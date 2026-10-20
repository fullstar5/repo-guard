import asyncio
import json

import httpx  # pyright: ignore[reportMissingImports]
from agent_experiments.agent_day2.agent import (
    TEST_MODEL_NAME,
    TEST_PR_ID,
    TEST_USER_ID,
    _assistant_turn,
    _call_llm,
    _print_block,
)
from agent_experiments.agent_day2.tools import BoundReviewTools, parse_tool_arguments
from agent_experiments.agent_day3.state import AgentState
from agent_experiments.agent_day4.agent import Day4Tools
from agent_experiments.agent_day4.agent import _execute as read_execute
from agent_experiments.agent_day5.agent import DAY5_TOOLS
from agent_experiments.agent_day5.agent import _execute as day5_execute
from agent_experiments.agent_day6.specialists import (
    FINISH_REVIEW,
    SPECIALIST_PROMPTS,
    SPECIALIST_TOOL_NAMES,
    aggregate_findings,
    slice_read_files,
    specialist_tools,
)
from app.services.openrouter_provider import OpenRouterReviewProvider
from app.services.review_file_cache import ReviewFileCache

MAX_ROUNDS = 12
_PREFETCH_CONCURRENCY = 4
_READ_TOOLS = {"get_file_content", "refresh_file_content", "get_related_files", "search_code"}

SYSTEM_PROMPT = (
    "You are the CodeGuard review orchestrator. "
    "The pull request is already selected. You are the only role that can read files.\n"
    "First list the changed files. Call submit_review_plan once, with every changed path, "
    "before any get_file_content call.\n"
    "disposition must be ignore, inspect, or inspect_carefully. "
    "Lockfiles, images, generated files, and README are ignore. "
    "Ordinary components are inspect. "
    "Authentication, payment, permission, migration, and external-input handling are inspect_carefully.\n"
    "After the plan is accepted, Python has already loaded every inspect and "
    "inspect_carefully file. Do not call get_file_content for those paths.\n"
    "Call get_related_files only for an inspect_carefully file, or for a related file "
    "you already read. It returns one hop of imports, at most 10 paths. "
    "Choose which of those paths to read with get_file_content. "
    "Call get_related_files again only when that new file must be followed one hop further.\n"
    "Then assign specialists in one response. Do not wait for one specialist before calling the next. "
    "Each specialist call sends only the paths in its arguments, "
    "and those paths must already have been read. Send at most 4 paths per call. "
    "Do not give a specialist files outside its assignment.\n"
    "Choose specialists by risk, and call more than one when a file has more than one risk:\n"
    "- ask_security_specialist: authentication, authorization, injection, XSS, CSRF, SSRF, "
    "path traversal, secrets, cryptography, data exposure. Use it for inspect_carefully files "
    "and for any diff that accepts external input.\n"
    "- ask_correctness_specialist: logic, null or empty data, error handling, state, "
    "concurrency, and boundary bugs. Use it for every inspect and inspect_carefully file.\n"
    "- ask_performance_specialist: queries in loops, N+1 fetches, unbounded reads, hot-path "
    "blocking calls, and repeated expensive work.\n"
    "- ask_reliability_specialist: timeouts, retries, idempotency, partial failure, "
    "transactions, and unreleased connections, files, or locks.\n"
    "- ask_contract_specialist: API shape, validation, migrations, events, and stored data "
    "that callers or older rows still depend on.\n"
    "- ask_maintainability_specialist: a rule copied in two places and updated in only one, "
    "or a name that contradicts the changed behavior. Do not call it for style.\n"
    "Do not call every specialist for every file. "
    "Do not write the review findings yourself.\n"
    "When the specialists you assigned have returned, call finish_review."
)

DAY6_TOOLS = [*DAY5_TOOLS, *specialist_tools(), FINISH_REVIEW]


