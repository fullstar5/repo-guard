import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest  # pyright: ignore[reportMissingImports]
from billiard.exceptions import SoftTimeLimitExceeded  # pyright: ignore[reportMissingImports]

from app.models.review_finding import ReviewFinding
from app.models.review_job import ReviewJob, ReviewJobStatus
from app.services.review_jobs import (
    _apply_file_path_fallback,
    _dedup_findings,
    create_review_job,
    create_review_job_if_no_active,
    execute_review_job,
    execute_review_job_by_id,
    replace_review_findings,
)
from app.services.review_provider import ReviewFindingDraft, ReviewResult
from helpers import async_cm, scalar_result


def _file(file_id: int, filename: str, body: str = "print(1)\n"):
    return SimpleNamespace(
        id=file_id,
        filename=filename,
        status="modified",
        patch=None,
        contents_url=f"https://api.github.com/repos/octo/demo/contents/{filename}",
        sha="abc",
        body=body,
    )


def _job(**overrides) -> ReviewJob:
    values = {
        "id": 42,
        "pull_request_id": 10,
        "status": ReviewJobStatus.pending,
        "provider": "openrouter",
        "model_name": "openrouter/free",
        "total_files": 1,
        "total_chunks": 0,
    }
    values.update(overrides)
    return ReviewJob(**values)


def _provider(outcomes):
    class ScriptedProvider:
        last = None

        def __init__(self, http_client, model_name):
            self.model_name = model_name
            self.http_client = http_client
            self.calls: list[str] = []
            self._outcomes = list(outcomes)
            ScriptedProvider.last = self

        async def review_content(self, content: str) -> ReviewResult:
            self.calls.append(content)
            outcome = self._outcomes[0]
            if not isinstance(outcome, BaseException):
                self._outcomes.pop(0)
                return outcome
            raise outcome

    return ScriptedProvider


def _run_execute(
    files,
    outcomes,
    *,
    max_chars: int = 102400,
    token: str = "token",
    fetch_side_effect=None,
):
    review_job = _job(total_files=len(files))
    saved = _job(status=ReviewJobStatus.processing, total_files=len(files))
    read_db = AsyncMock()
    read_db.get = AsyncMock(return_value=SimpleNamespace(id=10, repository_id=3))
    repo_result = MagicMock()
    repo_result.scalar_one.return_value = SimpleNamespace(
        user=SimpleNamespace(id=7 if token else None, github_access_token=token),
        owner_login="octo",
        name="demo",
    )
    read_db.execute = AsyncMock(return_value=repo_result)
    write_db = AsyncMock()
    write_db.get = AsyncMock(return_value=saved)
    write_db.add = MagicMock()

    if fetch_side_effect is not None:
        fetch = AsyncMock(side_effect=fetch_side_effect)
    else:

        async def _fetch_by_url(_client, _token, contents_url, **_kwargs):
            for item in files:
                if item.filename in (contents_url or ""):
                    return item.body
            return "print(1)\n"

        fetch = AsyncMock(side_effect=_fetch_by_url)

    provider_cls = _provider(outcomes)

    async def _inner():
        with (
            patch(
                "app.services.review_jobs.get_pull_request_files",
                new=AsyncMock(return_value=files),
            ),
            patch(
                "app.services.review_jobs.fetch_github_file_text",
                new=fetch,
            ),
            patch(
                "app.services.github_tokens.get_valid_github_access_token",
                new=AsyncMock(return_value=token or "token"),
            ),
            patch(
                "app.services.review_jobs.OpenRouterReviewProvider",
                new=provider_cls,
            ),
            patch(
                "app.services.review_jobs.AsyncSessionLocal",
                return_value=async_cm(write_db),
            ),
            patch("app.services.review_jobs.settings.review_pack_max_chars", max_chars),
            patch("app.services.review_jobs.settings.review_context_lines", 0),
            patch(
                "app.services.review_jobs.asyncio.sleep",
                new=AsyncMock(),
            ),
        ):
            result = await execute_review_job(
                db=read_db,
                review_job=review_job,
                http_client=AsyncMock(),
            )
        return result, saved, write_db, provider_cls.last, read_db

    return asyncio.run(_inner())


