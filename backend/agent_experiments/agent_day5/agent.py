import json

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
from agent_experiments.agent_day2.tools import BoundReviewTools, parse_tool_arguments
from agent_experiments.agent_day3.state import AgentState
from agent_experiments.agent_day4.agent import DAY4_TOOLS, Day4Tools
from agent_experiments.agent_day4.agent import _execute as read_execute
from agent_experiments.agent_day4.related import is_ignored_path
from app.services.openrouter_provider import OpenRouterReviewProvider

DISPOSITIONS = {"ignore", "inspect", "inspect_carefully"}

SYSTEM_PROMPT = (
    "You are a CodeGuard review planner. "
    "The pull request is already selected. "
    "First list the changed files. Then call submit_review_plan once, "
    "with every changed path, before any get_file_content call.\n"
    "disposition must be ignore, inspect, or inspect_carefully. "
    "Lockfiles, images, generated files, and README are ignore. "
    "Ordinary components are inspect. "
    "Authentication, payment, permission, and migration files are inspect_carefully.\n"
    "focus is a short reason, such as auth, null handling, or query count. "
    "related lists repository paths you may need later; use an empty array if none.\n"
    "After the plan is accepted, read inspect and inspect_carefully files only. "
    "Call get_related_files only for an inspect_carefully file. "
    "Do not read ignore files.\n"
    "When you report problems, finish with one JSON object and no markdown fence:\n"
    '{"summary":"...","findings":[{"severity":"low|medium|high|critical",'
    '"summary":"...","file_path":"path or null","start_line":10,'
    '"end_line":12,"suggestion":"... or null"}]}'
)

SUBMIT_REVIEW_PLAN: dict[str, object] = {
    "type": "function",
    "function": {
        "name": "submit_review_plan",
        "description": (
            "Submit one disposition for every changed file before reading contents. "
            "ignore: do not read. inspect: read the file. "
            "inspect_carefully: read the file and you may request its related files."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "disposition": {"type": "string"},
                            "focus": {"type": "string"},
                            "related": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["path", "disposition", "focus", "related"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["files"],
            "additionalProperties": False,
        },
    },
}

DAY5_TOOLS = [*DAY4_TOOLS, SUBMIT_REVIEW_PLAN]


async def _submit_plan(
    tools: Day4Tools,
    plan: dict[str, str],
    files: object,
) -> dict[str, object]:
    """Accept a plan only when every changed path is classified.

    Paths the existing filter ignores are forced to ignore.

    Args:
        tools: Bound tools used to load the changed-file list.
        plan: Path to disposition. Empty until the plan succeeds.
        files: The model's ``files`` argument.

    Returns:
        The normalized plan, or an error naming what must be fixed.
    """
    if not isinstance(files, list) or not files:
        return {"error": "files must be a non-empty list."}

    owned = await tools.base._owned_files()
    if isinstance(owned, dict):
        return owned
    changed = {item.filename for item in owned}

    proposed: dict[str, dict[str, object]] = {}
    for item in files:
        if not isinstance(item, dict):
            return {"error": "Each file entry must be an object."}
        path = item.get("path")
        disposition = item.get("disposition")
        focus = item.get("focus")
        related = item.get("related")
        if not isinstance(path, str) or path not in changed:
            return {"error": f"{path} is not a changed file in this pull request."}
        if disposition not in DISPOSITIONS:
            return {"error": f"{path} has an unknown disposition."}
        if not isinstance(focus, str) or not isinstance(related, list):
            return {"error": f"{path} needs a focus string and a related array."}
        if is_ignored_path(path):
            disposition = "ignore"
        proposed[path] = {
            "path": path,
            "disposition": disposition,
            "focus": focus,
            "related": [entry for entry in related if isinstance(entry, str)],
        }

    missing = sorted(changed - proposed.keys())
    if missing:
        return {"error": "Plan must include every changed file.", "missing": missing}

    plan.clear()
    plan.update({path: str(entry["disposition"]) for path, entry in proposed.items()})
    ordered = [proposed[item.filename] for item in owned]
    return {"accepted": True, "files": ordered}


async def _execute(
    tools: Day4Tools,
    state: AgentState,
    plan: dict[str, str],
    name: str,
    arguments: dict[str, object],
) -> tuple[dict[str, object], bool]:
    """Run a tool, refusing reads that the plan did not allow.

    Args:
        tools: Day 4 tools bound to this pull request.
        state: Working memory from earlier days.
        plan: Accepted dispositions. Empty until the plan succeeds.
        name: Tool name from the assistant message.
        arguments: Parsed arguments.

    Returns:
        The tool payload, and whether a saved file body was reused.
    """
    if name == "submit_review_plan":
        result = await _submit_plan(tools, plan, arguments.get("files"))
        return result, False

    path = arguments.get("path")
    path = path.strip() if isinstance(path, str) else ""
    if name in {"get_file_content", "refresh_file_content", "get_related_files"} and not plan:
        return {"error": "Call submit_review_plan before reading files."}, False
    if name in {"get_file_content", "refresh_file_content"} and plan.get(path) not in {
        "inspect",
        "inspect_carefully",
    }:
        return {"error": f"{path} is not marked inspect or inspect_carefully."}, False
    if name == "get_related_files" and plan.get(path) != "inspect_carefully":
        return {"error": f"{path} is not marked inspect_carefully."}, False
    return await read_execute(tools, state, name, arguments)


async def run_agent(user_text: str) -> str:
    """Plan the review, then read only the files the plan allows.

    Args:
        user_text: The review request.

    Returns:
        The final assistant text, or an empty string when the round limit is hit.
    """
    state = AgentState(
        user_id=TEST_USER_ID,
        pull_request_id=TEST_PR_ID,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
    )
    plan: dict[str, str] = {}
    print("========== AGENT RUN ==========")
    print()
    _print_block("USER", user_text)

    timeout = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        tools = Day4Tools(BoundReviewTools(state.user_id, state.pull_request_id, client))
        provider = OpenRouterReviewProvider(client, TEST_MODEL_NAME)
        for _ in range(MAX_ROUNDS):
            state.round_index += 1
            message = await _call_llm(client, state.messages, DAY5_TOOLS)
            tool_calls = message.get("tool_calls") or []
            if not isinstance(tool_calls, list) or not tool_calls:
                content = message.get("content")
                final_text = content.strip() if isinstance(content, str) else ""
                state.messages.append({"role": "assistant", "content": final_text})
                state.save()
                _print_block("PLAN", plan)
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
                    result, cached = await _execute(tools, state, plan, name, arguments)
                except Exception as exc:
                    arguments = {"raw": raw_arguments}
                    result, cached = {"error": f"{type(exc).__name__}: {exc}"}, False
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
    _print_block("FINAL", f"Stopped after {MAX_ROUNDS} rounds.")
    return ""


async def _main() -> None:
    """Run one planned review from the command line.

    Returns:
        None.
    """
    import sys

    question = " ".join(sys.argv[1:]).strip() or (
        "Review this pull request. Plan which files to ignore, inspect, "
        "or inspect carefully before reading them."
    )
    await run_agent(question)


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
