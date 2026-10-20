import asyncio
import json
import time

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
_FIRST_TOKEN_SECONDS = 180
# TEST_MODEL_NAME = "nvidia/nemotron-3.5-lightning:free"
TEST_MODEL_NAME = "openrouter/free"
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


class _RetryableOpenRouterError(RuntimeError):
    """One completion attempt can be sent again."""


def _json_from_openrouter_body(text: str) -> dict[str, object]:
    """Parse a completion body that may start with keepalive lines.

    A free model can sit in a queue while OpenRouter holds the HTTP 200 open.
    The body then begins with blank lines and SSE comments such as
    ``: OPENROUTER PROCESSING``. ``response.json()`` stops at the colon, which
    surfaces as ``Expecting value: line 201 column 1``, even when the JSON
    object follows those lines.

    Args:
        text: Raw response text.

    Returns:
        The decoded JSON object.

    Raises:
        ValueError: The body contains no JSON object.
    """
    pieces: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(":"):
            continue
        if stripped.startswith("data:"):
            data = stripped[5:].strip()
            if not data or data == "[DONE]":
                continue
            pieces.append(data)
            continue
        pieces.append(stripped)
    blob = "\n".join(pieces).strip()
    if not blob:
        raise ValueError("OpenRouter response had no JSON body.")
    try:
        payload = json.loads(blob)
    except json.JSONDecodeError:
        start = blob.find("{")
        if start < 0:
            raise ValueError("OpenRouter response had no JSON object.") from None
        try:
            payload, _end = json.JSONDecoder().raw_decode(blob[start:])
        except json.JSONDecodeError as exc:
            raise ValueError("OpenRouter response was not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("OpenRouter response JSON was not an object.")
    return payload


def _retryable_provider_error(error: object) -> bool:
    """Return whether an OpenRouter error object is worth another attempt.

    Args:
        error: The ``error`` field from a response or a choice.

    Returns:
        True for rate limits, timeouts, and provider outages.
    """
    if not isinstance(error, dict):
        return False
    code = error.get("code")
    if code in {429, 500, 502, 503, 504} or str(code) in {"429", "500", "502", "503", "504"}:
        return True
    metadata = error.get("metadata")
    if not isinstance(metadata, dict):
        return False
    kind = metadata.get("error_type")
    return kind in {
        "timeout",
        "server",
        "provider_overloaded",
        "provider_unavailable",
        "rate_limit_exceeded",
    }


def _completion_message(payload: dict[str, object]) -> dict[str, object]:
    """Read the assistant message, or explain why this body cannot be used.

    Args:
        payload: Decoded Chat Completions object.

    Returns:
        The assistant message from the first choice.

    Raises:
        _RetryableOpenRouterError: The provider failed in a way that a second
            request may succeed.
        RuntimeError: The body is a permanent failure or has no message.
    """
    error = payload.get("error")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        if _retryable_provider_error(error):
            raise _RetryableOpenRouterError(f"OpenRouter error: {error}")
        if error is not None:
            raise RuntimeError(f"OpenRouter returned an error: {error}")
        raise _RetryableOpenRouterError("OpenRouter returned no choices.")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise RuntimeError(f"OpenRouter returned no assistant message: {payload}")
    if choice.get("finish_reason") == "error" and _retryable_provider_error(choice.get("error")):
        raise _RetryableOpenRouterError(f"OpenRouter choice error: {choice.get('error')}")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise RuntimeError(f"OpenRouter returned no assistant message: {payload}")
    return message


class _StreamState:
    """Assistant message assembled from Chat Completions stream chunks."""

    def __init__(self) -> None:
        """Start with no text and no tool calls.

        Returns:
            None.
        """
        self.content: list[str] = []
        self.tool_calls: dict[int, dict[str, object]] = {}
        self.reasoning_details: list[object] = []
        self.error: object = None

    def add_tool_delta(self, call: dict[str, object]) -> None:
        """Merge one streamed tool-call fragment into the call at its index.

        Args:
            call: One item from ``delta.tool_calls``.

        Returns:
            None.
        """
        index = call.get("index")
        slot = index if isinstance(index, int) else 0
        current = self.tool_calls.get(slot)
        if current is None:
            current = {
                "id": "",
                "type": "function",
                "function": {"name": "", "arguments": ""},
            }
            self.tool_calls[slot] = current
        call_id = call.get("id")
        if isinstance(call_id, str) and call_id:
            current["id"] = call_id
        call_type = call.get("type")
        if isinstance(call_type, str) and call_type:
            current["type"] = call_type
        function = call.get("function")
        if not isinstance(function, dict):
            return
        stored = current["function"]
        if not isinstance(stored, dict):
            return
        name = function.get("name")
        arguments = function.get("arguments")
        if isinstance(name, str):
            stored["name"] = str(stored.get("name") or "") + name
        if isinstance(arguments, str):
            stored["arguments"] = str(stored.get("arguments") or "") + arguments

    def message(self) -> dict[str, object]:
        """Return the assistant message in the non-streaming shape.

        Returns:
            Role, content, tool calls, and reasoning details when any arrived.

        Raises:
            _RetryableOpenRouterError: The provider failed and can be retried.
            RuntimeError: The provider failed permanently or sent no message.
        """
        if self.error is not None and not self.content and not self.tool_calls:
            if _retryable_provider_error(self.error):
                raise _RetryableOpenRouterError(f"OpenRouter error: {self.error}")
            raise RuntimeError(f"OpenRouter returned an error: {self.error}")
        if not self.content and not self.tool_calls:
            raise _RetryableOpenRouterError("OpenRouter closed the stream without a completion.")
        message: dict[str, object] = {
            "role": "assistant",
            "content": "".join(self.content) if self.content else None,
            "tool_calls": [self.tool_calls[index] for index in sorted(self.tool_calls)],
        }
        if self.reasoning_details:
            message["reasoning_details"] = self.reasoning_details
        return message


def _consume_sse_line(state: _StreamState, line: str) -> str:
    """Apply one Server-Sent Event line to the stream state.

    Blank lines and ``: OPENROUTER PROCESSING`` comments are ignored.

    Args:
        state: Accumulator for this response.
        line: One line from the event stream, without the trailing newline.

    Returns:
        ``done`` when the stream sends ``[DONE]``, otherwise ``ignore`` or ``data``.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith(":"):
        return "ignore"
    data = stripped[5:].strip() if stripped.startswith("data:") else stripped
    if not data:
        return "ignore"
    if data == "[DONE]":
        return "done"
    try:
        chunk = json.loads(data)
    except json.JSONDecodeError:
        return "ignore"
    if not isinstance(chunk, dict):
        return "ignore"
    if chunk.get("error") is not None:
        state.error = chunk.get("error")
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return "data"
    choice = choices[0]
    if choice.get("error") is not None:
        state.error = choice.get("error")
    message = choice.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content:
            state.content.append(content)
        calls = message.get("tool_calls")
        if isinstance(calls, list):
            for index, call in enumerate(calls):
                if isinstance(call, dict):
                    state.add_tool_delta({"index": index, **call})
        details = message.get("reasoning_details")
        if isinstance(details, list):
            state.reasoning_details.extend(details)
        return "data"
    delta = choice.get("delta")
    if not isinstance(delta, dict):
        return "data"
    content = delta.get("content")
    if isinstance(content, str) and content:
        state.content.append(content)
    calls = delta.get("tool_calls")
    if isinstance(calls, list):
        for call in calls:
            if isinstance(call, dict):
                state.add_tool_delta(call)
    details = delta.get("reasoning_details")
    if isinstance(details, list):
        state.reasoning_details.extend(details)
    return "data"


async def _message_from_event_stream(response: httpx.Response) -> dict[str, object]:
    """Read an OpenRouter event stream into one assistant message.

    Args:
        response: Streaming response whose status was already checked.

    Returns:
        The assembled assistant message.

    Raises:
        _RetryableOpenRouterError: Only keepalive comments arrived, or the
            provider asked to be retried.
        RuntimeError: The stream reported a permanent provider error.
    """
    state = _StreamState()
    started = time.monotonic()
    async for line in response.aiter_lines():
        kind = _consume_sse_line(state, line)
        if kind == "done":
            break
        if state.content or state.tool_calls:
            continue
        if time.monotonic() - started > _FIRST_TOKEN_SECONDS:
            raise _RetryableOpenRouterError(
                f"OpenRouter sent no completion within {_FIRST_TOKEN_SECONDS} seconds."
            )
    return state.message()


async def _buffered_completion(response: httpx.Response) -> dict[str, object]:
    """Read a non-streaming body, skipping a whitespace keepalive prefix.

    Args:
        response: Response whose ``Content-Type`` is not an event stream.

    Returns:
        The assistant message.

    Raises:
        _RetryableOpenRouterError: The body never contained JSON.
        RuntimeError: The JSON body was a permanent provider error.
    """
    started = time.monotonic()
    chunks: list[bytes] = []
    saw_json = False
    async for chunk in response.aiter_bytes():
        chunks.append(chunk)
        if b"{" in chunk:
            saw_json = True
        if saw_json:
            continue
        if time.monotonic() - started > _FIRST_TOKEN_SECONDS:
            raise _RetryableOpenRouterError(
                "OpenRouter sent only keepalive whitespace and no JSON."
            )
    text = b"".join(chunks).decode("utf-8", errors="replace")
    try:
        payload = _json_from_openrouter_body(text)
    except ValueError as exc:
        preview = " ".join(text.split())[:180]
        raise _RetryableOpenRouterError(
            f"{exc} status={response.status_code} preview={preview!r}"
        ) from exc
    return _completion_message(payload)


async def _call_llm_once(
    client: httpx.AsyncClient,
    messages: list[dict[str, object]],
    tools: list[dict[str, object]] | None,
    enable_tools: bool = True,
    model_name: str | None = None,
) -> dict[str, object]:
    """Send one Chat Completions request and parse the assistant message.

    The request is streamed. OpenRouter keeps a queued free model alive with
    SSE comments or whitespace; those bytes are not JSON and are skipped.
    Specialist calls set ``enable_tools`` false so that request has no tools.

    Args:
        client: Async HTTP client. The caller owns its timeout.
        messages: Transcript so far, including tool results.
        tools: Tool schemas for this request. Day 2 uses its own list when omitted.
        enable_tools: When false, the payload omits tools and tool_choice.

    Returns:
        The assistant message object from the first choice.

    Raises:
        _RetryableOpenRouterError: The response was missing, non-JSON, or a
            transient provider error.
        RuntimeError: OpenRouter rejected the request permanently.
        httpx.HTTPError: The connection failed before a body arrived.
    """
    payload: dict[str, object] = {
        "model": model_name,
        "temperature": 0,
        "stream": True,
        "messages": messages,
    }
    if enable_tools:
        payload["tools"] = TOOLS if tools is None else tools
        payload["tool_choice"] = "auto"
    try:
        async with client.stream(
            "POST",
            f"{settings.open_router_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.open_router_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": settings.app_public_url,
                "X-OpenRouter-Title": settings.app_name,
            },
            json=payload,
        ) as response:
            if response.status_code in {429, 500, 502, 503, 504}:
                body = (await response.aread()).decode("utf-8", errors="replace")
                preview = " ".join(body.split())[:180]
                raise _RetryableOpenRouterError(
                    f"OpenRouter HTTP {response.status_code}: {preview}"
                )
            if response.is_error:
                body = (await response.aread()).decode("utf-8", errors="replace")
                preview = " ".join(body.split())[:180]
                raise RuntimeError(f"OpenRouter HTTP {response.status_code}: {preview}")
            content_type = response.headers.get("content-type", "")
            if "text/event-stream" in content_type:
                return await _message_from_event_stream(response)
            return await _buffered_completion(response)
    except (TimeoutError, httpx.TimeoutException, httpx.TransportError) as exc:
        detail = str(exc).strip() or type(exc).__name__
        raise _RetryableOpenRouterError(f"OpenRouter request failed: {detail}") from exc


async def _call_llm(
    client: httpx.AsyncClient,
    messages: list[dict[str, object]],
    tools: list[dict[str, object]] | None = None,
    enable_tools: bool = True,
    model_name: str | None = None,
) -> dict[str, object]:
    """Send one Chat Completions request that includes tools.

    A queued free model sometimes returns only keepalive text. Those attempts
    are sent again. A 4xx rejection other than 429 is not sent again.

    Args:
        client: Async HTTP client. The caller owns its timeout.
        messages: Transcript so far, including tool results.
        tools: Tool schemas for this request. Day 2 uses its own list when omitted.
        enable_tools: When false, the specialist request cannot call tools.

    Returns:
        The assistant message object from the first choice.

    Raises:
        RuntimeError: Every attempt failed, or OpenRouter rejected the request.
    """
    last_reason = "no attempt"
    for attempt in range(1, 4):
        try:
            return await _call_llm_once(
                client, messages, tools, enable_tools, model_name
            )
        except _RetryableOpenRouterError as exc:
            last_reason = str(exc)
            print(f"OpenRouter attempt {attempt} did not return a completion: {exc}")
            print()
            if attempt < 3:
                await asyncio.sleep(attempt)
    raise RuntimeError(f"OpenRouter failed after 3 attempts: {last_reason}")


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