def _finding(summary: str, *, file_path: str | None = "a.py", severity: str = "high"):
    return ReviewResult(
        summary=summary,
        findings=[
            ReviewFindingDraft(
                severity=severity,
                summary=summary,
                file_path=file_path,
                start_line=1,
                end_line=1,
                suggestion="fix it",
            )
        ],
    )


def test_small_pr_completes_as_one_pack_and_stores_findings():
    files = [_file(1, "a.py", "print(1)\n")]
    result, saved, write_db, provider, read_db = _run_execute(
        files,
        [_finding("one issue", file_path=None)],
    )

    assert result is saved
    assert saved.status == ReviewJobStatus.completed
    assert saved.total_chunks == 1
    assert saved.result_summary
    assert "one issue" in saved.result_summary
    assert saved.error_message is None
    assert read_db.commit.await_count >= 1
    stored = [call.args[0] for call in write_db.add.call_args_list]
    assert len(stored) == 1
    assert isinstance(stored[0], ReviewFinding)
    assert stored[0].file_path == "a.py"
    assert stored[0].pr_file_id == 1
    assert stored[0].summary == "one issue"
    assert provider.model_name == "openrouter/free"
    assert "a.py" in provider.calls[0]


def test_large_pr_records_pack_count_summaries_and_every_file():
    files = [
        _file(1, "a.py", "A" * 200),
        _file(2, "b.py", "B" * 200),
    ]
    result, saved, write_db, provider, _read_db = _run_execute(
        files,
        [_finding("from a", file_path="a.py"), _finding("from b", file_path="b.py")],
        max_chars=700,
    )

    assert saved.status == ReviewJobStatus.completed
    assert saved.total_chunks == 2
    assert "from a" in saved.result_summary
    assert "from b" in saved.result_summary
    assert len(provider.calls) == 2
    stored = [call.args[0] for call in write_db.add.call_args_list]
    assert {item.file_path for item in stored} == {"a.py", "b.py"}
    assert {item.summary for item in stored} == {"from a", "from b"}
    assert result.total_chunks == 2


def test_partial_pack_failure_completes_and_keeps_successful_findings():
    files = [
        _file(1, "a.py", "A" * 200),
        _file(2, "b.py", "B" * 200),
    ]
    _result, saved, write_db, _provider, _read_db = _run_execute(
        files,
        [_finding("kept", file_path="a.py"), ValueError("model down")],
        max_chars=700,
    )

    assert saved.status == ReviewJobStatus.completed
    assert saved.error_message
    assert "model down" in saved.error_message
    assert "kept" in saved.result_summary
    stored = [call.args[0] for call in write_db.add.call_args_list]
    assert [item.summary for item in stored] == ["kept"]


def test_all_packs_failing_marks_the_job_failed():
    files = [_file(1, "a.py", "print(1)\n")]
    failed = _job(status=ReviewJobStatus.failed)
    read_db = AsyncMock()
    read_db.get = AsyncMock(return_value=SimpleNamespace(id=10, repository_id=3))
    repo_result = MagicMock()
    repo_result.scalar_one.return_value = SimpleNamespace(
        user=SimpleNamespace(id=7, github_access_token="token"),
        owner_login="octo",
        name="demo",
    )
    read_db.execute = AsyncMock(return_value=repo_result)

    async def _inner():
        with (
            patch(
                "app.services.review_jobs.get_pull_request_files",
                new=AsyncMock(return_value=files),
            ),
            patch(
                "app.services.review_jobs.fetch_github_file_text",
                new=AsyncMock(return_value="print(1)\n"),
            ),
            patch(
                "app.services.github_tokens.get_valid_github_access_token",
                new=AsyncMock(return_value="token"),
            ),
            patch(
                "app.services.review_jobs.OpenRouterReviewProvider",
                new=_provider([ValueError("empty")]),
            ),
            patch(
                "app.services.review_jobs.mark_review_job_failed_by_id",
                new=AsyncMock(return_value=failed),
            ) as mark_failed,
            patch("app.services.review_jobs.asyncio.sleep", new=AsyncMock()),
        ):
            result = await execute_review_job(
                db=read_db,
                review_job=_job(),
                http_client=AsyncMock(),
            )
        return result, mark_failed

    result, mark_failed = asyncio.run(_inner())
    assert result is failed
    message = mark_failed.await_args.args[1]
    assert "All review packs failed" in message
    assert "empty" in message
    read_db.rollback.assert_awaited()


