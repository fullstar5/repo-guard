from types import SimpleNamespace

from app.services.diff_chunking import (
    build_file_windows,
    filter_reviewable_files,
    merge_line_windows,
    pack_content_budget,
    pack_review_windows,
    parse_new_file_hunk_ranges,
    split_patch_by_hunks,
)


def test_pack_budget_reserves_headroom_and_never_drops_to_zero():
    # Current ratio is 0.9. Docs still mention 0.6; lock the implemented ratio.
    assert pack_content_budget(1000) == 900
    assert pack_content_budget(1000, reserved=900) == 1
    assert pack_content_budget(0) == 1


def test_filter_ignores_case_suffixes_vendor_and_blank_names():
    files = [
        SimpleNamespace(filename="Package-Lock.json"),
        SimpleNamespace(filename="README.MD"),
        SimpleNamespace(filename="vendor/lib.py"),
        SimpleNamespace(filename="docs/guide.md"),
        SimpleNamespace(filename="assets/logo.PNG"),
        SimpleNamespace(filename="web/app.min.js"),
        SimpleNamespace(filename=""),
        SimpleNamespace(filename="   "),
        SimpleNamespace(filename=None),
        SimpleNamespace(filename="docs\\nested\\note.py"),
        SimpleNamespace(filename="src/readme.py"),
        SimpleNamespace(filename="src/app.py"),
    ]

    kept = [item.filename for item in filter_reviewable_files(files)]

    assert kept == ["src/readme.py", "src/app.py"]


def test_hunk_ranges_cover_deletion_only_and_default_count():
    assert parse_new_file_hunk_ranges(None) == []
    assert parse_new_file_hunk_ranges("@@ -1 +1 @@\n-a\n+b\n") == [(1, 1)]
    assert parse_new_file_hunk_ranges("@@ -10,2 +9,0 @@\n-old\n") == [(9, 9)]
    assert parse_new_file_hunk_ranges("@@ -1,3 +0,0 @@\n-gone\n") == []


def test_overlapping_windows_merge_and_clip_to_the_file():
    merged = merge_line_windows(
        [(1, 5), (8, 10)],
        context_lines=2,
        line_count=12,
    )
    assert merged == [(1, 12)]

    clipped = merge_line_windows([(1, 2)], context_lines=40, line_count=3)
    assert clipped == [(1, 3)]


def test_removed_file_uses_the_patch_and_ignores_fetched_source():
    windows = build_file_windows(
        filename="gone.py",
        status="removed",
        patch="@@ -1,1 +0,0 @@\n-print(1)\n",
        source_text="print(1)\nprint(2)\n",
        context_lines=40,
        max_chars=8000,
    )
    assert len(windows) == 1
    assert "gone.py" in windows[0]
    assert "print(1)" in windows[0]
    assert "print(2)" not in windows[0]
    assert "Status: removed" in windows[0]


def test_missing_patch_and_source_is_a_review_gap_not_a_skip():
    windows = build_file_windows(
        filename="mystery.bin",
        status="modified",
        patch=None,
        source_text=None,
        context_lines=40,
        max_chars=8000,
    )
    assert len(windows) == 1
    assert "mystery.bin" in windows[0]
    assert "review gap" in windows[0]


def test_pack_intro_requires_file_path_and_keeps_every_window():
    windows = [
        ("a.py", "A" * 120),
        ("b.py", "B" * 120),
        ("a.py", "C" * 120),
    ]
    packs = pack_review_windows(windows, max_chars=200)
    blob = "\n".join(pack.content for pack in packs)
    assert len(packs) > 1
    assert "file_path" in packs[0].content
    assert "A" * 120 in blob
    assert "B" * 120 in blob
    assert "C" * 120 in blob
    assert packs[0].filenames == ["a.py"]


def test_split_patch_by_hunks_keeps_small_hunks_and_splits_a_long_one():
    small = "@@ -1,1 +1,1 @@\n-a\n+b\n@@ -3,1 +3,1 @@\n-c\n+d\n"
    chunks = split_patch_by_hunks(small, max_chars=10_000)
    assert len(chunks) == 1
    assert "+b" in chunks[0]
    assert "+d" in chunks[0]

    long_hunk = "@@ -1,1 +1,1 @@\n" + "".join(f"+line{i}\n" for i in range(30))
    pieces = split_patch_by_hunks(long_hunk, max_chars=40)
    assert len(pieces) > 1
    assert "".join(pieces).count("+line") == 30
    assert split_patch_by_hunks("", max_chars=40) == []
