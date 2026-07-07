import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import Repository
from app.models.user import User




async def fetch_github_repositories(
    http_client: httpx.AsyncClient,
    access_token: str,
) -> list[dict]:
    response = await http_client.get(
        "https://api.github.com/user/repos",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "X-GitHub-Api-Version": "2026-03-10",
        },
        params={
            "per_page": 100,
            "sort": "updated",
        },
    )
    response.raise_for_status()
    return response.json()


async def sync_repositories(
    db: AsyncSession,
    user: User,
    github_repos: list[dict],
) -> list[Repository]:
    synced_items: list[Repository] = []

    for repo_data in github_repos:
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

        synced_items.append(repo)

    await db.commit()

    for repo in synced_items:
        await db.refresh(repo)

    return synced_items