def test_soft_time_limit_during_execute_is_not_marked_failed():
    files = [_file(1, "a.py")]

    async def _inner():
        with (
            patch(
                "app.services.review_jobs.get_pull_request_files",
                new=AsyncMock(return_value=files),
            ),
            patch(
                "app.services.review_jobs.fetch_github_file_text",
                new=AsyncMock(return_value="print(1)\n"),
            ),
            patch(
                "app.services.github_tokens.get_valid_github_access_token",
                new=AsyncMock(return_value="token"),
            ),
            patch(
                "app.services.review_jobs.OpenRouterReviewProvider",
                new=_provider([SoftTimeLimitExceeded()]),
            ),
            patch(
                "app.services.review_jobs.mark_review_job_failed_by_id",
                new=AsyncMock(),
            ) as mark_failed,
        ):
            with pytest.raises(SoftTimeLimitExceeded):
                await execute_review_job(
                    db=_ready_db(),
                    review_job=_job(),
                    http_client=AsyncMock(),
                )
        return mark_failed

    mark_failed = asyncio.run(_inner())
    mark_failed.assert_not_awaited()


def test_fetch_failure_still_reviews_the_patch_and_records_the_note():
    pr_file = SimpleNamespace(
        id=1,
        filename="a.py",
        status="modified",
        patch="@@ -1 +1 @@\n-a\n+b\n",
        contents_url="https://api.github.com/repos/octo/demo/contents/a.py",
        sha="abc",
        body="",
    )
    _result, saved, _write_db, provider, _read_db = _run_execute(
        [pr_file],
        [_finding("from patch", file_path="a.py")],
        fetch_side_effect=RuntimeError("github 403"),
    )

    assert saved.status == ReviewJobStatus.completed
    assert "failed to fetch source" in (saved.error_message or "")
    assert "github 403" in saved.error_message
    assert "@@ -1 +1 @@" in provider.calls[0]


def test_missing_source_and_patch_is_still_sent_as_a_gap():
    pr_file = SimpleNamespace(
        id=1,
        filename="blob.bin",
        status="modified",
        patch=None,
        contents_url=None,
        sha=None,
        body="",
    )
    _result, saved, _write_db, provider, _read_db = _run_execute(
        [pr_file],
        [_finding("gap noted", file_path="blob.bin")],
        token=None,
    )

    assert saved.status == ReviewJobStatus.completed
    assert "review gap" in provider.calls[0]


def test_noise_only_pull_request_fails():
    lockfile = SimpleNamespace(
        id=1,
        filename="package-lock.json",
        status="modified",
        patch="@@\n+lock\n",
        contents_url=None,
        sha=None,
        body="",
    )
    failed = _job(status=ReviewJobStatus.failed)

    async def _inner():
        with (
            patch(
                "app.services.review_jobs.get_pull_request_files",
                new=AsyncMock(return_value=[lockfile]),
            ),
            patch(
                "app.services.review_jobs.mark_review_job_failed_by_id",
                new=AsyncMock(return_value=failed),
            ) as mark_failed,
        ):
            result = await execute_review_job(
                db=_ready_db(token=None),
                review_job=_job(),
                http_client=AsyncMock(),
            )
        return result, mark_failed

    result, mark_failed = asyncio.run(_inner())
    assert result is failed
    assert "No reviewable patch content" in mark_failed.await_args.args[1]


def test_unsupported_provider_is_marked_failed():
    failed = _job(status=ReviewJobStatus.failed)

    async def _inner():
        with patch(
            "app.services.review_jobs.mark_review_job_failed_by_id",
            new=AsyncMock(return_value=failed),
        ) as mark_failed, patch(
            "app.services.review_jobs.get_pull_request_files",
            new=AsyncMock(return_value=[]),
        ):
            result = await execute_review_job(
                db=_ready_db(token=None),
                review_job=_job(provider="other"),
                http_client=AsyncMock(),
            )
        return result, mark_failed

    result, mark_failed = asyncio.run(_inner())
    assert result is failed
    assert "Unsupported provider" in mark_failed.await_args.args[1]


