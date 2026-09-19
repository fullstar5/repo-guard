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


# Original tests for build_combined_review_input / build_review_chunks.
# def _file(filename: str, patch: str = "@@ -1 +1 @@\n+ok\n") -> SimpleNamespace:
#     return SimpleNamespace(
#         id=1,
#         filename=filename,
#         status="modified",
#         additions=1,
#         deletions=0,
#         changes=1,
#         patch=patch,
#     )
#
#
# def test_combined_and_chunk_builders_skip_ignored_paths():
#     files = [
#         _file("package-lock.json", patch="+" + ("x" * 50_000)),
#         _file("app/__pycache__/mod.pyc", patch="+" + ("y" * 50_000)),
#         _file("app/hello.py", patch="@@ -1 +1 @@\n+print(1)\n"),
#     ]
#
#     combined = build_combined_review_input(files)
#     chunks = build_review_chunks(files)
#
#     assert combined is not None
#     assert "package-lock.json" not in combined
#     assert "__pycache__" not in combined
#     assert "app/hello.py" in combined
#     assert [chunk.filename for chunk in chunks] == ["app/hello.py"]


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