import json
import os

import httpx  # pyright: ignore[reportMissingImports]
from agent_experiments.agent_day2.tools import (
    TOOLS,
    BoundReviewTools,
    parse_tool_arguments,
)
from app.core.config import get_settings
from app.services.openrouter_provider import OpenRouterReviewProvider

settings = get_settings()

MAX_ROUNDS = 8
TEST_MODEL_NAME = "nvidia/nemotron-3.5-lightning:free"
SYSTEM_PROMPT = (
    "You are a CodeGuard review assistant. "
    "The pull request for this run is already selected. "
    "Do not ask the user for a repository name, pull request number, or token. "
    "Use the provided tools when you need information. Read only the files required to answer.\n"
    "If the user only wants to know which files changed, list those files. "
    "Do not read every file.\n"
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

TEST_USER_ID = 1
TEST_PR_ID = 31 


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
    tools: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Send one Chat Completions request that includes tools.

    Args:
        client: Async HTTP client. The caller owns its timeout.
        messages: Transcript so far, including tool results.
        tools: Tool schemas for this request. Day 2 uses its own list when omitted.

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
            "tools": TOOLS if tools is None else tools,
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
        raise TypeError(f"OpenRouter returned no assistant message: {payload}")
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

    user_id, pull_request_id = TEST_USER_ID, TEST_PR_ID
    question = " ".join(sys.argv[1:]).strip() or "Which files does this PR modify?"
    await run_agent(question, user_id=user_id, pull_request_id=pull_request_id)


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
