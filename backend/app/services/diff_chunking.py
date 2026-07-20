import re
from dataclasses import dataclass

from app.models.pr_file import PRFile




@dataclass
class DiffChunk:
    file_id: int
    filename: str
    chunk_index: int
    content: str

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


def build_review_chunks(
    pr_files: list[PRFile],
    max_patch_chars: int = 4000,
) -> list[DiffChunk]:
    chunks: list[DiffChunk] = []

    for pr_file in pr_files:
        if not pr_file.patch:
            continue

        patch_chunks = split_patch_by_hunks(pr_file.patch, max_patch_chars)

        for index, patch_chunk in enumerate(patch_chunks):
            content = (
                f"File: {pr_file.filename}\n"
                f"Status: {pr_file.status}\n"
                f"Additions: {pr_file.additions}, Deletions: {pr_file.deletions}\n"
                f"\n{patch_chunk}"
            )
            chunks.append(
                DiffChunk(
                    file_id=pr_file.id,
                    filename=pr_file.filename,
                    chunk_index=index,
                    content=content,
                )
            )
    return chunks