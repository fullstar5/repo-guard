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
        "docs",
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


HUNK_HEADER = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@"
)

# Leave headroom in each pack for the OpenRouter system prompt, JSON schema,
# and model reply. Characters are only an approximation of tokens.
PACK_CONTENT_BUDGET_RATIO = 0.9


@dataclass
class ReviewPack:
    pack_index: int
    filenames: list[str]
    content: str


def pack_content_budget(max_chars: int, reserved: int = 0) -> int:
    """Usable character budget after prompt and reply headroom.

    Args:
        max_chars: Configured pack size before the budget ratio.
        reserved: Characters already used by a fixed prefix, such as the intro.

    Returns:
        How many characters of window text may still go into the pack.
        At least 1.
    """
    return max(int(max_chars * PACK_CONTENT_BUDGET_RATIO) - reserved, 1)


def filter_reviewable_files(pr_files: list[PRFile]) -> list[PRFile]:
    """Drop lockfiles, generated files, images, and other paths the model should skip.

    Args:
        pr_files: Synced files for one pull request.

    Returns:
        Files whose paths are not on the ignore list. Order is preserved.
    """

    def is_ignored_review_path(filename: str | None) -> bool:
        """Return whether a path should be left out of review.

        Args:
            filename: GitHub path using forward slashes, or None.

        Returns:
            True for empty names, ignored filenames, ignored directories,
            and ignored suffixes.
        """
        if not filename or not filename.strip():
            return True

        path = PurePosixPath(filename.strip().replace("\\", "/"))
        parts_lower = [part.lower() for part in path.parts]
        name_lower = path.name.lower()
        if name_lower in IGNORED_FILENAMES:
            return True
        if any(part in IGNORED_DIR_NAMES for part in parts_lower):
            return True
        return bool(any(name_lower.endswith(suffix) for suffix in IGNORED_SUFFIXES))

    return [
        pr_file
        for pr_file in pr_files
        if not is_ignored_review_path(pr_file.filename)
    ]


def parse_new_file_hunk_ranges(patch: str | None) -> list[tuple[int, int]]:
    """Read inclusive 1-based line ranges in the new file from ``@@`` headers.

    Args:
        patch: GitHub unified diff, or None.

    Returns:
        ``(start, end)`` pairs. An empty list means there was no patch or no
        usable hunk header.
    """
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
    """Expand each hunk by context and merge ranges that overlap or touch.

    Args:
        ranges: Inclusive 1-based hunk ranges.
        context_lines: Lines added before and after each hunk.
        line_count: Number of lines in the new file. Ranges are clipped to it.

    Returns:
        Merged inclusive ranges, in file order.
    """
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
    """Render one source window with line numbers.

    Args:
        filename: Path shown to the model.
        lines: Full file split into lines, without trailing newlines.
        start: Inclusive 1-based first line.
        end: Inclusive 1-based last line.

    Returns:
        Prompt text for that window.
    """
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


def render_line_fragment(
    filename: str,
    line_no: int,
    text: str,
    *,
    part: int,
    parts: int,
) -> str:
    """Render one piece of a source line that does not fit in a pack.

    Args:
        filename: Path shown to the model.
        line_no: 1-based line number.
        text: The piece of that line included in this fragment.
        part: 1-based index of this piece.
        parts: How many pieces the line was split into.

    Returns:
        Prompt text for that piece.
    """
    suffix = f" (line split {part}/{parts})" if parts > 1 else ""
    return (
        f"File: {filename}\n"
        f"Lines: {line_no}-{line_no}{suffix}\n"
        "Review this change with the surrounding source.\n\n"
        f"{line_no:>6}|{text}\n"
    )


def split_oversized_line(
    filename: str,
    line_no: int,
    text: str,
    budget: int,
) -> list[str]:
    """Split one source line that does not fit the pack budget. Never drop it.

    Args:
        filename: Path shown to the model.
        line_no: 1-based line number.
        text: Full line text.
        budget: Maximum characters for one rendered fragment.

    Returns:
        One or more rendered fragments covering the whole line.
    """
    overhead = len(render_line_fragment(filename, line_no, "", part=1, parts=1))
    piece_budget = max(budget - overhead, 64)
    if not text:
        return [render_line_fragment(filename, line_no, "", part=1, parts=1)]

    slices = [
        text[index:index + piece_budget]
        for index in range(0, len(text), piece_budget)
    ]
    parts = len(slices)
    return [
        render_line_fragment(filename, line_no, piece, part=index + 1, parts=parts)
        for index, piece in enumerate(slices)
    ]


def build_file_windows(
    *,
    filename: str,
    status: str,
    patch: str | None,
    source_text: str | None,
    context_lines: int,
    max_chars: int,
) -> list[str]:
    """Turn one file's changes into review windows.

    Remainder goes to the next window. Nothing from this file is dropped.

    Args:
        filename: Path shown to the model.
        status: GitHub file status, such as ``modified`` or ``removed``.
        patch: Unified diff, or None.
        source_text: PR-head file text, or None when it could not be fetched.
        context_lines: Lines of source kept around each hunk.
        max_chars: Pack size used to compute the window budget.

    Returns:
        Rendered windows in file order.
    """
    budget = pack_content_budget(max_chars)

    if status == "removed" or not source_text:
        if not patch:
            return [
                (f"File: {filename}\n"
                "The file has no patch and the source could not be fetched. "
                "Note this as a review gap for this file.\n")
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
            last_fit = cursor - 1
            while piece_end <= end:
                candidate = render_window(filename, lines, cursor, piece_end)
                if len(candidate) > budget:
                    break
                last_fit = piece_end
                piece_end += 1
            if last_fit < cursor:
                line_text = lines[cursor - 1] if cursor <= len(lines) else ""
                rendered.extend(
                    split_oversized_line(filename, cursor, line_text, budget)
                )
                cursor += 1
                continue
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
    """Greedily pack windows into model requests. There is no call cap.

    A window that does not fit the current pack starts the next pack.
    Windows are never discarded.

    Args:
        windows: ``(filename, window_text)`` pairs in review order.
        max_chars: Pack size used to compute the content budget.

    Returns:
        Packs whose ``content`` is ready to send as one user message.
    """
    intro = (
        "Review the following pull request changes.\n"
        "Each finding MUST include file_path for the file it refers to.\n"
        "Return the most important issues you can find.\n\n"
    )
    budget = pack_content_budget(max_chars, reserved=len(intro))
    packs: list[ReviewPack] = []
    current_parts: list[str] = []
    current_names: list[str] = []
    current_len = 0

    def flush() -> None:
        """Append the current windows as one pack and clear the buffer.

        Returns:
            None.
        """
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
    """Split a GitHub patch into chunks, preferring hunk boundaries.

    Args:
        patch: Unified diff.
        max_chars: Maximum characters in one chunk. A longer hunk is split
        by line.

    Returns:
        Diff chunks in file order. Empty when ``patch`` is empty.
    """
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
