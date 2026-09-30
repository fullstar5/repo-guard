import httpx  # pyright: ignore[reportMissingImports]
from app.models.repository import Repository
from app.models.user import User
from sqlalchemy import delete, select  # pyright: ignore[reportMissingImports]
from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]
from sqlalchemy.orm import selectinload  # pyright: ignore[reportMissingImports]

_REPO_URL = "https://api.github.com/user/repos"


async def fetch_github_repositories(
    http_client: httpx.AsyncClient,
    access_token: str,
) -> list[dict]:
    """Load every repository visible to this GitHub token.

    Args:
        http_client: Shared async HTTP client.
        access_token: GitHub OAuth token for the current user.

    Returns:
        Repository objects from every page of ``GET /user/repos``.
        An empty list means the account currently has no repositories.

    Raises:
        httpx.HTTPStatusError: GitHub returned a non-2xx response.
        TypeError: A page body was not a JSON list.
    """
    repos: list[dict] = []
    next_url: str | None = _REPO_URL
    params: dict[str, str | int] | None = {
                "per_page": 100,
                "sort": "updated",
            }

    while next_url != None:
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
            raise TypeError("Github /user/repos returned a non-list body")
        repos.extend(page)
        next_link = response.links.get("next")
        next_url = next_link.get("url") if next_link else None
        params = None

    return repos


async def _delete_repos_absent_from_github(
    db: AsyncSession,
    user_id: int,
    seen_github_repo_ids: set[int],
) -> None:
    """Delete this user's local repos missing from the latest GitHub list.

    Child rows are removed by the database ``ON DELETE CASCADE`` constraints.
    An empty ``seen_github_repo_ids`` deletes every repo for the user.

    Args:
        db: Open async session. The caller commits.
        user_id: Local user whose repositories are being synced.
        seen_github_repo_ids: GitHub repository ids returned by the full fetch.

    Returns:
        None.
    """
    statement = delete(Repository).where(Repository.user_id == user_id)
    if seen_github_repo_ids:
        statement = statement.where(
            Repository.github_repo_id.not_in(seen_github_repo_ids)
        )
    await db.execute(statement)


async def sync_repositories(
    db: AsyncSession,
    user: User,
    github_repos: list[dict],
) -> list[Repository]:
    """Insert or update GitHub repos, then drop ones GitHub no longer lists.

    Args:
        db: Open async session.
        user: Owner of the local repository rows.
        github_repos: Complete ``GET /user/repos`` payload, including every page.

    Returns:
        The user's repositories after commit, newest ``updated_at`` first.
        This is the same set ``GET /repositories`` reads.
    """
    seen_github_repo_ids: set[int] = set()

    for repo_data in github_repos:
        seen_github_repo_ids.add(repo_data["id"])
        result = await db.execute(
            select(Repository).where(
                Repository.user_id == user.id,
                Repository.github_repo_id == repo_data["id"],
            )
        )
        repo = result.scalar_one_or_none()

        if repo is None:
            repo = Repository(
                user_id=user.id,
                github_repo_id=repo_data["id"],
                name=repo_data["name"],
                full_name=repo_data["full_name"],
                owner_login=repo_data["owner"]["login"],
                private=repo_data["private"],
                default_branch=repo_data.get("default_branch"),
            )
            db.add(repo)
        else:
            repo.name = repo_data["name"]
            repo.full_name = repo_data["full_name"]
            repo.owner_login = repo_data["owner"]["login"]
            repo.private = repo_data["private"]
            repo.default_branch = repo_data.get("default_branch")

    await _delete_repos_absent_from_github(
        db=db, user_id=user.id, seen_github_repo_ids=seen_github_repo_ids
    )
    await db.commit()

    return await list_repos_for_user(db=db, user_id=user.id)


async def list_repos_for_user(
    db: AsyncSession,
    user_id: int,
) -> list[Repository]:
    """Return repositories already stored for one user.

    Args:
        db: Open async session.
        user_id: Local user id.

    Returns:
        That user's repositories, newest ``updated_at`` first.
    """
    result = await db.execute(
        select(Repository)
        .where(Repository.user_id == user_id)
        .order_by(Repository.updated_at.desc())
    )

    return list(result.scalars().all())


async def list_repo_by_github_repo_id(
    db: AsyncSession,
    github_repo_id: int,
) -> list[Repository]:
    """Find every local repository row for one GitHub repository id.

    Args:
        db: Open async session.
        github_repo_id: GitHub's numeric repository id.

    Returns:
        Matching rows with ``user`` loaded. One GitHub repo can belong to
        more than one CodeGuard user.
    """
    result = await db.execute(
        select(Repository)
        .options(selectinload(Repository.user))
        .where(Repository.github_repo_id == github_repo_id)
    )

    return list(result.scalars().all())
