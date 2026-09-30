from datetime import datetime

import httpx  # pyright: ignore[reportMissingImports]
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from sqlalchemy import delete, select  # pyright: ignore[reportMissingImports]
from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]

# get PR from github and sync to database

def parse_github_datetime(value: str | None) -> datetime | None:
    """Parse a GitHub timestamp.

    Args:
        value: ISO-8601 string from GitHub, or None.

    Returns:
        A timezone-aware datetime, or None when ``value`` is None.
    """
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def fetch_github_pull_requests(
    http_client: httpx.AsyncClient,
    access_token: str,
    owner_login: str,
    repo_name: str,
) -> list[dict]:
    """Load every pull request GitHub lists for one repository.

    Args:
        http_client: Shared async HTTP client.
        access_token: Repository owner's GitHub token.
        owner_login: GitHub owner login.
        repo_name: Repository name, without the owner.

    Returns:
        Pull request objects from every page of ``GET /pulls`` with
        ``state=all``. An empty list means the repository has no pull requests.

    Raises:
        httpx.HTTPStatusError: GitHub returned a non-2xx response.
        TypeError: A page body was not a JSON list.
    """
    pulls: list[dict] = []
    next_url: str | None = (
        f"https://api.github.com/repos/{owner_login}/{repo_name}/pulls"
    )
    params: dict[str, str | int] | None = {
        "state": "all",
        "per_page": 100,
        "sort": "updated",
        "direction": "desc",
    }

    while next_url is not None:
        response = await http_client.get(
            next_url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": "2026-03-10",
            },
            params=params,
        )
        response.raise_for_status()
        page = response.json()
        if not isinstance(page, list):
            raise TypeError("Github /pulls returned a non-list body")
        pulls.extend(page)
        next_link = response.links.get("next")
        next_url = next_link.get("url") if next_link else None
        params = None

    return pulls


async def _delete_pull_requests_absent_from_github(
    db: AsyncSession,
    repository_id: int,
    seen_github_pr_ids: set[int],
) -> None:
    """Delete this repository's local pull requests missing from GitHub.

    Files, review jobs, and findings follow the ``ON DELETE CASCADE``
    constraints. An empty ``seen_github_pr_ids`` deletes every pull request
    on this repository. Call this only after a complete ``state=all`` fetch.

    Args:
        db: Open async session. The caller commits.
        repository_id: Local repository id.
        seen_github_pr_ids: GitHub pull request ids from the full fetch.

    Returns:
        None.
    """
    statement = delete(PullRequest).where(PullRequest.repository_id == repository_id)
    if seen_github_pr_ids:
        statement = statement.where(PullRequest.github_pr_id.not_in(seen_github_pr_ids))
    await db.execute(statement)


async def sync_pull_requests(
    db: AsyncSession,
    repository: Repository,
    github_pull_requests: list[dict],
    *,
    replace_missing: bool = False,
) -> list[PullRequest]:
    """Insert or update pull requests for one repository.

    Args:
        db: Open async session. This function commits.
        repository: Local repository these pull requests belong to.
        github_pull_requests: Pull request objects from GitHub.
        replace_missing: When True, ``github_pull_requests`` must be the
            complete ``state=all`` list. Local rows absent from it are deleted.
            Webhook sync passes one pull request and leaves this False.

    Returns:
        When ``replace_missing`` is True, every pull request still stored for
        the repository. Otherwise only the rows written by this call.
    """
    seen_github_pr_ids: set[int] = set()

    for pr_data in github_pull_requests:
        seen_github_pr_ids.add(pr_data["id"])
        result = await db.execute(
            select(PullRequest).where(
                PullRequest.repository_id == repository.id,
                PullRequest.github_pr_id == pr_data["id"],
            )
        )
        pull_request = result.scalar_one_or_none()

        if pull_request is None:
            pull_request = PullRequest(
                repository_id=repository.id,
                github_pr_id=pr_data["id"],
                number=pr_data["number"],
                title=pr_data["title"],
                state=pr_data["state"],
                author_login=pr_data["user"]["login"] if pr_data.get("user") else None,
                html_url=pr_data["html_url"],
                base_branch=pr_data["base"]["ref"],
                head_branch=pr_data["head"]["ref"],
                is_draft=pr_data.get("draft", False),
                github_created_at=parse_github_datetime(pr_data["created_at"]),
                github_updated_at=parse_github_datetime(pr_data["updated_at"]),
                github_closed_at=parse_github_datetime(pr_data.get("closed_at")),
                github_merged_at=parse_github_datetime(pr_data.get("merged_at")),
            )
            db.add(pull_request)
        else:
            pull_request.number = pr_data["number"]
            pull_request.title = pr_data["title"]
            pull_request.state = pr_data["state"]
            pull_request.author_login = pr_data["user"]["login"] if pr_data.get("user") else None
            pull_request.html_url = pr_data["html_url"]
            pull_request.base_branch = pr_data["base"]["ref"]
            pull_request.head_branch = pr_data["head"]["ref"]
            pull_request.is_draft = pr_data.get("draft", False)
            pull_request.github_created_at = parse_github_datetime(pr_data["created_at"])
            pull_request.github_updated_at = parse_github_datetime(pr_data["updated_at"])
            pull_request.github_closed_at = parse_github_datetime(pr_data.get("closed_at"))
            pull_request.github_merged_at = parse_github_datetime(pr_data.get("merged_at"))

    if replace_missing:
        await _delete_pull_requests_absent_from_github(
            db,
            repository.id,
            seen_github_pr_ids,
        )
    await db.commit()

    if replace_missing:
        return await list_PRs_for_repo(db, repository.id)
    if not seen_github_pr_ids:
        return []

    result = await db.execute(
        select(PullRequest).where(
            PullRequest.repository_id == repository.id,
            PullRequest.github_pr_id.in_(seen_github_pr_ids),
        )
    )
    return list(result.scalars().all())



async def get_repo_for_user(
    db: AsyncSession,
    repository_id: int,
    user_id: int,
) -> Repository | None:
    """Load one repository when it belongs to the user.

    Args:
        db: Open async session.
        repository_id: Local repository id.
        user_id: Local user id.

    Returns:
        The repository, or None when it is missing or owned by someone else.
    """
    result = await db.execute(
        select(Repository).where(
            Repository.id == repository_id,
            Repository.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()



async def list_PRs_for_repo(
    db: AsyncSession,
    repository_id: int,
) -> list[PullRequest]:
    """List stored pull requests for one repository.

    Args:
        db: Open async session.
        repository_id: Local repository id. The caller checks ownership.

    Returns:
        Pull requests, newest GitHub update first.
    """
    result = await db.execute(
        select(PullRequest)
        .where(PullRequest.repository_id == repository_id)
        .order_by(PullRequest.github_updated_at.desc())
    )
    return list(result.scalars().all())