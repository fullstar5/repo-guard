import asyncio
import json

import httpx  # pyright: ignore[reportMissingImports]
import pytest  # pyright: ignore[reportMissingImports]

from app.services.github_pr_files import (
    fetch_github_file_text,
    fetch_github_pull_request_files,
)
from app.services.github_pull_requests import fetch_github_pull_requests
from app.services.github_repositories import fetch_github_repositories


CONTENTS_URL = "https://api.github.com/repos/octo/demo/contents/app.py"
BLOB_URL = "https://api.github.com/repos/octo/demo/git/blobs/abc123"


def _fetch(handler, *, contents_url=CONTENTS_URL, blob_sha="abc123"):
    transport = httpx.MockTransport(handler)

    async def _inner():
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_github_file_text(
                client,
                "token",
                contents_url,
                owner_login="octo",
                repo_name="demo",
                blob_sha=blob_sha,
            )

    return asyncio.run(_inner())


def test_contents_500_is_raised_and_does_not_fall_back():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(httpx.HTTPStatusError):
        _fetch(handler)


def test_empty_body_returns_empty_string():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"")

    assert _fetch(handler) == ""


def test_utf8_json_content_is_returned_without_base64():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"content": "hello", "encoding": "utf-8"},
        )

    assert _fetch(handler) == "hello"


def test_invalid_json_body_is_decoded_as_text():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"{not-json",
            headers={"content-type": "application/json"},
        )

    assert _fetch(handler) == "{not-json"


def test_non_dict_json_is_dumped():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "a", "file"])

    assert json.loads(_fetch(handler)) == ["not", "a", "file"]


def test_blob_404_after_contents_403_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        if "/contents/" in str(request.url):
            return httpx.Response(403, text="too large")
        return httpx.Response(404, text="missing blob")

    assert _fetch(handler) is None


def test_missing_urls_return_none_without_a_request():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no GitHub call expected")

    assert _fetch(handler, contents_url=None, blob_sha=None) is None


def test_repository_fetch_follows_link_next_and_drops_params():
    seen: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), dict(request.url.params)))
        if "page=2" not in str(request.url):
            return httpx.Response(
                200,
                json=[{"id": 1}],
                headers={
                    "Link": '<https://api.github.com/user/repos?page=2>; rel="next"'
                },
            )
        return httpx.Response(200, json=[{"id": 2}])

    transport = httpx.MockTransport(handler)

    async def _inner():
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_github_repositories(client, "token")

    repos = asyncio.run(_inner())
    assert [item["id"] for item in repos] == [1, 2]
    assert seen[0][1]["per_page"] == "100"
    assert seen[1][0] == "https://api.github.com/user/repos?page=2"
    assert "per_page" not in seen[1][1]


def test_repository_fetch_rejects_a_non_list_page():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": "nope"})

    transport = httpx.MockTransport(handler)

    async def _inner():
        async with httpx.AsyncClient(transport=transport) as client:
            await fetch_github_repositories(client, "token")

    with pytest.raises(TypeError):
        asyncio.run(_inner())


def test_pull_request_fetch_follows_every_page():
    def handler(request: httpx.Request) -> httpx.Response:
        if "page=2" in str(request.url):
            return httpx.Response(200, json=[{"id": 20, "number": 2}])
        return httpx.Response(
            200,
            json=[{"id": 10, "number": 1}],
            headers={
                "Link": (
                    '<https://api.github.com/repos/octo/demo/pulls?page=2>; rel="next"'
                )
            },
        )

    transport = httpx.MockTransport(handler)

    async def _inner():
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_github_pull_requests(client, "token", "octo", "demo")

    pulls = asyncio.run(_inner())
    assert [item["number"] for item in pulls] == [1, 2]


def test_pull_request_files_fetch_stops_after_the_first_page():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            200,
            json=[{"filename": "a.py"}],
            headers={
                "Link": (
                    '<https://api.github.com/repos/octo/demo/pulls/7/files?page=2>; '
                    'rel="next"'
                )
            },
        )

    transport = httpx.MockTransport(handler)

    async def _inner():
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_github_pull_request_files(
                client, "token", "octo", "demo", 7
            )

    files = asyncio.run(_inner())
    assert files == [{"filename": "a.py"}]
    assert len(calls) == 1
    assert "per_page=100" in calls[0]
