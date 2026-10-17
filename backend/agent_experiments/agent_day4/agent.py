import json
from urllib.parse import quote

import httpx  # pyright: ignore[reportMissingImports]
from agent_experiments.agent_day2.agent import (
    MAX_ROUNDS,
    TEST_MODEL_NAME,
    TEST_PR_ID,
    TEST_USER_ID,
    _assistant_turn,
    _call_llm,
    _print_block,
    _record_findings,
)
from agent_experiments.agent_day2.tools import TOOLS as DAY2_TOOLS
from agent_experiments.agent_day2.tools import BoundReviewTools, parse_tool_arguments
from agent_experiments.agent_day3.agent import REFRESH_FILE_CONTENT
from agent_experiments.agent_day3.state import AgentState
from agent_experiments.agent_day4.related import (
    is_ignored_path,
    related_paths,
    search_hits,
)
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.services.github_pr_files import (
    fetch_github_file_text,
    get_pull_request_with_repository,
)
from app.services.github_tokens import GitHubTokenUnavailable
from app.services.openrouter_provider import OpenRouterReviewProvider

TOOL_TEXT_LIMIT = min(get_settings().review_pack_max_chars, 8000)

SYSTEM_PROMPT = (
    "You are a CodeGuard review assistant. "
    "The pull request for this run is already selected. "
    "Use tools when you need information. "
    "To judge a change, you may need a file that this pull request did not modify. "
    "Call get_related_files on a file you already read, then call get_file_content "
    "only for related paths you actually need. "
    "get_related_files returns one hop, not the whole repository. "
    "Use search_code to find a string in changed filenames and patches. "
    "Do not read lockfiles, images, or generated files.\n"
    "If the user asks for problems, finish with one JSON object and no markdown fence:\n"
    '{"summary": "...", "findings": [{"severity": "low|medium|high|critical", '
    '"summary": "...", "file_path": "path or null", "start_line": 10, '
    '"end_line": 12, "suggestion": "... or null"}]}\n'
    "file_path must come from a tool result. Do not invent file contents."
)

