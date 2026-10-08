import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import SimpleNamespace

import httpx  # pyright: ignore[reportMissingImports]
from app.core.database import AsyncSessionLocal
from app.services.diff_chunking import filter_reviewable_files
from app.services.github_pr_files import (
    fetch_github_file_text,
    get_pull_request_with_repository,
    list_PR_files,
)
from app.services.github_tokens import GitHubTokenSession, GitHubTokenUnavailable

# One file body sent back to the model. The review pack budget is much larger;
# this cap keeps a single tool result from filling the Day 2 transcript.
TOOL_TEXT_LIMIT = 8000


def parse_tool_arguments(raw_arguments: object) -> dict[str, object]:
    """Parse a tool call's arguments field.

    Args:
        raw_arguments: JSON string from Chat Completions, or a dict a provider already parsed.

    Returns:
        An arguments object.

    Raises:
        json.JSONDecodeError: The string is not JSON.
        TypeError: The value is not an object.
    """
    if isinstance(raw_arguments, str):
        parsed = json.loads(raw_arguments)
    else:
        parsed = raw_arguments
    if not isinstance(parsed, dict):
        raise TypeError("Tool arguments must be a JSON object.")
    return parsed


def _clip(text: str | None) -> dict[str, object]:
    """Shorten one text field before it is sent to the model.

    Args:
        text: Patch or source text, or None when GitHub has no body.

    Returns:
        The text, whether it was cut, and the original length when cut.
    """
    if text is None:
        return {"text": None, "truncated": False}
    if len(text) <= TOOL_TEXT_LIMIT:
        return {"text": text, "truncated": False}
    return {
        "text": text[:TOOL_TEXT_LIMIT],
        "truncated": True,
        "original_chars": len(text),
    }


@dataclass(frozen=True)
class FileSnapshot:
    """Plain copy of one synced file, safe to use after the session closes."""

    filename: str
    status: str
    additions: int
    deletions: int
    changes: int
    patch: str | None
    contents_url: str | None
    sha: str | None


def _file_summary(pr_file: FileSnapshot) -> dict[str, object]:
    """Describe one changed file without its patch or GitHub URLs.

    Args:
        pr_file: Copied file row.

    Returns:
        Path, status, and diff size. ``has_patch`` tells the model a diff exists.
    """
    return {
        "path": pr_file.filename,
        "status": pr_file.status,
        "additions": pr_file.additions,
        "deletions": pr_file.deletions,
        "changes": pr_file.changes,
        "has_patch": bool(pr_file.patch),
    }


