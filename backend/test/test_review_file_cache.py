import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from agent_experiments.agent_day4.agent import Day4Tools
from agent_experiments.agent_day6.specialists import slice_read_files
from app.services.review_file_cache import ReviewFileCache, review_file_record


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_review_file_record_keeps_source_and_windows():
    record = review_file_record(
        filename="a.py",
        status="modified",
        patch="@@ -1 +1 @@\n-old\n+new\n",
        source_text="new\n",
        context_lines=0,
        max_chars=256000,
    )
    assert record["path"] == "a.py"
    assert record["source_text"]["text"] == "new\n"
    assert record["windows"]
    assert "File: a.py" in record["windows"][0]


def test_review_file_cache_get_and_put_use_job_key():
    http = AsyncMock()
    body = {"path": "a.py", "windows": ["File: a.py\n"]}
    http.post = AsyncMock(
        side_effect=[
            _Response({"result": "OK"}),
            _Response({"result": json.dumps(body)}),
            _Response({"result": None}),
        ]
    )
    cache = ReviewFileCache(http, 42)

    asyncio.run(cache.put("a.py", body))
    loaded = asyncio.run(cache.get("a.py"))
    missing = asyncio.run(cache.get("missing.py"))

    assert loaded == body
    assert missing is None
    put_command = http.post.await_args_list[0].kwargs["json"]
    get_command = http.post.await_args_list[1].kwargs["json"]
    assert put_command[0] == "SET"
    assert put_command[1] == "review-job:42:file:a.py"
    assert json.loads(put_command[2]) == body
    assert put_command[3] == "EX"
    assert get_command == ["GET", "review-job:42:file:a.py"]


def test_slice_sends_windows_instead_of_full_source():
    selected = slice_read_files(
        {
            "a.py": {
                "status": "modified",
                "source_text": {"text": "FULL SOURCE"},
                "windows": ["File: a.py\n1|new\n"],
            }
        },
        ["a.py"],
    )
    assert selected["files"] == [
        {
            "path": "a.py",
            "status": "modified",
            "windows": ["File: a.py\n1|new\n"],
        }
    ]


def test_read_path_windows_keep_the_tail_of_a_long_change():
    source = "\n".join(f"line-{index}" for index in range(2000))
    base = AsyncMock()
    base.get_file_content = AsyncMock(
        return_value={
            "path": "a.py",
            "status": "modified",
            "patch": None,
            "source_text": {"text": source, "truncated": False},
        }
    )
    tools = Day4Tools(base)

    result = asyncio.run(tools.read_path("a.py"))

    base.get_file_content.assert_awaited_once_with({"path": "a.py"})
    windows = result["windows"]
    assert isinstance(windows, list)
    combined = "\n".join(window for window in windows if isinstance(window, str))
    assert len(combined) > 8000
    assert "line-1999" in combined


def test_read_path_returns_redis_body_without_github():
    cache = SimpleNamespace(
        get=AsyncMock(
            return_value={
                "path": "a.py",
                "status": "modified",
                "windows": ["File: a.py\n"],
                "source_text": {"text": "new\n", "truncated": False},
            }
        ),
        put=AsyncMock(),
    )
    base = AsyncMock()
    tools = Day4Tools(base, file_cache=cache)

    result = asyncio.run(tools.read_path("a.py"))

    assert result["cached"] is True
    assert result["windows"] == ["File: a.py\n"]
    base.get_file_content.assert_not_called()