async def _ask_specialist(
    client: httpx.AsyncClient,
    provider: OpenRouterReviewProvider,
    state: AgentState,
    specialty: str,
    arguments: dict[str, object],
    reports: list[dict[str, object]],
    model_name: str | None = None,
) -> dict[str, object]:
    """Open one specialist conversation on a slice of files already read.

    Args:
        client: HTTP client used for the specialist model call.
        provider: Parser for the specialist's findings JSON.
        state: Orchestrator memory. Only ``read_files`` is read.
        specialty: Prompt key, such as ``security``.
        arguments: ``paths`` and ``focus`` from the orchestrator.
        reports: Specialist reports collected in this run.

    Returns:
        The specialist summary and findings, or an error. The body contains
        only the assigned paths.
    """
    focus = arguments.get("focus")
    if not isinstance(focus, str) or not focus.strip():
        return {"error": "focus must be a non-empty string."}
    selected = slice_read_files(state.read_files, arguments.get("paths"))
    if "error" in selected:
        return selected
    files = selected["files"]
    if not isinstance(files, list):
        return {"error": "No files were selected."}
    paths = [str(item["path"]) for item in files if isinstance(item, dict)]
    message = await _call_llm(
        client,
        [
            {"role": "system", "content": SPECIALIST_PROMPTS[specialty]},
            {
                "role": "user",
                "content": json.dumps(
                    {"focus": focus.strip(), "files": files},
                    ensure_ascii=False,
                ),
            },
        ],
        enable_tools=False,
        model_name=model_name,
    )
    content = message.get("content")
    text = content.strip() if isinstance(content, str) else ""
    if not text:
        return {"error": f"{specialty} specialist returned no findings JSON.", "paths": paths}
    try:
        parsed = provider._parse_review_response(text)
    except (ValueError, TypeError) as exc:
        return {
            "error": f"{specialty} specialist did not return findings JSON: {exc}",
            "paths": paths,
        }
    allowed = set(paths)
    findings: list[dict[str, object]] = []
    for finding in parsed.findings:
        item = finding.model_dump()
        file_path = item.get("file_path")
        if file_path in allowed:
            findings.append(item)
        elif file_path in (None, "") and len(paths) == 1:
            item["file_path"] = paths[0]
            findings.append(item)
    report = {
        "specialist": specialty,
        "paths": paths,
        "summary": parsed.summary,
        "findings": findings,
    }
    reports.append(report)
    return report


async def _prefetch_planned_files(
    tools: Day4Tools,
    state: AgentState,
    plan: dict[str, str],
) -> dict[str, object]:
    """Load every planned inspect file in parallel.

    Args:
        tools: Day 4 tools bound to this pull request.
        state: Orchestrator memory. Successful reads are stored on it.
        plan: Accepted path dispositions.

    Returns:
        Paths whose bodies are ready, and any path that failed to load.
        File text is not included.
    """
    paths = [
        path
        for path, disposition in plan.items()
        if disposition in {"inspect", "inspect_carefully"} and path not in state.read_files
    ]
    semaphore = asyncio.Semaphore(_PREFETCH_CONCURRENCY)

    async def load(path: str) -> tuple[str, dict[str, object]]:
        async with semaphore:
            return path, await tools.read_path(path)

    loaded: list[str] = []
    failed: list[dict[str, object]] = []
    for path, result in await asyncio.gather(*(load(path) for path in paths)):
        if "error" in result:
            failed.append({"path": path, "error": result["error"]})
        else:
            state.read_files[path] = result
            loaded.append(path)
    return {"already_read": loaded, "prefetch_failed": failed}


