import json
import os

import httpx  # pyright: ignore[reportMissingImports]
from app.core.config import get_settings
from app.services.openrouter_provider import OpenRouterReviewProvider
from agent_experiments.agent_day2.tools import TOOLS, BoundReviewTools, parse_tool_arguments

settings = get_settings()

MAX_ROUNDS = 8
TEST_MODEL_NAME = "nvidia/nemotron-3.5-lightning:free"
SYSTEM_PROMPT = (
    "你是 CodeGuard 的 review 助手。"
    "这一轮要看的 pull request 已经选定，不要向用户索要仓库名、PR 编号或 token。"
    "需要信息时使用提供的工具。只读取回答所需要的文件。\n"
    "如果用户只想知道改了哪些文件，列出文件即可，不要逐个读取全文。\n"
    "如果用户要求审查或指出问题，最后只输出一个 JSON 对象，不要用 markdown 围栏：\n"
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
    "没有实质问题时 findings 为空数组。"
    "file_path 必须来自工具返回的路径。不要编造文件内容。"
)


def bound_ids_from_env() -> tuple[int, int]:
    """Read the local user and pull request this run is allowed to see.

    Returns:
        ``(user_id, pull_request_id)``.

    Raises:
        RuntimeError: Either variable is missing or not an integer.
    """
    user_raw = os.environ.get("AGENT_DAY2_USER_ID", "").strip()
    pull_request_raw = os.environ.get("AGENT_DAY2_PULL_REQUEST_ID", "").strip()
    if not user_raw or not pull_request_raw:
        raise RuntimeError(
            "Set AGENT_DAY2_USER_ID and AGENT_DAY2_PULL_REQUEST_ID to local ids. "
            "The pull request id is the number in /pull-requests/{id}."
        )
    try:
        return int(user_raw), int(pull_request_raw)
    except ValueError as exc:
        raise RuntimeError("AGENT_DAY2_USER_ID and AGENT_DAY2_PULL_REQUEST_ID must be integers.") from exc


def _print_block(label: str, body: object) -> None:
    """Print one trace section.

    Args:
        label: Section name, such as ``USER`` or ``TOOL``.
        body: Text or a JSON-able object.

    Returns:
        None.
    """
    if not isinstance(body, str):
        body = json.dumps(body, ensure_ascii=False, indent=2)
    print(f"{label}:")
    print(body)
    print()


async def _call_llm(
    client: httpx.AsyncClient,
    messages: list[dict[str, object]],
) -> dict[str, object]:
    """Send one Chat Completions request that includes the Day 2 tools.

    Args:
        client: Async HTTP client. The caller owns its timeout.
        messages: Transcript so far, including tool results.

    Returns:
        The assistant message object from the first choice.

    Raises:
        httpx.HTTPStatusError: OpenRouter returned a non-2xx response.
        RuntimeError: The payload has no assistant message.
    """
    response = await client.post(
        f"{settings.open_router_base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.open_router_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": settings.app_public_url,
            "X-OpenRouter-Title": settings.app_name,
        },
        json={
            "model": TEST_MODEL_NAME,
            "temperature": 0,
            "messages": messages,
            "tools": TOOLS,
            "tool_choice": "auto",
        },
    )
    if response.is_error:
        print(response.status_code)
        print(response.text)
    response.raise_for_status()

    payload = response.json()
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError(f"OpenRouter returned no choices: {payload}")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise RuntimeError(f"OpenRouter returned no assistant message: {payload}")
    return message


def _assistant_turn(message: dict[str, object]) -> dict[str, object]:
    """Copy the assistant message that must be replayed before tool results.

    Args:
        message: Assistant message from OpenRouter.

    Returns:
        Role, content, and tool calls. Reasoning details are kept when present.
    """
    turn: dict[str, object] = {
        "role": "assistant",
        "content": message.get("content"),
        "tool_calls": message.get("tool_calls") or [],
    }
    reasoning_details = message.get("reasoning_details")
    if reasoning_details is not None:
        turn["reasoning_details"] = reasoning_details
    return turn


def _record_findings(provider: OpenRouterReviewProvider, final_text: str) -> None:
    """Parse a final answer with the existing review finding parser.

    Args:
        provider: Provider used only for ``_parse_review_response``.
        final_text: Assistant text after the tool loop stops.

    Returns:
        None. Parsed drafts are printed. A missing or invalid JSON object is
        printed as ``FINDINGS`` and does not raise.
    """
    if not final_text:
        _print_block("FINDINGS", "not parsed: empty final answer")
        return
    try:
        parsed = provider._parse_review_response(final_text)
    except (ValueError, TypeError) as exc:
        _print_block("FINDINGS", f"not parsed: {exc}")
        return
    _print_block("SUMMARY", parsed.summary)
    _print_block(
        "FINDINGS",
        [finding.model_dump() for finding in parsed.findings],
    )


async def run_agent(user_text: str, *, user_id: int, pull_request_id: int) -> str:
    """Run the tool loop for one question about the bound pull request.

    Args:
        user_text: The question for this run.
        user_id: Local user id. Injected into tools, not into the tool schema.
        pull_request_id: Local pull request id. Injected the same way.

    Returns:
        The final assistant text, or an empty string when the round limit is hit
        before an answer.
    """
    messages: list[dict[str, object]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]

    print("========== AGENT RUN ==========")
    print()
    _print_block(
        "BOUND",
        {"user_id": user_id, "pull_request_id": pull_request_id},
    )
    _print_block("USER", user_text)

    timeout = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        tools = BoundReviewTools(user_id, pull_request_id, client)
        provider = OpenRouterReviewProvider(client, TEST_MODEL_NAME)
        for _round in range(MAX_ROUNDS):
            message = await _call_llm(client, messages)
            tool_calls = message.get("tool_calls") or []
            if not isinstance(tool_calls, list) or not tool_calls:
                content = message.get("content")
                final_text = content.strip() if isinstance(content, str) else ""
                if not final_text:
                    _print_block("LLM", message)
                _print_block("FINAL", final_text or "(empty content)")
                _record_findings(provider, final_text)
                return final_text

            messages.append(_assistant_turn(message))
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
                    result: dict[str, object] = await tools.execute(name, arguments)
                except Exception as exc:
                    arguments = {"raw": raw_arguments}
                    result = {"error": f"{type(exc).__name__}: {exc}"}

                print("LLM:")
                print(f"Tool Call -> {name}")
                print(f"Arguments -> {json.dumps(arguments, ensure_ascii=False)}")
                print()
                _print_block("TOOL", result)
                tool_call_id = tool_call.get("id")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id if isinstance(tool_call_id, str) else "",
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

        _print_block("FINAL", f"Stopped after {MAX_ROUNDS} rounds.")
        return ""


async def _main() -> None:
    import sys

    user_id, pull_request_id = bound_ids_from_env()
    question = " ".join(sys.argv[1:]).strip() or "这个 PR 改了哪些文件？"
    await run_agent(question, user_id=user_id, pull_request_id=pull_request_id)


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
