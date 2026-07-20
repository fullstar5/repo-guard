from datetime import datetime

import httpx

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pull_request import PullRequest
from app.models.repository import Repository


# get PR from github and sync to database

def parse_github_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def fetch_github_pull_requests(
    http_client: httpx.AsyncClient,
    access_token: str,
    owner_login: str,
    repo_name: str,
) -> list[dict]:
    response =  await http_client.get(
        f"https://api.github.com/repos/{owner_login}/{repo_name}/pulls",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "X-GitHub-Api-Version": "2026-03-10",
        },
        params={
            "state": "all",
            "per_page": 100,
            "sort": "updated",
            "direction": "desc",
        },
    )
    response.raise_for_status()
    return response.json()


async def sync_pull_requests(
    db: AsyncSession,
    repository: Repository,
    github_pull_requests: list[dict],
) -> list[dict]:
    synced_items: list[PullRequest] = []

    for pr_data in github_pull_requests:
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

        synced_items.append(pull_request)

    await db.commit()

    for pull_request in synced_items:
        await db.refresh(pull_request)

    return synced_items