from types import SimpleNamespace

from app.services.diff_chunking import (
    build_file_windows,
    filter_reviewable_files,
    pack_review_windows,
    parse_new_file_hunk_ranges,
)



def test_filter_reviewable_files_drops_noise_only():
    files = [
        SimpleNamespace(filename="app/main.py"),
        SimpleNamespace(filename="frontend/app/page.tsx"),
        SimpleNamespace(filename="app/__pycache__/main.cpython-312.pyc"),
        SimpleNamespace(filename="app/__pycache__/bar.py"),
        SimpleNamespace(filename="package-lock.json"),
        SimpleNamespace(filename="backend/uv.lock"),
        SimpleNamespace(filename="static/logo.png"),
        SimpleNamespace(filename="README.md"),
    ]

    kept = filter_reviewable_files(files)

    assert [item.filename for item in kept] == [
        "app/main.py",
        "frontend/app/page.tsx",
    ]


def test_every_reviewable_file_is_in_some_pack():
    windows = [
        ("a.py", "A" * 100),
        ("b.py", "B" * 100),
        ("c.py", "C" * 100),
    ]
    packs = pack_review_windows(windows, max_chars=180)
    names = {name for pack in packs for name in pack.filenames}
    assert names == {"a.py", "b.py", "c.py"}


def test_oversized_file_continues_in_later_packs():
    source = "\n".join(f"line{i}" for i in range(1, 81))
    patch = (
        "@@ -1,2 +1,2 @@\n-line1\n+line1x\n"
        "@@ -70,2 +70,2 @@\n-line70\n+line70x\n"
    )
    windows = build_file_windows(
        filename="huge.py",
        status="modified",
        patch=patch,
        source_text=source,
        context_lines=2,
        max_chars=400,
    )
    packs = pack_review_windows(
        [("huge.py", window) for window in windows],
        max_chars=400,
    )
    blob = "\n".join(pack.content for pack in packs)
    assert "line1" in blob
    assert "line70" in blob
    assert all("huge.py" in pack.filenames for pack in packs)


def test_hunk_windows_include_context_lines():
    source = "\n".join(f"L{i}" for i in range(1, 21))
    patch = "@@ -10,1 +10,1 @@\n-L10\n+L10 changed\n"
    windows = build_file_windows(
        filename="mod.py",
        status="modified",
        patch=patch,
        source_text=source,
        context_lines=3,
        max_chars=8000,
    )
    assert len(windows) == 1
    assert "L7" in windows[0]
    assert "L13" in windows[0]
    assert parse_new_file_hunk_ranges(patch) == [(10, 10)]


def test_missing_patch_still_covers_the_file():
    source = "\n".join(f"body{i}" for i in range(1, 6))
    windows = build_file_windows(
        filename="no_patch.py",
        status="modified",
        patch=None,
        source_text=source,
        context_lines=40,
        max_chars=8000,
    )
    assert len(windows) == 1
    assert "no_patch.py" in windows[0]
    assert "body1" in windows[0]
    assert "body5" in windows[0]


def test_oversized_single_line_is_split_not_dropped():
    long_line = "x" * 4000
    windows = build_file_windows(
        filename="wide.py",
        status="modified",
        patch="@@ -1,1 +1,1 @@\n-old\n+new\n",
        source_text=long_line,
        context_lines=0,
        max_chars=800,
    )
    blob = "".join(windows)
    assert blob.count("x") >= 4000
    assert len(windows) > 1
    assert all("wide.py" in window for window in windows)