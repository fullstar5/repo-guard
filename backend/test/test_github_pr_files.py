import asyncio
import base64

import httpx  # pyright: ignore[reportMissingImports]

from app.services.github_pr_files import fetch_github_file_text


CONTENTS_URL = "https://api.github.com/repos/octo/demo/contents/app.py"
BLOB_URL = "https://api.github.com/repos/octo/demo/git/blobs/abc123"


def _run(handler):
    transport = httpx.MockTransport(handler)

    async def _inner() -> str | None:
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_github_file_text(
                client,
                "token",
                CONTENTS_URL,
                owner_login="octo",
                repo_name="demo",
                blob_sha="abc123",
            )

    return asyncio.run(_inner())


def test_fetch_github_file_text_raw_200():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == CONTENTS_URL
        return httpx.Response(200, text="print(1)\n")

    assert _run(handler) == "print(1)\n"


def test_fetch_github_file_text_contents_403_falls_back_to_blob():
    def handler(request: httpx.Request) -> httpx.Response:
        if "/contents/" in str(request.url):
            return httpx.Response(403, text="too large")
        assert str(request.url) == BLOB_URL
        return httpx.Response(200, text="print(2)\n")

    assert _run(handler) == "print(2)\n"


def test_fetch_github_file_text_contents_404_falls_back_to_blob():
    def handler(request: httpx.Request) -> httpx.Response:
        if "/contents/" in str(request.url):
            return httpx.Response(404, text="missing")
        return httpx.Response(200, text="print(3)\n")

    assert _run(handler) == "print(3)\n"


def test_fetch_github_file_text_decodes_base64_json_blob():
    encoded = base64.b64encode(b"print(4)\n").decode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"content": encoded, "encoding": "base64"},
        )

    assert _run(handler) == "print(4)\n"