GET_RELATED_FILES: dict[str, object] = {
    "type": "function",
    "function": {
        "name": "get_related_files",
        "description": (
            "List files directly imported by one file already read in this review. "
            "Returns at most 10 same-repository paths and does not include their contents. "
            "Does not follow imports of those files. "
            "Skip this for lockfiles and files that were already read."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path already returned by get_file_content.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}

SEARCH_CODE: dict[str, object] = {
    "type": "function",
    "function": {
        "name": "search_code",
        "description": (
            "Search changed filenames and stored patches for a string. "
            "Does not search the rest of the repository and does not return full files."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Case-insensitive text to find."},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}


def _day4_tools() -> list[dict[str, object]]:
    """Add Day 4 tools to the Day 2 schemas.

    Returns:
        Tool schemas for this experiment.
    """
    description = (
        "Read one repository file needed to review the selected pull request. "
        "Changed files include their patch. A file that was not changed is loaded "
        "from the pull request head as context. "
        "If this review already read the path, the saved body is returned."
    )
    tools: list[dict[str, object]] = []
    for tool in DAY2_TOOLS:
        function = tool.get("function")
        if isinstance(function, dict) and function.get("name") == "get_file_content":
            tools.append({**tool, "function": {**function, "description": description}})
        else:
            tools.append(tool)
    tools.extend([REFRESH_FILE_CONTENT, GET_RELATED_FILES, SEARCH_CODE])
    return tools


DAY4_TOOLS = _day4_tools()


def _clip(text: str | None) -> dict[str, object]:
    """Cut one text field down to the per-tool limit.

    Args:
        text: File text, or None.

    Returns:
        The text and whether it was cut. The limit is 8000 characters or
        ``REVIEW_PACK_MAX_CHARS``, whichever is smaller.
    """
    if text is None:
        return {"text": None, "truncated": False}
    if len(text) <= TOOL_TEXT_LIMIT:
        return {"text": text, "truncated": False}
    return {"text": text[:TOOL_TEXT_LIMIT], "truncated": True, "original_chars": len(text)}


def _saved_text(saved: dict[str, object]) -> str:
    """Read patch or source text out of a stored file result.

    Args:
        saved: One value from ``read_files``.

    Returns:
        The best available text, or an empty string.
    """
    for key in ("source_text", "patch"):
        body = saved.get(key)
        if isinstance(body, dict) and isinstance(body.get("text"), str):
            return body["text"]
    return ""


class Day4Tools:
    """Day 2 tools plus one-hop imports and patch search."""

    def __init__(self, base: BoundReviewTools) -> None:
        """Store the bound Day 2 tools.

        Args:
            base: Tools already limited to one user and one pull request.

        Returns:
            None.
        """
        self.base = base

    async def read_path(self, path: str) -> dict[str, object]:
        """Read a changed file, or a same-repository file from the pull request head.

        Args:
            path: Repository path.

        Returns:
            Patch and source for a changed file. Unchanged files have status
            ``context`` and no patch. Ignored paths return an error.
        """
        if is_ignored_path(path):
            return {"error": f"{path} is ignored for review."}
        changed = await self.base.get_file_content({"path": path})
        if "error" not in changed:
            return changed
        if not str(changed.get("error", "")).startswith("No changed file"):
            return changed

        async with AsyncSessionLocal() as db:
            pull_request, repository = await get_pull_request_with_repository(
                db,
                self.base.pull_request_id,
                self.base.user_id,
            )
            if pull_request is None or repository is None:
                await db.rollback()
                return {"error": "Pull request was not found for this user."}
            owner = repository.owner_login
            repo = repository.name
            ref = pull_request.head_branch
            await db.rollback()

        contents_url = (
            f"https://api.github.com/repos/{owner}/{repo}/contents/"
            f"{quote(path, safe='/')}?ref={quote(ref, safe='')}"
        )
        try:
            text = await self.base.github_tokens.run(
                lambda token, contents_url=contents_url, owner=owner, repo=repo: fetch_github_file_text(
                    self.base.http_client,
                    token,
                    contents_url,
                    owner_login=owner,
                    repo_name=repo,
                )
            )
        except GitHubTokenUnavailable as exc:
            return {"error": str(exc)}
        if not text:
            return {"error": f"Could not read {path} from the pull request head."}
        return {
            "path": path,
            "status": "context",
            "patch": None,
            "source_text": _clip(text),
            "note": "Not part of the diff. Loaded from the pull request head as context.",
        }

    async def get_related_files(self, state: AgentState, path: str) -> dict[str, object]:
        """List one hop of imports for a file this review already read.

        Args:
            state: Working memory that holds the file body.
            path: File to scan.

        Returns:
            Related paths, or an error when that file has not been read.
        """
        saved = state.read_files.get(path)
        if not isinstance(saved, dict):
            return {"error": f"Call get_file_content for {path} before asking for related files."}
        paths = related_paths(path, _saved_text(saved), set(state.read_files))
        return {"path": path, "related": paths, "truncated": len(paths) >= 10}

    async def search_code(self, query: str) -> dict[str, object]:
        """Search synced filenames and patches.

        Args:
            query: Text to find.

        Returns:
            Hits, or an error when the query or the pull request is unavailable.
        """
        if not query.strip():
            return {"error": "query must be a non-empty string."}
        files = await self.base._owned_files()
        if isinstance(files, dict):
            return files
        return search_hits([(item.filename, item.patch) for item in files], query.strip())


def _summary(name: str, arguments: dict[str, object], result: dict[str, object], cached: bool) -> dict[str, object]:
    """Keep a short record of one tool call.

    Args:
        name: Tool name.
        arguments: Parsed arguments.
        result: Tool payload.
        cached: True when a saved file body was reused.

    Returns:
        A summary without the file body.
    """
    target = arguments.get("path") or arguments.get("query")
    return {
        "name": name,
        "path": target if isinstance(target, str) else None,
        "cached": cached,
        "error": result.get("error"),
        "note": result.get("note"),
    }


async def _execute(
    tools: Day4Tools,
    state: AgentState,
    name: str,
    arguments: dict[str, object],
) -> tuple[dict[str, object], bool]:
    """Run one Day 4 tool.

    Args:
        tools: Bound tools for this pull request.
        state: Working memory for this review.
        name: Tool name from the assistant message.
        arguments: Parsed function arguments.

    Returns:
        The tool payload, and True when a file body came from ``read_files``.
    """
    path = arguments.get("path")
    if name == "get_related_files":
        if not isinstance(path, str) or not path.strip():
            return {"error": "path must be a non-empty string."}, False
        return await tools.get_related_files(state, path.strip()), False
    if name == "search_code":
        query = arguments.get("query")
        if not isinstance(query, str):
            return {"error": "query must be a string."}, False
        return await tools.search_code(query), False

    if name in {"get_file_content", "refresh_file_content"}:
        if not isinstance(path, str) or not path.strip():
            return {"error": "path must be a non-empty string."}, False
        path = path.strip()
        if name == "get_file_content" and path in state.read_files:
            cached = dict(state.read_files[path])
            cached["cached"] = True
            cached["note"] = "Already read in this review. Full text was not fetched again."
            return cached, True
        result = await tools.read_path(path)
        if "error" not in result:
            state.read_files[path] = result
        return result, False

    result = await tools.base.execute(name, arguments)
    return result, False


async def run_agent(user_text: str, *, resume: bool) -> str:
    """Run one Day 4 review, restoring the Day 3 checkpoint format when requested.

    Args:
        user_text: The question for this run.
        resume: True to continue ``agent_day3/checkpoint.json``.

    Returns:
        The final assistant text, or an empty string when the round limit is hit.
    """
    if resume:
        state = AgentState.load()
        state.messages.append({"role": "user", "content": user_text})
        if state.messages and state.messages[0].get("role") == "system":
            state.messages[0]["content"] = SYSTEM_PROMPT
    else:
        state = AgentState(
            user_id=TEST_USER_ID,
            pull_request_id=TEST_PR_ID,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
        )

    print("========== AGENT RUN ==========")
    print()
    _print_block("USER", user_text)
    timeout = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        tools = Day4Tools(BoundReviewTools(state.user_id, state.pull_request_id, client))
        provider = OpenRouterReviewProvider(client, TEST_MODEL_NAME)
        for _ in range(MAX_ROUNDS):
            state.round_index += 1
            message = await _call_llm(client, state.messages, DAY4_TOOLS)
            tool_calls = message.get("tool_calls") or []
            if not isinstance(tool_calls, list) or not tool_calls:
                content = message.get("content")
                final_text = content.strip() if isinstance(content, str) else ""
                state.messages.append({"role": "assistant", "content": final_text})
                state.save()
                _print_block("FINAL", final_text or "(empty content)")
                _record_findings(provider, final_text)
                return final_text

            state.messages.append(_assistant_turn(message))
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function")
                if not isinstance(function, dict):
                    function = {}
                name = str(function.get("name") or "")
                raw_arguments = function.get("arguments")
                try:
                    arguments = parse_tool_arguments(raw_arguments)
                    result, cached = await _execute(tools, state, name, arguments)
                except Exception as exc:
                    arguments = {"raw": raw_arguments}
                    result = {"error": f"{type(exc).__name__}: {exc}"}
                    cached = False
                print("LLM:")
                print(f"Tool Call -> {name}")
                print(f"Arguments -> {json.dumps(arguments, ensure_ascii=False)}")
                print(f"Cached -> {cached}")
                print()
                _print_block("TOOL", result)
                tool_call_id = tool_call.get("id")
                state.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id if isinstance(tool_call_id, str) else "",
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                state.tool_summaries.append(
                    {"round": state.round_index, **_summary(name, arguments, result, cached)}
                )
            state.save()
    _print_block("FINAL", f"Stopped after {MAX_ROUNDS} rounds.")
    return ""


async def _main() -> None:
    import sys

    question = " ".join(sys.argv[1:]).strip() or (
        "Read backend/agent_experiments/agent_day2/tools.py, "
        "follow its project imports, and point out problems that depend on those files."
    )
    await run_agent(question, resume=False)


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())