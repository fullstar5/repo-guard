import base64
import json

import httpx  # pyright: ignore[reportMissingImports]
from sqlalchemy import select  # pyright: ignore[reportMissingImports]
from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]

from app.models.pull_request import PullRequest
from app.models.pr_file import PRFile
from app.models.repository import Repository


# get PR files from github and sync to database

async def fetch_github_pull_request_files(
    http_client: httpx.AsyncClient,
    access_token: str,
    owner_login: str,
    repo_name: str,
    pull_number: int,
) -> list[dict]:
    """Load the changed files GitHub lists for one pull request.

    Args:
        http_client: Shared async HTTP client.
        access_token: Repository owner's GitHub token.
        owner_login: GitHub owner login.
        repo_name: Repository name, without the owner.
        pull_number: GitHub pull request number.

    Returns:
        File objects from the first page of the GitHub files API, at most 100.
    """
    response = await http_client.get(
        f"https://api.github.com/repos/{owner_login}/{repo_name}/pulls/{pull_number}/files",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "X-GitHub-Api-Version": "2026-03-10",
        },
        params={
            "per_page": 100,
        },
    )
    response.raise_for_status()
    return response.json()


async def sync_pull_request_files(
    db: AsyncSession,
    pull_request: PullRequest,
    github_files: list[dict],
) -> list[PRFile]:
    """Insert or update changed files for one pull request.

    Args:
        db: Open async session. This function commits.
        pull_request: Local pull request these files belong to.
        github_files: File objects from the GitHub files API.

    Returns:
        The file rows written by this call. Files GitHub no longer lists are
        left in place.
    """
    synced_items: list[PRFile] = []

    for file in github_files:
        result = await db.execute(
            select(PRFile).where(
                PRFile.pull_request_id == pull_request.id,
                PRFile.filename == file["filename"],
            )
        )
        pr_file = result.scalar_one_or_none()

        if pr_file is None:
            pr_file = PRFile(
                pull_request_id=pull_request.id,
                filename=file["filename"],
                previous_filename=file.get("previous_filename"),
                status=file["status"],
                sha=file.get("sha"),
                additions=file.get("additions", 0),
                deletions=file.get("deletions", 0),
                changes=file.get("changes", 0),
                blob_url=file.get("blob_url"),
                raw_url=file.get("raw_url"),
                contents_url=file.get("contents_url"),
                patch=file.get("patch"),
            )
            db.add(pr_file)
        else:
            pr_file.previous_filename = file.get("previous_filename")
            pr_file.status = file["status"]
            pr_file.sha = file.get("sha")
            pr_file.additions = file.get("additions", 0)
            pr_file.deletions = file.get("deletions", 0)
            pr_file.changes = file.get("changes", 0)
            pr_file.blob_url = file.get("blob_url")
            pr_file.raw_url = file.get("raw_url")
            pr_file.contents_url = file.get("contents_url")
            pr_file.patch = file.get("patch")

        synced_items.append(pr_file)

    await db.commit()

    for pr_file in synced_items:
        await db.refresh(pr_file)
    return synced_items


async def get_pull_request_with_repository(
    db: AsyncSession,
    pull_request_id: int,
    user_id: int
) -> tuple[PullRequest | None, Repository | None]:
    """Load a pull request and its repository when both belong to the user.

    Args:
        db: Open async session.
        pull_request_id: Local pull request id.
        user_id: Local user id.

    Returns:
        The pull request and repository, or ``(None, None)`` when the user
        does not own that pull request.
    """
    result = await db.execute(
        select(PullRequest, Repository).join(Repository, PullRequest.repository_id == Repository.id).where(
            PullRequest.id == pull_request_id,
            Repository.user_id == user_id,
        )
    )

    row = result.first()
    if row is None:
        return None, None

    pull_request, repository = row
    return pull_request, repository



async def list_PR_files(
    db: AsyncSession,
    pull_request_id: int,
) -> list[PRFile]:
    """List stored files for one pull request.

    Args:
        db: Open async session.
        pull_request_id: Local pull request id. The caller checks ownership.

    Returns:
        File rows ordered by filename.
    """
    result = await db.execute(
        select(PRFile)
        .where(PRFile.pull_request_id == pull_request_id)
        .order_by(PRFile.filename.asc())
    )
    return list(result.scalars().all())


async def get_PR_file_for_user(
    db: AsyncSession,
    pull_request_id: int,
    file_id: int,
    user_id: int,
) -> PRFile | None:
    """Load one file when it belongs to the user's pull request.

    Args:
        db: Open async session.
        pull_request_id: Local pull request id.
        file_id: Local file id.
        user_id: Local user id.

    Returns:
        The file row, or None when it is missing or owned by someone else.
    """
    result = await db.execute(
        select(PRFile)
        .join(PullRequest, PRFile.pull_request_id == PullRequest.id)
        .join(Repository, PullRequest.repository_id == Repository.id)
        .where(
            PRFile.id == file_id,
            PRFile.pull_request_id == pull_request_id,
            Repository.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


def _text_from_github_file_response(response: httpx.Response) -> str:
    """Decode a GitHub Contents or blob response into file text.

    Args:
        response: Successful GitHub response. May be raw text or JSON with
        base64 ``content``.

    Returns:
        Decoded text. Invalid JSON is returned as a UTF-8 replacement string.
    """
    content_type = (response.headers.get("content-type") or "").lower()
    raw = response.content or b""
    if not raw:
        return ""

    looks_json = "json" in content_type or raw.lstrip()[:1] in {b"{", b"["}
    if looks_json:
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            return raw.decode("utf-8", errors="replace")
        if isinstance(payload, dict):
            content = payload.get("content")
            if isinstance(content, str) and payload.get("encoding") == "base64":
                decoded = base64.b64decode(content)
                return decoded.decode("utf-8", errors="replace")
            if isinstance(content, str):
                return content
        return json.dumps(payload)

    return raw.decode("utf-8", errors="replace")


async def fetch_github_file_text(
    http_client: httpx.AsyncClient,
    access_token: str,
    contents_url: str | None,
    *,
    owner_login: str | None = None,
    repo_name: str | None = None,
    blob_sha: str | None = None,
) -> str | None:
    """Load the file text GitHub stored on the pull request head.

    Args:
        http_client: Shared async HTTP client.
        access_token: Repository owner's GitHub token.
        contents_url: Contents API URL stored on the file row.
        owner_login: Repository owner, used for the blob fallback.
        repo_name: Repository name, used for the blob fallback.
        blob_sha: Blob sha, used when Contents returns 403 or 404.

    Returns:
        File text, or None when neither URL can be read.
    """
    headers = {
        "Accept": "application/vnd.github.raw",
        "Authorization": f"Bearer {access_token}",
        "X-GitHub-Api-Version": "2026-03-10",
    }

    if contents_url:
        response = await http_client.get(contents_url, headers=headers)
        if response.status_code == 200:
            return _text_from_github_file_response(response)
        if response.status_code not in {403, 404}:
            response.raise_for_status()

    if owner_login and repo_name and blob_sha:
        response = await http_client.get(
            f"https://api.github.com/repos/{owner_login}/{repo_name}/git/blobs/{blob_sha}",
            headers=headers,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return _text_from_github_file_response(response)

    return None