TOOLS: list[dict[str, object]] = [
    {
        "type": "function",
        "function": {
            "name": "get_pull_request_info",
            "description": (
                "Get metadata for the pull request already selected for this run. "
                "Takes no arguments."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pull_request_files",
            "description": (
                "List changed files for the selected pull request. "
                "Returns path, status, and diff size only, not file contents. "
                "At most the first 100 synced files."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_reviewable_files",
            "description": (
                "List changed files that the existing review filter would inspect. "
                "Lockfiles, images, and generated paths are omitted. Takes no arguments."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_content",
            "description": (
                "Read one changed file from the selected pull request. "
                "Returns the stored patch. For a file that still exists, also returns "
                "head text. Call this only for a file you need to inspect."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path returned by get_pull_request_files.",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
]


class BoundReviewTools:
    """Tools scoped to one user and one local pull request.

    The model never receives ``user_id``, ``pull_request_id``, or a GitHub token.
    """

    def __init__(
        self,
        user_id: int,
        pull_request_id: int,
        http_client: httpx.AsyncClient,
    ) -> None:
        """Store the caller and the HTTP client used for GitHub file text.

        Args:
            user_id: Local user id. Only this user's pull request can be read.
            pull_request_id: Local pull request id from the app URL.
            http_client: Shared async client. The caller owns its timeout.

        Returns:
            None.
        """
        self.user_id = user_id
        self.pull_request_id = pull_request_id
        self.http_client = http_client
        self.github_tokens = GitHubTokenSession(user_id, http_client)
        self.tool_functions: dict[
            str,
            Callable[[dict[str, object]], Awaitable[dict[str, object]]],
        ] = {
            "get_pull_request_info": self.get_pull_request_info,
            "get_pull_request_files": self.get_pull_request_files,
            "list_reviewable_files": self.list_reviewable_files,
            "get_file_content": self.get_file_content,
        }

    async def execute(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        """Run the Python function registered under this tool name.

        Args:
            name: Tool name from the assistant message.
            arguments: Parsed function arguments.

        Returns:
            The tool payload, or an error object the model can read.
        """
        function = self.tool_functions.get(name)
        if function is None:
            return {"error": f"Unknown tool: {name}"}
        return await function(arguments)

    async def get_pull_request_info(self, arguments: dict[str, object]) -> dict[str, object]:
        """Load metadata for the bound pull request.

        Args:
            arguments: Unused. The pull request is already bound on this object.

        Returns:
            Number, title, state, author, branches, and repository full name.
            An error object when this user does not own the pull request.
        """
        async with AsyncSessionLocal() as db:
            pull_request, repository = await get_pull_request_with_repository(
                db,
                self.pull_request_id,
                self.user_id,
            )
            if pull_request is None or repository is None:
                await db.rollback()
                return {"error": "Pull request was not found for this user."}
            payload: dict[str, object] = {
                "number": pull_request.number,
                "title": pull_request.title,
                "state": pull_request.state,
                "author_login": pull_request.author_login,
                "base_branch": pull_request.base_branch,
                "head_branch": pull_request.head_branch,
                "repository": repository.full_name,
            }
            await db.rollback()
            return payload

    async def _owned_files(self) -> list[FileSnapshot] | dict[str, object]:
        """Load synced files after checking ownership.

        Values are copied before the session closes. Later reads do not touch
        the database connection.

        Returns:
            File snapshots, or an error object when the pull request is not visible.
        """
        async with AsyncSessionLocal() as db:
            pull_request, _repository = await get_pull_request_with_repository(
                db,
                self.pull_request_id,
                self.user_id,
            )
            if pull_request is None:
                await db.rollback()
                return {"error": "Pull request was not found for this user."}
            files = await list_PR_files(db, self.pull_request_id)
            snapshots = [
                FileSnapshot(
                    filename=pr_file.filename,
                    status=pr_file.status,
                    additions=pr_file.additions,
                    deletions=pr_file.deletions,
                    changes=pr_file.changes,
                    patch=pr_file.patch,
                    contents_url=pr_file.contents_url,
                    sha=pr_file.sha,
                )
                for pr_file in files
            ]
            await db.rollback()
            return snapshots

    async def get_pull_request_files(self, arguments: dict[str, object]) -> dict[str, object]:
        """List changed files without their patches or source text.

        Args:
            arguments: Unused. The pull request is already bound on this object.

        Returns:
            Up to the synced page of files. The existing sync stores at most 100.
        """
        files = await self._owned_files()
        if isinstance(files, dict):
            return files
        return {
            "file_count": len(files),
            "files": [_file_summary(pr_file) for pr_file in files],
        }

    async def list_reviewable_files(self, arguments: dict[str, object]) -> dict[str, object]:
        """List files the production review filter would keep.

        Args:
            arguments: Unused. The pull request is already bound on this object.

        Returns:
            Reviewable paths, plus the paths the filter drops.
        """
        files = await self._owned_files()
        if isinstance(files, dict):
            return files
        reviewable_paths = {
            pr_file.filename
            for pr_file in filter_reviewable_files(
                [SimpleNamespace(filename=pr_file.filename) for pr_file in files]
            )
        }
        reviewable = [pr_file for pr_file in files if pr_file.filename in reviewable_paths]
        return {
            "reviewable": [_file_summary(pr_file) for pr_file in reviewable],
            "ignored_paths": [
                pr_file.filename
                for pr_file in files
                if pr_file.filename not in reviewable_paths
            ],
        }

    async def get_file_content(self, arguments: dict[str, object]) -> dict[str, object]:
        """Read one changed file's patch and, when it still exists, its head text.

        Args:
            arguments: Must include ``path``, a filename from the changed-file list.

        Returns:
            Status, clipped patch, and clipped head text. Removed files do not
            fetch head text. An error object when the path is missing or not in this PR.
        """
        path = arguments.get("path")
        if not isinstance(path, str) or not path.strip():
            return {"error": "path must be a non-empty string."}
        path = path.strip()
        async with AsyncSessionLocal() as db:
            pull_request, repository = await get_pull_request_with_repository(
                db,
                self.pull_request_id,
                self.user_id,
            )
            if pull_request is None or repository is None:
                await db.rollback()
                return {"error": "Pull request was not found for this user."}
            files = await list_PR_files(db, self.pull_request_id)
            match = next((pr_file for pr_file in files if pr_file.filename == path), None)
            if match is None:
                await db.rollback()
                return {"error": f"No changed file named {path}."}
            status = match.status
            patch = match.patch
            contents_url = match.contents_url
            blob_sha = match.sha
            owner_login = repository.owner_login
            repo_name = repository.name
            await db.rollback()

        payload: dict[str, object] = {
            "path": path,
            "status": status,
            "patch": _clip(patch),
        }
        if status == "removed":
            payload["source_text"] = None
            payload["note"] = "Removed file. Head text was not fetched."
            return payload

        try:
            source_text = await self.github_tokens.run(
                lambda token,
                contents_url=contents_url,
                blob_sha=blob_sha,
                owner_login=owner_login,
                repo_name=repo_name: fetch_github_file_text(
                    self.http_client,
                    token,
                    contents_url,
                    owner_login=owner_login,
                    repo_name=repo_name,
                    blob_sha=blob_sha,
                )
            )
        except GitHubTokenUnavailable as exc:
            payload["source_text"] = None
            payload["note"] = str(exc)
            return payload

        payload["source_text"] = _clip(source_text)
        return payload
