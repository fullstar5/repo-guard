import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.models.pr_file import PRFile



# Paths GitHub never needs an LLM to read. Matched against POSIX paths
# from the GitHub files API (always forward slashes).
IGNORED_FILENAMES = frozenset(
    {
        "package-lock.json",
        "package-lock.json.md5",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lock",
        "bun.lockb",
        "poetry.lock",
        "cargo.lock",
        "composer.lock",
        "gemfile.lock",
        "pipfile.lock",
        "uv.lock",
        "go.sum",
        "readme.md",
        "README.md",
    }
)
IGNORED_DIR_NAMES = frozenset(
    {
        "__pycache__",
        "node_modules",
        ".git",
        ".next",
        "coverage",
        "vendor",
    }
)
IGNORED_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".pyd",
    ".so",
    ".dylib",
    ".dll",
    ".min.js",
    ".min.css",
    ".map",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".zip",
    ".gz",
    ".whl",
)




# Original combined/chunk types. Review jobs now use ReviewPack windows.
# @dataclass
# class DiffChunk:
#     file_id: int
#     filename: str
#     chunk_index: int
#     content: str




def filter_reviewable_files(pr_files: list[PRFile]) -> list[PRFile]:
    """filter out files that not suppose to be reviewed"""

    def is_ignored_review_path(filename: str | None) -> bool:
        """Return True when this path should not be sent to the review model."""
        if not filename or not filename.strip():
            return True

        path = PurePosixPath(filename.strip().replace("\\", "/"))
        parts_lower = [part.lower() for part in path.parts]
        name_lower = path.name.lower()
        if name_lower in IGNORED_FILENAMES:
            return True
        if any(part in IGNORED_DIR_NAMES for part in parts_lower):
            return True
        if any(name_lower.endswith(suffix) for suffix in IGNORED_SUFFIXES):
            return True

        return False

    return [
        pr_file
        for pr_file in pr_files
        if not is_ignored_review_path(pr_file.filename)
    ]




HUNK_HEADER = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@"
)


@dataclass
class ReviewPack:
    pack_index: int
    filenames: list[str]
    content: str


def parse_new_file_hunk_ranges(patch: str | None) -> list[tuple[int, int]]:
    """Inclusive 1-based line ranges in the new file, from @@ headers."""
    if not patch:
        return []
    ranges: list[tuple[int, int]] = []
    for line in patch.splitlines():
        match = HUNK_HEADER.match(line)
        if not match:
            continue
        new_start = int(match.group(3))
        new_count = int(match.group(4) or "1")
        if new_count == 0:
            if new_start <= 0:
                continue
            # Deletion-only hunk: show context around the new-file cursor.
            ranges.append((new_start, new_start))
            continue
        ranges.append((new_start, new_start + new_count - 1))
    return ranges


def merge_line_windows(
    ranges: list[tuple[int, int]],
    *,
    context_lines: int,
    line_count: int,
) -> list[tuple[int, int]]:
    """Expand each hunk by context and merge overlaps so one function stays together."""
    expanded: list[tuple[int, int]] = []
    for start, end in ranges:
        left = max(1, start - context_lines)
        right = min(line_count, end + context_lines)
        expanded.append((left, right))
    expanded.sort()

    merged: list[tuple[int, int]] = []
    for start, end in expanded:
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def render_window(filename: str, lines: list[str], start: int, end: int) -> str:
    """Slice inclusive 1-based lines and keep numbers in the prompt."""
    body = []
    for number in range(start, end + 1):
        text = lines[number - 1] if number <= len(lines) else ""
        body.append(f"{number:>6}|{text}")
    return (
        f"File: {filename}\n"
        f"Lines: {start}-{end}\n"
        "Review this change with the surrounding source.\n\n"
        + "\n".join(body)
        + "\n"
    )


def build_file_windows(
    *,
    filename: str,
    status: str,
    patch: str | None,
    source_text: str | None,
    context_lines: int,
    max_chars: int,
) -> list[str]:
    """
    Every reviewable change in this file becomes one or more windows.
    Remainder goes to the next window/pack. Nothing from this file is dropped.
    """
    intro_room = 256
    budget = max(max_chars - intro_room, 512)

    if status == "removed" or not source_text:
        if not patch:
            return [
                f"File: {filename}\n"
                "The file has no patch and the source could not be fetched. "
                "Note this as a review gap for this file.\n"
            ]
        hunks = split_patch_by_hunks(patch, budget)
        if not hunks:
            hunks = [patch]
        return [
            f"File: {filename}\nStatus: {status}\n\n{hunk}\n"
            for hunk in hunks
        ]

    lines = source_text.splitlines()
    ranges = parse_new_file_hunk_ranges(patch)
    if not ranges:
        ranges = [(1, max(len(lines), 1))]

    windows = merge_line_windows(
        ranges,
        context_lines=context_lines,
        line_count=max(len(lines), 1),
    )

    rendered: list[str] = []
    for start, end in windows:
        chunk = render_window(filename, lines, start, end)
        if len(chunk) <= budget:
            rendered.append(chunk)
            continue
        cursor = start
        while cursor <= end:
            piece_end = cursor
            last_fit = cursor
            while piece_end <= end:
                candidate = render_window(filename, lines, cursor, piece_end)
                if len(candidate) > budget:
                    break
                last_fit = piece_end
                piece_end += 1
            if last_fit < cursor:
                last_fit = cursor
            rendered.append(render_window(filename, lines, cursor, last_fit))
            if last_fit >= end:
                break
            cursor = last_fit + 1
    return rendered


