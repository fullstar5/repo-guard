import json

import httpx  # pyright: ignore[reportMissingImports]
from agent_experiments.agent_day2.agent import (
    MAX_ROUNDS,
    TEST_PR_ID,
    TEST_USER_ID,
    _assistant_turn,
    _call_llm,
    _print_block,
    _record_findings,
)
from agent_experiments.agent_day2.tools import TOOLS as DAY2_TOOLS
from agent_experiments.agent_day2.tools import BoundReviewTools, parse_tool_arguments
from agent_experiments.agent_day3.state import AgentState
from app.services.openrouter_provider import OpenRouterReviewProvider

SYSTEM_PROMPT = (
    "You are a CodeGuard review assistant. "
    "The pull request for this run is already selected. "
    "Do not ask the user for a repository name, pull request number, or token. "
    "Use the provided tools when you need information. Read only the files required to answer.\n"
    "If a file body is already in this conversation, analyze that body. "
    "Call get_file_content for a file you still need to inspect. "
    "Call refresh_file_content only when the latest user message explicitly asks to refresh, re-read, or fetch that file again.\n"
    "Examples:\n"
    "User: Does backend/foo.py have any other problems?\n"
    "Decision: do not call refresh_file_content. Answer from the existing body, or call get_file_content if that body is not in the conversation.\n"
    "User: Refresh backend/foo.py and look again.\n"
    "Decision: call refresh_file_content with path backend/foo.py.\n"
    "If the user asks for a review or for problems, finish with one JSON object and no markdown fence:\n"
    "{\n"
    '  "summary": "short overall summary",\n'
    '  "findings": [\n'
    "    {\n"
    '      "severity": "low|medium|high|critical",\n'
    '      "summary": "short actionable issue summary",\n'
    '      "file_path": "path or null",\n'
    '      "start_line": 10,\n'
    '      "end_line": 12,\n'
    '      "suggestion": "optional concrete fix or null"\n'
    "    }\n"
    "  ]\n"
    "}\n"
    "When there are no real issues, findings is an empty array. "
    "file_path must be a path returned by a tool. Do not invent file contents."
)


REFRESH_FILE_CONTENT: dict[str, object] = {
    "type": "function",
    "function": {
        "name": "refresh_file_content",
        "description": (
            "Fetch one changed file from GitHub again and replace the saved copy. "
            "Call this only when the latest user message explicitly asks to refresh, re-read, or fetch that file again. "
            "Do not call this when the user only asks for more problems, another review, or a summary."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path returned by get_pull_request_files.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}

GET_FILE_CONTENT_DESCRIPTION = (
    "Read one changed file from the selected pull request. "
    "Use this when the patch or source is not already in the conversation. "
    "If this review already read the path, the saved body is returned and GitHub is not called. "
    "Do not use this when the user explicitly asked to refresh or re-read the file; use refresh_file_content."
)


def _day3_tools() -> list[dict[str, object]]:
    """Return Day 2 tools with a Day 3 description for reading a file.

    Returns:
        Tool schemas sent to the model, including ``refresh_file_content``.
    """
    tools: list[dict[str, object]] = []
    for tool in DAY2_TOOLS:
        function = tool.get("function")
        if isinstance(function, dict) and function.get("name") == "get_file_content":
            tools.append({**tool, "function": {**function, "description": GET_FILE_CONTENT_DESCRIPTION}})
        else:
            tools.append(tool)
    tools.append(REFRESH_FILE_CONTENT)
    return tools


DAY3_TOOLS = _day3_tools()


def _summary(name: str, arguments: dict[str, object], result: dict[str, object], cached: bool) -> dict[str, object]:
    """Keep a short record of one tool call.
    Args:
        name: Tool name.
        arguments: Parsed arguments.
        result: Tool payload.
        cached: True when the file body was served from memory.
    Returns:
        A summary without the file body.
    """
    path = arguments.get("path")
    return {
        "name": name,
        "path": path if isinstance(path, str) else None,
        "cached": cached,
        "error": result.get("error"),
        "note": result.get("note"),
        "file_count": result.get("file_count"),
    }


async def _execute(
    tools: BoundReviewTools,
    state: AgentState,
    name: str,
    arguments: dict[str, object],
) -> tuple[dict[str, object], bool]:
    """Run one tool, reusing a file body that this review already read.

    ``get_file_content`` returns the saved body for a path already in ``read_files``.
    ``refresh_file_content`` always reads from GitHub and replaces that saved body.
    The model chooses which name to send.

    Args:
        tools: Day 2 tools bound to the checkpoint's user and pull request.
        state: Working memory for this review.
        name: Tool name from the assistant message.
        arguments: Parsed function arguments.

    Returns:
        The tool payload, and True when it came from ``read_files``.
    """
    path = arguments.get("path")
    if name == "get_file_content" and isinstance(path, str) and path in state.read_files:
        cached = dict(state.read_files[path])
        cached["cached"] = True
        cached["note"] = "Already read in this review. Full text was not fetched again."
        return cached, True

    fetch_name = "get_file_content" if name == "refresh_file_content" else name
    result = await tools.execute(fetch_name, arguments)
    if fetch_name == "get_file_content" and isinstance(path, str) and "error" not in result:
        state.read_files[path] = result
    return result, False


async def run_agent(
    user_text: str, *, resume: bool
) -> str:
    """Continue one review, restoring the checkpoint when requested.
    Args:
        user_text: The question appended to this run, including a resumed one.
        resume: True to load ``checkpoint.json`` instead of starting over.
    Returns:
        The final assistant text, or an empty string when the round limit is hit.
    """
    if resume:
        state = AgentState.load()
        if state.user_id != TEST_USER_ID or state.pull_request_id != TEST_PR_ID:
            raise RuntimeError("Checkpoint belongs to a different user or pull request.")
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
    _print_block(
        "STATE",
        {
            "user_id": state.user_id,
            "pull_request_id": state.pull_request_id,
            "round_index": state.round_index,
            "read_files": sorted(state.read_files),
            "resume": resume,
        },
    )
    _print_block("USER", user_text)

    timeout = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        tools = BoundReviewTools(state.user_id, state.pull_request_id, client)
        provider = OpenRouterReviewProvider(client, "nvidia/nemotron-3.5-lightning:free")
        for _ in range(MAX_ROUNDS):
            state.round_index += 1
            message = await _call_llm(client, state.messages, DAY3_TOOLS)
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
                    arguments = parse_tool_arguments(raw_arguments=raw_arguments)
                    result, cached = await _execute(
                        tools=tools,
                        state=state,
                        name=name,
                        arguments=arguments,
                    )
                except Exception as exc:
                    arguments = {"raw": raw_arguments}
                    result = {"error": f"{type(exc).__name__}: {exc}"}
                    cached = False

                state.tool_summaries.append(
                    {"round": state.round_index, **_summary(name, arguments, result, cached)}
                )
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
            state.save()

    state.save()
    _print_block("FINAL", f"Stopped after {MAX_ROUNDS} rounds.")
    return ""


async def _main() -> None:
    import sys
    args = sys.argv[1:]
    resume = False
    if args and args[0] == "--resume":
        resume = True
        args = args[1:]
    question = " ".join(args).strip()
    if not question:
        question = (
            "Does the authentication file you already read have any other problems?"
            if resume
            else "Read the authentication-related changes and point out the problems."
        )
    await run_agent(question, resume=resume)
if __name__ == "__main__":
    import asyncio
    import json
    asyncio.run(_main())
        

        
