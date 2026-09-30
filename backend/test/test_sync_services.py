import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.sql.dml import Delete  # pyright: ignore[reportMissingImports]

from app.models.pr_file import PRFile
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.models.user import User
from app.services.github_pr_files import sync_pull_request_files
from app.services.github_pull_requests import (
    parse_github_datetime,
    sync_pull_requests,
)
from app.services.github_repositories import sync_repositories
from helpers import scalars_result


def _repo_payload(repo_id: int, name: str, *, private: bool = False) -> dict:
    return {
        "id": repo_id,
        "name": name,
        "full_name": f"octo/{name}",
        "owner": {"login": "octo"},
        "private": private,
        "default_branch": "main",
    }


def _pr_payload(pr_id: int, number: int, title: str) -> dict:
    return {
        "id": pr_id,
        "number": number,
        "title": title,
        "state": "open",
        "user": {"login": "octo"},
        "html_url": f"https://github.com/octo/demo/pull/{number}",
        "base": {"ref": "main"},
        "head": {"ref": "feature"},
        "draft": False,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T03:04:05Z",
        "closed_at": None,
        "merged_at": None,
    }


def _file_payload(filename: str, *, status: str = "modified") -> dict:
    return {
        "filename": filename,
        "previous_filename": None,
        "status": status,
        "sha": "abc",
        "additions": 1,
        "deletions": 0,
        "changes": 1,
        "blob_url": "https://github.com/blob",
        "raw_url": "https://github.com/raw",
        "contents_url": "https://api.github.com/contents",
        "patch": "@@ -1 +1 @@\n-a\n+b\n",
    }


def test_parse_github_datetime_accepts_zulu_and_null():
    parsed = parse_github_datetime("2026-01-02T03:04:05Z")
    assert parsed == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert parse_github_datetime(None) is None


def test_sync_repositories_updates_inserts_and_deletes_absent_rows():
    user = User(id=7, github_id=70, github_login="octo")
    existing = Repository(
        id=1,
        user_id=7,
        github_repo_id=11,
        name="old-name",
        full_name="octo/old-name",
        owner_login="old",
        private=False,
        default_branch="dev",
    )
    listed = [existing]
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.side_effect = [
        _scalar(existing),
        _scalar(None),
        MagicMock(),
        scalars_result(listed),
    ]

    result = asyncio.run(
        sync_repositories(
            db,
            user,
            [
                _repo_payload(11, "renamed", private=True),
                _repo_payload(22, "fresh"),
            ],
        )
    )

    assert existing.name == "renamed"
    assert existing.full_name == "octo/renamed"
    assert existing.owner_login == "octo"
    assert existing.private is True
    assert existing.default_branch == "main"
    added = db.add.call_args.args[0]
    assert isinstance(added, Repository)
    assert added.github_repo_id == 22
    assert added.user_id == 7
    delete_stmt = db.execute.await_args_list[2].args[0]
    assert isinstance(delete_stmt, Delete)
    delete_sql = str(delete_stmt.compile(compile_kwargs={"render_postcompile": True}))
    assert "NOT IN" in delete_sql.upper()
    assert result == listed
    db.commit.assert_awaited()


def test_sync_repositories_empty_github_list_deletes_every_local_repo():
    user = User(id=7, github_id=70, github_login="octo")
    db = AsyncMock()
    db.execute.side_effect = [MagicMock(), scalars_result([])]

    result = asyncio.run(sync_repositories(db, user, []))

    delete_stmt = db.execute.await_args_list[0].args[0]
    delete_sql = str(delete_stmt.compile(compile_kwargs={"render_postcompile": True}))
    assert isinstance(delete_stmt, Delete)
    assert "NOT IN" not in delete_sql.upper()
    assert result == []


def test_sync_pull_requests_replace_missing_deletes_absent_prs():
    repository = Repository(
        id=4,
        user_id=7,
        github_repo_id=11,
        name="demo",
        full_name="octo/demo",
        owner_login="octo",
        private=False,
    )
    existing = PullRequest(
        id=8,
        repository_id=4,
        github_pr_id=50,
        number=1,
        title="Old",
        state="closed",
        html_url="https://github.com/octo/demo/pull/1",
        base_branch="main",
        head_branch="old",
        github_created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        github_updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    kept = [existing]
    db = AsyncMock()
    db.execute.side_effect = [
        _scalar(existing),
        MagicMock(),
        scalars_result(kept),
    ]

    result = asyncio.run(
        sync_pull_requests(
            db,
            repository,
            [_pr_payload(50, 3, "Renamed PR")],
            replace_missing=True,
        )
    )

    assert existing.title == "Renamed PR"
    assert existing.number == 3
    assert existing.state == "open"
    assert existing.author_login == "octo"
    assert existing.head_branch == "feature"
    delete_stmt = db.execute.await_args_list[1].args[0]
    assert isinstance(delete_stmt, Delete)
    assert "github_pr_id" in str(delete_stmt)
    assert result == kept


def test_webhook_style_pull_request_sync_does_not_delete_other_prs():
    repository = Repository(
        id=4,
        user_id=7,
        github_repo_id=11,
        name="demo",
        full_name="octo/demo",
        owner_login="octo",
        private=False,
    )
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.side_effect = [
        _scalar(None),
        scalars_result([]),
    ]

    asyncio.run(
        sync_pull_requests(
            db,
            repository,
            [_pr_payload(90, 9, "Webhook PR")],
            replace_missing=False,
        )
    )

    statements = [call.args[0] for call in db.execute.await_args_list]
    assert not any(isinstance(stmt, Delete) for stmt in statements)
    added = db.add.call_args.args[0]
    assert isinstance(added, PullRequest)
    assert added.github_pr_id == 90
    assert added.github_updated_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def test_empty_webhook_sync_returns_without_a_follow_up_select():
    repository = Repository(
        id=4,
        user_id=7,
        github_repo_id=11,
        name="demo",
        full_name="octo/demo",
        owner_login="octo",
        private=False,
    )
    db = AsyncMock()

    result = asyncio.run(
        sync_pull_requests(db, repository, [], replace_missing=False)
    )

    assert result == []
    db.execute.assert_not_awaited()
    db.commit.assert_awaited()


def test_sync_files_upserts_and_leaves_rows_github_no_longer_lists():
    pull_request = PullRequest(
        id=8,
        repository_id=4,
        github_pr_id=50,
        number=3,
        title="PR",
        state="open",
        html_url="https://github.com/octo/demo/pull/3",
        base_branch="main",
        head_branch="feature",
        github_created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        github_updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    existing = PRFile(
        id=3,
        pull_request_id=8,
        filename="keep.py",
        status="added",
        additions=0,
        deletions=0,
        changes=0,
    )
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.side_effect = [
        _scalar(existing),
        _scalar(None),
    ]

    synced = asyncio.run(
        sync_pull_request_files(
            db,
            pull_request,
            [
                _file_payload("keep.py", status="modified"),
                _file_payload("new.py", status="added"),
            ],
        )
    )

    assert existing.status == "modified"
    assert existing.additions == 1
    assert existing.patch.startswith("@@")
    added = db.add.call_args.args[0]
    assert isinstance(added, PRFile)
    assert added.filename == "new.py"
    assert [item.filename for item in synced] == ["keep.py", "new.py"]
    statements = [call.args[0] for call in db.execute.await_args_list]
    assert not any(isinstance(stmt, Delete) for stmt in statements)
    assert db.refresh.await_count == 2


def _scalar(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result