def pack_review_windows(
    windows: list[tuple[str, str]],
    *,
    max_chars: int,
) -> list[ReviewPack]:
    """
    windows: (filename, window_text). Greedy packs with no call cap.
    A window that does not fit the current pack starts the next pack.
    Windows are never discarded.
    """
    intro = (
        "Review the following pull request changes.\n"
        "Return the most important issues you can find.\n\n"
    )
    budget = max(max_chars - len(intro), 1)
    packs: list[ReviewPack] = []
    current_parts: list[str] = []
    current_names: list[str] = []
    current_len = 0

    def flush() -> None:
        nonlocal current_parts, current_names, current_len
        if not current_parts:
            return
        packs.append(
            ReviewPack(
                pack_index=len(packs),
                filenames=list(dict.fromkeys(current_names)),
                content=intro + "\n".join(current_parts),
            )
        )
        current_parts = []
        current_names = []
        current_len = 0

    for filename, window in windows:
        extra = 0 if not current_parts else 1
        if current_parts and current_len + extra + len(window) > budget:
            flush()
        current_parts.append(window)
        current_names.append(filename)
        current_len += extra + len(window)

    flush()
    return packs


def split_patch_by_hunks(patch: str, max_chars: int = 4000) -> list[str]:
    """Split a GitHub patch into chunks, preferring hunk boundaries."""
    if not patch:
        return []

    hunk_splits = re.split(r'(?=\n@@\s)', patch)

    chunks: list[str] = []
    current_chunk: list[str] = []
    current_len = 0

    for hunk in hunk_splits:
        hunk_len = len(hunk)

        # If one hunk is too large, fall back to line-based splitting.
        if hunk_len > max_chars:
            if current_chunk:
                chunks.append("".join(current_chunk))
                current_chunk = []
                current_len = 0

            lines = hunk.splitlines(keepends=True)
            for line in lines:
                if current_len + len(line) > max_chars and current_chunk:
                    chunks.append("".join(current_chunk))
                    current_chunk = [line]
                    current_len = len(line)
                else:
                    current_chunk.append(line)
                    current_len += len(line)
        else:
            # Keep hunk boundaries when the current chunk still has capacity.
            if current_len + hunk_len > max_chars and current_chunk:
                chunks.append("".join(current_chunk))
                current_chunk = [hunk]
                current_len = hunk_len
            else:
                current_chunk.append(hunk)
                current_len += hunk_len

    if current_chunk:
        chunks.append("".join(current_chunk))

    return chunks


# Original chunk path: split each file patch by hunk, one request per piece.
# Replaced by build_file_windows + pack_review_windows so files are not skipped
# and hunks keep GitHub source context.
# def build_review_chunks(
#     pr_files: list[PRFile],
#     max_patch_chars: int = 4000,
# ) -> list[DiffChunk]:
#     chunks: list[DiffChunk] = []
#
#     for pr_file in filter_reviewable_files(pr_files=pr_files):
#         if not pr_file.patch:
#             continue
#
#         patch_chunks = split_patch_by_hunks(pr_file.patch, max_patch_chars)
#
#         for index, patch_chunk in enumerate(patch_chunks):
#             content = (
#                 f"File: {pr_file.filename}\n"
#                 f"Status: {pr_file.status}\n"
#                 f"Additions: {pr_file.additions}, Deletions: {pr_file.deletions}\n"
#                 f"\n{patch_chunk}"
#             )
#             chunks.append(
#                 DiffChunk(
#                     file_id=pr_file.id,
#                     filename=pr_file.filename,
#                     chunk_index=index,
#                     content=content,
#                 )
#             )
#     return chunks
#
#
# Original combined path: one request when the whole PR patch fits the limits.
# Too large for openrouter/free, and files without a GitHub patch were skipped.
# def build_combined_review_input(
#     pr_files: list[PRFile],
#     max_combined_chars: int = 24000,
#     max_combined_files: int = 30,
#     max_combined_changes: int = 1000,
# ) -> str | None:
#     """build one review payload for whole PR when PR is small to save API calls"""
#     sections: list[str] = []
#     total_chars = 0
#     file_count = 0
#     total_changes = 0
#
#     for pr_file in filter_reviewable_files(pr_files=pr_files):
#         if not pr_file.patch:
#             continue
#
#         file_changes = pr_file.changes or (pr_file.additions + pr_file.deletions)
#
#         section = (
#             f"File: {pr_file.filename}\n"
#             f"Status: {pr_file.status}\n"
#             f"Additions: {pr_file.additions}, Deletions: {pr_file.deletions}\n\n"
#             f"{pr_file.patch}\n"
#         )
#
#         if total_chars + len(section) > max_combined_chars:
#             return None
#
#         if file_count + 1 > max_combined_files:
#             return None
#
#         if total_changes + file_changes > max_combined_changes:
#             return None
#
#         sections.append(section)
#         total_chars += len(section)
#         file_count += 1
#         total_changes += file_changes
#
#     if not sections:
#         return None
#
#     return (
#         "Review the following pull request diff.\n"
#         "Return the most important issues you can find.\n\n"
#         + "\n\n".join(sections)
#     )
