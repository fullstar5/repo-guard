import json

import httpx  # pyright: ignore[reportMissingImports]
from app.core.config import get_settings
from agent_experiments.agent_day1.tools import TOOLS, execute_tool, parse_tool_arguments

settings = get_settings()

MAX_ROUNDS = 5
SYSTEM_PROMPT = (
    "You are a CodeGuard review assistant. "
    "When you need facts about a pull request, use the tools you have been given. "
    "Do not invent pull request metadata. "
    "If the question does not need those facts, answer it directly."
)
TEST_MODEL_NAME = "nvidia/nemotron-3.5-lightning:free"


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
    """Send one Chat Completions request that includes tools.

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
        raise TypeError(f"OpenRouter returned no assistant message: {payload}")
    return message


def _assistant_turn(message: dict[str, object]) -> dict[str, object]:
    """Copy the assistant message that must be replayed before tool results.

    Args:
        message: Assistant message from OpenRouter.

    Returns:
        Role, content, and tool calls. Reasoning details are kept when present
        because OpenRouter expects them on the next request.
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


async def run_agent(user_text: str) -> str:
    """Run the tool loop until the model answers or the round limit is hit.

    Args:
        user_text: The question for this run.

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
    _print_block("USER", user_text)

    timeout = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for _round in range(MAX_ROUNDS):
            message = await _call_llm(client=client, messages=messages)
            tool_calls = message.get("tool_calls") or []
            if not isinstance(tool_calls, list) or not tool_calls:
                content = message.get("content")
                final_text = content.strip() if isinstance(content, str) else ""
                if not final_text:
                    _print_block("LLM", message)
                _print_block("FINAL", final_text or "(empty content)")
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
                    result: dict[str, object] = execute_tool(name, arguments)
                except (json.JSONDecodeError, TypeError) as exc:
                    arguments = {"raw": raw_arguments}
                    result = {"error": str(exc)}

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

    question = " ".join(sys.argv[1:]).strip() or "Review PR #42 in mark/codeguard."
    await run_agent(question)


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
