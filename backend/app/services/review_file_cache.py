import json

import httpx  # pyright: ignore[reportMissingImports]
from app.core.config import get_settings
from app.services.diff_chunking import build_file_windows

settings = get_settings()

# A retried job should still find the bodies from the first attempt.
# The Celery soft limit is one hour and the task retries once.
REVIEW_FILE_CACHE_TTL_SECONDS = 6 * 60 * 60


def review_file_record(
    *,
    filename: str,
    status: str,
    patch: str | None,
    source_text: str | None,
    context_lines: int,
    max_chars: int,
    note: str | None = None,
) -> dict[str, object]:
    """Build the cached body for one file from the existing window chunker.

    Args:
        filename: Repository path.
        status: GitHub status, or ``context`` for a file outside the diff.
        patch: Unified diff, or None.
        source_text: Full head text, or None when it was not fetched.
        context_lines: Source lines kept around each hunk.
        max_chars: Pack size used to size each window.
        note: Optional note stored with the body.

    Returns:
        Path, status, full patch, full source, and the rendered windows.
        Windows are what a specialist reads. Source stays available for import parsing.
    """
    windows = build_file_windows(
        filename=filename,
        status=status,
        patch=patch,
        source_text=source_text,
        context_lines=context_lines,
        max_chars=max_chars,
    )
    record: dict[str, object] = {
        "path": filename,
        "status": status,
        "patch": None if patch is None else {"text": patch, "truncated": False},
        "source_text": (
            None if source_text is None else {"text": source_text, "truncated": False}
        ),
        "windows": windows,
    }
    if note:
        record["note"] = note
    return record


class ReviewFileCache:
    """File bodies for one review job, stored in Upstash Redis.

    The key is ``review-job:{job_id}:file:{path}``. A new job id does not see
    another job's files.
    """

    def __init__(self, http_client: httpx.AsyncClient, job_id: int) -> None:
        """Store the client and the job that owns these keys.

        Args:
            http_client: Shared async client. The caller owns its timeout.
            job_id: Local review job id.

        Returns:
            None.
        """
        self.http_client = http_client
        self.job_id = job_id

    def _key(self, path: str) -> str:
        """Return the Redis key for one path in this job.

        Args:
            path: Repository path.

        Returns:
            The key string.
        """
        return f"review-job:{self.job_id}:file:{path}"

    async def get(self, path: str) -> dict[str, object] | None:
        """Load one cached file body.

        Args:
            path: Repository path.

        Returns:
            The stored record, or None when this job has not cached that path.

        Raises:
            RuntimeError: Upstash did not return a usable value.
        """
        result = await self._command(["GET", self._key(path)])
        if result is None:
            return None
        if not isinstance(result, str):
            raise RuntimeError(f"Review file cache returned {type(result).__name__}")
        try:
            payload = json.loads(result)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Review file cache for {path} is not JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"Review file cache for {path} is not an object")
        return payload

    async def put(self, path: str, body: dict[str, object]) -> None:
        """Store one file body until the job cache expires.

        Args:
            path: Repository path.
            body: Record from ``review_file_record``.

        Returns:
            None.

        Raises:
            RuntimeError: Upstash did not accept the write.
        """
        await self._command(
            [
                "SET",
                self._key(path),
                json.dumps(body, ensure_ascii=False),
                "EX",
                str(REVIEW_FILE_CACHE_TTL_SECONDS),
            ]
        )

    async def _command(self, command: list[str]) -> object:
        """Send one Upstash REST command.

        Args:
            command: Redis command and arguments.

        Returns:
            The Upstash ``result`` field.

        Raises:
            RuntimeError: The request failed or Upstash reported an error.
        """
        try:
            response = await self.http_client.post(
                settings.upstash_redis_rest_url.rstrip("/"),
                headers={
                    "Authorization": f"Bearer {settings.upstash_redis_rest_token}",
                },
                json=command,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise RuntimeError("Review file cache request failed") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Review file cache returned an unexpected payload")
        if payload.get("error"):
            raise RuntimeError(f"Review file cache error: {payload['error']}")
        return payload.get("result")
