import json
import re

import httpx  # pyright: ignore[reportMissingImports]
from app.core.config import get_settings
from app.services.review_provider import (
    ReviewFindingDraft,
    ReviewProvider,
    ReviewResult,
)

settings = get_settings()



SEVERITY_ALIASES = {
    "info": "low",
    "low": "low",
    "minor": "low",
    "medium": "medium",
    "moderate": "medium",
    "warning": "medium",
    "high": "high",
    "major": "high",
    "critical": "critical",
    "blocker": "critical",
}


def _extract_json_text(raw_text: str) -> str:
    """Take the JSON object or array out of a model reply.

    Args:
        raw_text: Model message, possibly wrapped in markdown fences or prose.

    Returns:
        The first JSON object or array substring.

    Raises:
        ValueError: No JSON value can be decoded.
    """
    text = raw_text.strip()
    fenced_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)

    if fenced_match:
        text = fenced_match.group(1).strip()

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            _, end_index = decoder.raw_decode(text[index:])
            return text[index:index+end_index]
        except json.JSONDecodeError:
            continue
    
    raise ValueError("Model did not return valid JSON content.")   # model returned content but not in valid format



def _coerce_int(value: object) -> int | None:
    """Turn a model field into an int.

    Args:
        value: A number, numeric string, null, or some other JSON value.

    Returns:
        The integer, or None for null, blanks, booleans, and non-numeric values.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    
    try: 
        return int(value)
    except (TypeError, ValueError):
        return None



def _normalize_severity(value: object) -> str:
    """Map a model severity label onto low, medium, high, or critical.

    Args:
        value: Severity from the model, such as ``warning`` or ``blocker``.

    Returns:
        A canonical severity. Unknown or missing values become ``medium``.
    """
    if value is None:
        return "medium"
    normalized = str(value).strip().lower()
    return SEVERITY_ALIASES.get(normalized, "medium")



class OpenRouterReviewProvider(ReviewProvider):
    """Call an online review model through OpenRouter."""

    def __init__(self, http_client: httpx.AsyncClient, model_name: str) -> None:
        """Store the client and model used for later review calls.

        Args:
            http_client: Async HTTP client. The caller owns its timeout.
            model_name: OpenRouter model id sent on each request.

        Returns:
            None.
        """
        self.http_client = http_client
        self.model_name = model_name

    async def review_content(self, content: str) -> ReviewResult:
        """Send one pack to OpenRouter and parse the JSON reply.

        Args:
            content: User message for this pack. Earlier packs are not included.

        Returns:
            Parsed summary and findings.

        Raises:
            ValueError: The model returned empty content or unusable JSON.
            httpx.HTTPStatusError: OpenRouter returned a non-2xx response.
        """
        # Keep the prompt small and focused so free models can respond reliably.
        response = await self.http_client.post(
            f"{settings.open_router_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.open_router_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": settings.app_public_url,
                "X-OpenRouter-Title": settings.app_name,
            },
            json={
                "model": self.model_name,
                "temperature": 0.2,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are an expert code reviewer. "
                            "Review the provided pull request diff carefully. "
                            "Focus on correctness, bugs, security risks, performance issues, "
                            "and maintainability concerns.\n\n"
                            "Return ONLY valid JSON with this exact shape:\n"
                            "{\n"
                            '  "summary": "short overall summary",\n'
                            '  "findings": [\n'
                            "    {\n"
                            '      "severity": "low|medium|high|critical",\n'
                            '      "summary": "short actionable issue summary",\n'
                            '      "file_path": "path/to/file.py or null",\n'
                            '      "start_line": 10,\n'
                            '      "end_line": 12,\n'
                            '      "suggestion": "optional concrete fix or null"\n'
                            "    }\n"
                            "  ]\n"
                            "}\n\n"
                            "Rules:\n"
                            "- Do not wrap the JSON in markdown fences.\n"
                            "- Only include real issues worth showing to a developer.\n"
                            "- If there are no meaningful issues, return an empty findings array.\n"
                            "- Each finding MUST include file_path matching a reviewed file.\n"
                            "- Do not invent file_path. Use null only when the path is truly unknown.\n"
                            "- Use null for unknown start_line, end_line, or suggestion.\n"
                            "- Keep findings concise and specific."
                        ),
                    },
                    {
                        "role": "user",
                        "content": content,
                    },
                ],
            },
        )
        response.raise_for_status()

        payload = response.json()
        message = payload["choices"][0]["message"]
        raw_content = message.get("content")

        if raw_content is None or (isinstance(raw_content, str) and not raw_content.strip()):
            raise ValueError(
                "Model returned empty content. "
                f"message_keys={list(message.keys())} "
                f"finish_reason={payload['choices'][0].get('finish_reason')}"
            )

        if not isinstance(raw_content, str):
            raw_content = json.dumps(raw_content, ensure_ascii=False)

        try:
            return self._parse_review_response(raw_content)
        except ValueError as exc:
            raise ValueError(f"{exc} Raw model output preview {raw_content}") from exc


    def _parse_review_response(self, raw_content: str) -> ReviewResult:
        """Parse a model message into a summary and findings.

        Args:
            raw_content: Raw assistant message.

        Returns:
            A ``ReviewResult``.

        Raises:
            ValueError: The JSON is not an object, has no summary, or
            ``findings`` is not a list.
        """
        json_text = _extract_json_text(raw_content)
        payload = json.loads(json_text)

        if not isinstance(payload, dict):
            raise TypeError("Model response must be a JSON object")
        
        summary = str(payload.get("summary", "")).strip()
        raw_findings = payload.get("findings", [])

        if not summary:
            raise ValueError("Model responses is missing summary")

        if not isinstance(raw_findings, list):
            raise TypeError("Model ressponse field 'findings' must be a list")

        findings = [self._parse_finding(item) for item in raw_findings]
        return ReviewResult(summary=summary, findings=findings)


    def _parse_finding(self, item: object) -> ReviewFindingDraft:
        """Parse one finding object from the model.

        Args:
            item: One element of the model's ``findings`` array.

        Returns:
            A draft finding with normalized severity and line numbers.

        Raises:
            ValueError: ``item`` is not an object or has no summary.
        """
        if not isinstance(item, dict):
            raise TypeError("Each finding must be a JSON object.")

        summary = str(item.get("summary", "")).strip()
        if not summary:
            raise ValueError("Each finding must include a summary.")

        file_path = item.get("file_path")
        file_path = str(file_path).strip() if file_path else None

        start_line = _coerce_int(item.get("start_line"))
        end_line = _coerce_int(item.get("end_line"))

        if start_line is not None and end_line is None:
            end_line = start_line
        if end_line is not None and start_line is None:
            start_line = end_line
        if start_line is not None and end_line is not None and end_line < start_line:
            start_line, end_line = end_line, start_line

        suggestion = item.get("suggestion")
        suggestion = str(suggestion).strip() if suggestion else None

        return ReviewFindingDraft(
            severity=_normalize_severity(item.get("severity")),
            summary=summary,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            suggestion=suggestion,
        )