def test_execute_by_id_skips_terminal_jobs_and_missing_rows():
    completed = _job(status=ReviewJobStatus.completed)
    db = AsyncMock()
    db.get = AsyncMock(side_effect=[completed, None])

    async def _inner():
        with (
            patch(
                "app.services.review_jobs.AsyncSessionLocal",
                return_value=async_cm(db),
            ),
            patch(
                "app.services.review_jobs.execute_review_job",
                new=AsyncMock(),
            ) as execute,
        ):
            first = await execute_review_job_by_id(42)
            second = await execute_review_job_by_id(99)
        return first, second, execute

    first, second, execute = asyncio.run(_inner())
    assert first is completed
    assert second is None
    execute.assert_not_awaited()


def test_create_review_job_starts_pending_with_zero_chunks():
    pull_request = SimpleNamespace(id=10)
    db = AsyncMock()
    db.add = MagicMock()

    async def _inner():
        with patch(
            "app.services.review_jobs.get_pull_request_files",
            new=AsyncMock(return_value=[object(), object()]),
        ):
            return await create_review_job(
                db,
                pull_request,
                "openrouter",
                "nvidia/nemotron-3-ultra-550b-a55b:free",
            )

    job = asyncio.run(_inner())
    assert job.status == ReviewJobStatus.pending
    assert job.total_files == 2
    assert job.total_chunks == 0
    assert job.model_name == "nvidia/nemotron-3-ultra-550b-a55b:free"
    db.commit.assert_awaited()


def test_create_review_job_if_no_active_raises_when_pr_disappears():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=scalar_result(None))

    with pytest.raises(ValueError, match="no longer exists"):
        asyncio.run(
            create_review_job_if_no_active(
                db,
                SimpleNamespace(id=10),
                "openrouter",
                "openrouter/free",
            )
        )


def test_file_path_fallback_and_dedup_keep_current_rules():
    blank = ReviewFindingDraft(
        severity="medium",
        summary="Bug  Here",
        file_path=None,
        suggestion="Do it",
    )
    filled = _apply_file_path_fallback([blank], "only.py")
    assert filled[0].file_path == "only.py"
    assert blank.file_path is None

    duplicate = ReviewFindingDraft(
        severity="low",
        summary="bug here",
        file_path="only.py",
        suggestion="  Do   it ",
    )
    other = ReviewFindingDraft(
        severity="high",
        summary="bug here",
        file_path="only.py",
        suggestion="do it",
    )
    distinct = ReviewFindingDraft(
        severity="high",
        summary="different",
        file_path="only.py",
    )
    deduped = _dedup_findings([filled[0], duplicate, other, distinct])
    assert [item.summary for item in deduped] == ["Bug  Here", "different"]


def test_replace_review_findings_dedups_before_insert():
    job = _job()
    db = AsyncMock()
    db.add = MagicMock()
    files = [_file(5, "a.py")]
    findings = [
        ReviewFindingDraft(severity="low", summary="Same", file_path="a.py"),
        ReviewFindingDraft(severity="critical", summary="same", file_path="a.py"),
        ReviewFindingDraft(severity="high", summary="Other", file_path="missing.py"),
    ]

    asyncio.run(replace_review_findings(db, job, files, findings))

    stored = [call.args[0] for call in db.add.call_args_list]
    assert [item.summary for item in stored] == ["Same", "Other"]
    assert stored[0].pr_file_id == 5
    assert stored[1].pr_file_id is None
    db.flush.assert_awaited()


def _ready_db(*, token: str | None = "token"):
    db = AsyncMock()
    db.get = AsyncMock(return_value=SimpleNamespace(id=10, repository_id=3))
    repo_result = MagicMock()
    repo_result.scalar_one.return_value = SimpleNamespace(
        user=SimpleNamespace(id=7 if token else None, github_access_token=token),
        owner_login="octo",
        name="demo",
    )
    db.execute = AsyncMock(return_value=repo_result)
    return db