async def _execute(
    client: httpx.AsyncClient,
    provider: OpenRouterReviewProvider,
    tools: Day4Tools,
    state: AgentState,
    plan: dict[str, str],
    reports: list[dict[str, object]],
    related_ok: set[str],
    name: str,
    arguments: dict[str, object],
    model_name: str | None = None,
    fetch_notes: list[str] | None = None,
) -> tuple[dict[str, object], bool]:
    """Run an orchestrator tool.

    Read tools stay on the Day 5 plan gate. Specialist tools open a new
    conversation and do not receive the GitHub token.

    Args:
        client: HTTP client for specialist model calls.
        provider: Findings parser.
        tools: Day 4 tools bound to this pull request.
        state: Orchestrator memory.
        plan: Accepted dispositions. Empty until the plan succeeds.
        reports: Specialist reports collected in this run.
        related_ok: Paths returned by get_related_files that may be read next.
        name: Tool name from the assistant message.
        arguments: Parsed arguments.

    Returns:
        The tool payload, and whether a saved file body was reused.
    """
    specialty = SPECIALIST_TOOL_NAMES.get(name)
    if specialty is not None:
        result = await _ask_specialist(
            client, provider, state, specialty, arguments, reports, model_name
        )
        return result, False
    if name == "finish_review":
        return aggregate_findings(reports), False
    if name == "submit_review_plan":
        result, cached = await day5_execute(tools, state, plan, name, arguments)
        if isinstance(result, dict) and result.get("accepted") is True:
            prefetched = await _prefetch_planned_files(tools, state, plan)
            failed = prefetched.get("prefetch_failed")
            if isinstance(failed, list) and fetch_notes is not None:
                for item in failed:
                    if isinstance(item, dict):
                        fetch_notes.append(f"{item.get('path')}: {item.get('error')}")
            result = {
                **result,
                **prefetched,
                "note": (
                    "inspect and inspect_carefully bodies are already loaded. "
                    "Assign specialists with those paths. "
                    "get_related_files returns one hop of imports, not a guessed path."
                ),
            }
        return result, cached

    path = arguments.get("path")
    path = path.strip() if isinstance(path, str) else ""
    if name == "get_related_files":
        if not plan:
            return {"error": "Call submit_review_plan before reading files."}, False
        if plan.get(path) != "inspect_carefully" and path not in related_ok:
            return {"error": f"{path} is not marked inspect_carefully."}, False
        result, cached = await read_execute(tools, state, name, arguments)
        related = result.get("related") if isinstance(result, dict) else None
        if isinstance(related, list):
            for item in related:
                if isinstance(item, str):
                    related_ok.add(item)
        return result, cached
    if name == "get_file_content" and path in related_ok:
        return await read_execute(tools, state, name, arguments)
    return await day5_execute(tools, state, plan, name, arguments)


