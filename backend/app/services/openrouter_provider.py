import httpx  # pyright: ignore[reportMissingImports]
import re
import json

from app.core.config import get_settings
from app.services.review_provider import ReviewProvider, ReviewFindingDraft, ReviewResult

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
    """extract real json content from AI API response"""
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
    
    raise ValueError("Model did not return valid JSON content.")



def _coerce_int(value: object) -> int | None:
    """type converage, eg. "10" -> 10"""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    
    try: 
        return int(value)
    except (TypeError, ValueError):
        return None



def _normalize_severity(value: object) -> str:
    """Label mapping, eg. warning -> low"""
    if value is None:
        return "medium"
    normalized = str(value).strip().lower()
    return SEVERITY_ALIASES.get(normalized, "medium")



class OpenRouterReviewProvider(ReviewProvider):
    """Call an online review model through OpenRouter."""

    def __init__(self, http_client: httpx.AsyncClient, model_name: str) -> None:
        self.http_client = http_client
        self.model_name = model_name

    async def review_content(self, content: str) -> ReviewResult:
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
                            "- Use null for unknown file_path, start_line, end_line, or suggestion.\n"
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
        raw_content = payload["choices"][0]["message"]["content"]

        if not isinstance(raw_content, str):
            raw_content = json.dumps(raw_content, ensure_ascii=False)

        try:
            return self._parse_review_response(raw_content)
        except ValueError as exc:
            raise ValueError(f"{exc} Raw model output preview {raw_content}") from exc


    def _parse_review_response(self, raw_content: str) -> ReviewResult:
        json_text = _extract_json_text(raw_content)
        payload = json.loads(json_text)

        if not isinstance(payload, dict):
            raise ValueError("Model response must be a JSON object")
        
        summary = str(payload.get("summary", "")).strip()
        raw_findings = payload.get("findings", [])

        if not summary:
            raise ValueError("Model responses is missing summary")

        if not isinstance(raw_findings, list):
            raise ValueError("Model ressponse field 'findings' must be a list")

        findings = [self._parse_finding(item) for item in raw_findings]
        return ReviewResult(summary=summary, findings=findings)


    def _parse_finding(self, item: object) -> ReviewFindingDraft:
        if not isinstance(item, dict):
            raise ValueError("Each finding must be a JSON object.")

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