async def run_agent(
    user_text: str,
    *,
    user_id: int,
    pull_request_id: int,
    model_name: str | None = None,
    save_checkpoint: bool = True,
    file_cache: ReviewFileCache | None = None,
) -> dict[str, object]:
    """Plan the review, assign specialists, and merge their findings.

    Args:
        user_text: The review request.
        user_id: Local user id. Production passes the repository owner.
            This function does not substitute a test user.
        pull_request_id: Local pull request id. Production passes the job's pull request.
            This function does not substitute a test pull request.
        model_name: OpenRouter model id. The experiment default is used when omitted.
        save_checkpoint: Write ``agent_day3/checkpoint.json`` after tool rounds.
            Production jobs leave this false.
        file_cache: Redis file cache for a production review job.
            Experiment runs leave this unset.

    Returns:
        The aggregated summary and findings. Findings are empty when no specialist ran.
    """
    state = AgentState(
        user_id=user_id,
        pull_request_id=pull_request_id,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
    )
    plan: dict[str, str] = {}
    reports: list[dict[str, object]] = []
    related_ok: set[str] = set()
    fetch_notes: list[str] = []
    print("========== AGENT RUN ==========")
    print()
    _print_block("USER", user_text)

    timeout = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        tools = Day4Tools(
            BoundReviewTools(state.user_id, state.pull_request_id, client),
            file_cache=file_cache,
        )
        provider = OpenRouterReviewProvider(client, model_name or TEST_MODEL_NAME)
        finished = False
        for _ in range(MAX_ROUNDS):
            state.round_index += 1
            message = await _call_llm(
                client, state.messages, DAY6_TOOLS, model_name=model_name
            )
            tool_calls = message.get("tool_calls") or []
            if not isinstance(tool_calls, list) or not tool_calls:
                break
            state.messages.append(_assistant_turn(message))
            indexed: list[tuple[int, dict[str, object]]] = []
            for index, tool_call in enumerate(tool_calls):
                if isinstance(tool_call, dict):
                    indexed.append((index, tool_call))

            async def run_one(tool_call: dict[str, object]) -> tuple[str, dict[str, object], dict[str, object], bool, str]:
                function = tool_call.get("function")
                if not isinstance(function, dict):
                    function = {}
                name = str(function.get("name") or "")
                raw_arguments = function.get("arguments")
                try:
                    arguments = parse_tool_arguments(raw_arguments)
                    result, cached = await _execute(
                        client,
                        provider,
                        tools,
                        state,
                        plan,
                        reports,
                        related_ok,
                        name,
                        arguments,
                        model_name,
                        fetch_notes,
                    )
                except Exception as exc:
                    arguments = {"raw": raw_arguments}
                    result, cached = {"error": f"{type(exc).__name__}: {exc}"}, False
                tool_call_id = tool_call.get("id")
                return (
                    name,
                    arguments if isinstance(arguments, dict) else {"raw": raw_arguments},
                    result,
                    cached,
                    tool_call_id if isinstance(tool_call_id, str) else "",
                )

            def phase(name: str) -> int:
                if name in SPECIALIST_TOOL_NAMES:
                    return 2
                if name == "finish_review":
                    return 3
                if name in _READ_TOOLS:
                    return 1
                return 0

            pending = indexed
            outcomes: dict[int, tuple[str, dict[str, object], dict[str, object], bool, str]] = {}
            for step in range(4):
                group = []
                for index, tool_call in pending:
                    function = tool_call.get("function")
                    function = function if isinstance(function, dict) else {}
                    if phase(str(function.get("name") or "")) == step:
                        group.append((index, tool_call))
                if not group:
                    continue
                if step in {1, 2} and len(group) > 1:
                    ran = await asyncio.gather(*(run_one(tool_call) for _, tool_call in group))
                    for (index, _), outcome in zip(group, ran):
                        outcomes[index] = outcome
                else:
                    for index, tool_call in group:
                        outcomes[index] = await run_one(tool_call)

            for index, _tool_call in indexed:
                name, arguments, result, cached, tool_call_id = outcomes[index]
                print("LLM:")
                print(f"Tool Call -> {name}")
                print(f"Arguments -> {json.dumps(arguments, ensure_ascii=False)}")
                print(f"Cached -> {cached}")
                print()
                _print_block("TOOL", result)
                state.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                if name == "finish_review":
                    finished = True
            if save_checkpoint:
                state.save()
            if finished:
                break
        merged = aggregate_findings(reports)
        read_windows: list[list[str]] = []
        for path, record in state.read_files.items():
            file_windows = record.get("windows") if isinstance(record, dict) else None
            if not isinstance(file_windows, list):
                continue
            for window in file_windows:
                if isinstance(window, str):
                    read_windows.append([path, window])
        merged["finished"] = finished
        merged["windows"] = read_windows
        merged["fetch_notes"] = fetch_notes
        if save_checkpoint:
            state.save()
        _print_block("PLAN", plan)
        _print_block("SPECIALISTS", [report.get("specialist") for report in reports])
        _print_block("AGGREGATED", merged)
        return merged


async def _main() -> None:
    """Run one multi-specialist review from the command line.

    Returns:
        None.
    """
    import sys

    question = " ".join(sys.argv[1:]).strip() or (
        "Review this pull request. Plan the files, assign specialists, "
        "and finish with their merged findings."
    )
    await run_agent(
        question,
        user_id=TEST_USER_ID,
        pull_request_id=TEST_PR_ID,
    )


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
