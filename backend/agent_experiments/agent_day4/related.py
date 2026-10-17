import re
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

from app.services.diff_chunking import filter_reviewable_files

MAX_RELATED = 10
MAX_HITS = 10

# Absolute Python imports whose first segment is a standard library or a
# third-party package. These are not files in the repository being reviewed.
_SKIP_TOP_LEVEL = frozenset(
    {
        "json", "os", "sys", "re", "typing", "dataclasses", "pathlib", "collections",
        "functools", "itertools", "http", "httpx", "sqlalchemy", "fastapi", "pydantic",
        "enum", "abc", "datetime", "unittest", "ast", "types",
    }
)

# Go standard library. A path whose first segment is here is not repository code.
_GO_STDLIB = frozenset(
    {
        "fmt", "os", "io", "net", "http", "encoding", "crypto", "context", "sync",
        "time", "strings", "strconv", "bytes", "bufio", "errors", "log", "math",
        "sort", "path", "filepath", "reflect", "runtime", "testing", "unicode",
        "regexp", "database", "html", "image", "mime", "hash", "compress",
        "container", "embed", "flag", "go", "maps", "slices",
    }
)

_PY_FROM = re.compile(
    r"^\s*from\s+(\.*)([\w.]*)\s+import\s+(\([^)]*\)|[^\n#]+)",
    re.MULTILINE,
)
_PY_IMPORT = re.compile(
    r"^\s*import\s+([^\n#]+)",
    re.MULTILINE,
)
_JS_RELATIVE = re.compile(
    r"""(?:import\s+.*?from\s+|export\s+.*?from\s+|require\()\s*['"](\.[^'"]+)['"]""",
)
_JAVA = re.compile(
    r"^\s*import\s+(?:static\s+)?([\w.]+?)(?:\.\*)?\s*;",
    re.MULTILINE,
)
_CSHARP = re.compile(
    r"^\s*using\s+(?:static\s+)?([\w.]+)\s*;",
    re.MULTILINE,
)
_GO_SINGLE = re.compile(
    r'^\s*import\s+(?:[\w.]+\s+)?"([^"]+)"',
    re.MULTILINE,
)
_GO_GROUP = re.compile(r"import\s*\((.*?)\)", re.DOTALL)
_GO_SPEC = re.compile(r'"([^"]+)"')
_RUST = re.compile(
    r"^\s*(?:pub(?:\([^)]*\))?\s+)?use\s+((?:crate|super|self)(?:::[\w*]+)+)",
    re.MULTILINE,
)
_RUBY = re.compile(
    r"""^\s*require_relative\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_PHP_USE = re.compile(
    r"^\s*use\s+([\w\\]+)(?:\s+as\s+\w+)?\s*;",
    re.MULTILINE,
)
_PHP_REQUIRE = re.compile(
    r"""^\s*(?:require|include)(?:_once)?\s*\(?\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_C_INCLUDE = re.compile(
    r'^\s*#\s*include\s+"([^"]+)"',
    re.MULTILINE,
)
_DART = re.compile(
    r"""^\s*import\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)


def is_ignored_path(path: str) -> bool:
    """Return whether the existing review filter would skip this path.

    Args:
        path: Repository path using forward slashes.

    Returns:
        True for lockfiles, images, generated files, and blank names.
    """
    return not filter_reviewable_files([SimpleNamespace(filename=path)])


def _python_file(module: str) -> str:
    """Turn a dotted Python module into a repository path.

    Args:
        module: Import module, such as ``app.services.github_tokens``.

    Returns:
        A ``.py`` path.
    """
    return module.replace(".", "/") + ".py"


def _import_names(raw: str) -> list[str]:
    """Split the name list that follows a Python ``import``.

    Args:
        raw: Text after ``import``, possibly wrapped in parentheses.

    Returns:
        Identifier names, without ``as`` aliases. ``*`` is omitted.
    """
    text = raw.strip()
    if text.startswith("("):
        text = text[1:]
    if text.endswith(")"):
        text = text[:-1]
    names: list[str] = []
    for part in text.replace("\n", " ").split(","):
        piece = part.strip()
        if not piece or piece == "*":
            continue
        name = piece.split(" as ", 1)[0].strip().split()[0]
        if name.isidentifier():
            names.append(name)
    return names


def _relative_directory(file_path: str, dots: str) -> PurePosixPath | None:
    """Walk up from a file for a relative Python import.

    Args:
        file_path: File that contains the import.
        dots: One or more leading dots.

    Returns:
        The package directory those dots select, or None if they leave the tree.
    """
    directory = PurePosixPath(file_path).parent
    for _ in range(len(dots) - 1):
        if str(directory) in {"", "."}:
            return None
        directory = directory.parent
    return directory


def _repo_root() -> Path:
    """Find the git checkout that contains this experiment.

    Returns:
        The directory that contains ``.git``, or a parent used as a fallback.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists():
            return parent
    return here.parents[3]


def _locate_in_repo(importer: str, relative: str) -> str | None:
    """Find a guessed import path that exists in this checkout.

    Python imports are resolved from a package root, which may sit below the
    git root. ``app.core.database`` is ``backend/app/core/database.py`` here.

    Args:
        importer: File that contains the import.
        relative: Path guessed from the import text, such as ``app/core/database.py``.

    Returns:
        A repository path of an existing file, or None.
    """
    root = _repo_root()
    relative_path = PurePosixPath(relative)
    directories = [PurePosixPath(".")]
    current = PurePosixPath(importer).parent
    while str(current) not in {"", "."}:
        directories.append(current)
        current = current.parent
    seen: set[str] = set()
    for directory in directories:
        candidate = directory / relative_path if str(directory) != "." else relative_path
        normalized = _normalize(PurePosixPath(str(candidate)))
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        if (root / normalized).is_file():
            return normalized
    return None


def _prefer_existing(importer: str, guesses: list[str]) -> list[str]:
    """Keep guessed paths that exist, falling back to the first guess.

    Args:
        importer: File that contains the import.
        guesses: Paths derived from the import statement.

    Returns:
        Existing repository paths. When none exist locally, the first guess is
        kept so a later GitHub read can still try it.
    """
    located: list[str] = []
    for guess in guesses:
        found = _locate_in_repo(importer, guess)
        if found and found not in located:
            located.append(found)
    if located:
        return located
    return guesses[:1]


def _resolve_python(file_path: str, dots: str, module: str, names: list[str]) -> list[str]:
    """Resolve one Python import into repository file candidates.

    ``from . import something`` treats each imported name as a module in the
    current package. ``from .tools import execute_tool`` points at ``tools.py``
    and does not invent a file for the imported symbol. Absolute imports are
    then matched to a file that exists in this checkout, so ``app.core.database``
    can become ``backend/app/core/database.py``.

    Args:
        file_path: File whose source is being scanned.
        dots: Leading dots. Empty means an absolute import.
        module: Dotted module after the dots.
        names: Names that follow ``import``.

    Returns:
        Candidate paths. An empty list means the import is skipped.
    """
    results: list[str] = []
    if not dots:
        if not module or module.split(".", 1)[0] in _SKIP_TOP_LEVEL:
            return []
        parent = module.replace(".", "/")
        results.append(parent + ".py")
        results.append(parent + "/__init__.py")
        return _prefer_existing(file_path, results)

    directory = _relative_directory(file_path, dots)
    if directory is None:
        return []
    if module:
        target = directory.joinpath(*module.split("."))
        results.append(str(target) + ".py")
        results.append(str(target / "__init__.py"))
        return _prefer_existing(file_path, results)
    for name in names:
        results.append(str(directory / name) + ".py")
        results.append(str(directory / name / "__init__.py"))
    return _prefer_existing(file_path, results)


def _normalize(path: PurePosixPath) -> str | None:
    """Collapse ``.`` and ``..`` without leaving the repository root.

    Args:
        path: Path that may still contain relative segments.

    Returns:
        A forward-slash path, or None when the path escapes the root.
    """
    parts: list[str] = []
    for part in path.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    if not parts:
        return None
    return "/".join(parts)


def _source_suffix(file_path: str, default: str) -> str:
    """Choose a source suffix from the file being scanned.

    Args:
        file_path: File whose imports are being scanned.
        default: Suffix used when the current file has a different kind.

    Returns:
        A suffix including the dot.
    """
    suffix = PurePosixPath(file_path).suffix.lower()
    if suffix in {".java", ".kt", ".kts", ".scala", ".cs"}:
        return suffix
    return default


def _dotted_to_path(module: str, suffix: str) -> str:
    """Turn a dotted language name into a file path.

    Args:
        module: Name such as ``com.example.Jwt``.
        suffix: File suffix, including the dot.

    Returns:
        A repository path.
    """
    return module.replace(".", "/") + suffix


def _resolve_javascript(file_path: str, spec: str) -> str | None:
    """Resolve a relative JavaScript or TypeScript import.

    Args:
        file_path: File whose source is being scanned.
        spec: Import specifier beginning with ``.``.

    Returns:
        A repository path. A missing suffix keeps the source file's suffix.
    """
    joined = PurePosixPath(file_path).parent.joinpath(spec)
    normalized = _normalize(PurePosixPath(str(joined)))
    if normalized is None:
        return None
    path = PurePosixPath(normalized)
    if path.suffix:
        return str(path)
    return str(path.with_suffix(PurePosixPath(file_path).suffix or ".ts"))


def _java_family_paths(file_path: str, source: str) -> list[str]:
    """Resolve Java, Kotlin, and Scala import declarations.

    Args:
        file_path: File being scanned. Its suffix selects ``.java``, ``.kt``, or ``.scala``.
        source: Source text.

    Returns:
        Candidate paths. ``java.*`` and ``javax.*`` are omitted.
    """
    suffix = _source_suffix(file_path, ".java")
    paths: list[str] = []
    for module in _JAVA.findall(source):
        top = module.split(".", 1)[0]
        if top in {"java", "javax", "jdk", "kotlin", "scala", "androidx"}:
            continue
        paths.append(_dotted_to_path(module, suffix))
    return paths


def _csharp_paths(source: str) -> list[str]:
    """Resolve C# ``using`` namespace declarations.

    Args:
        source: Source text.

    Returns:
        Candidate ``.cs`` paths. ``System`` and ``Microsoft`` are omitted.
        A namespace does not always match a folder; the path is a candidate.
    """
    paths: list[str] = []
    for module in _CSHARP.findall(source):
        top = module.split(".", 1)[0]
        if top in {"System", "Microsoft"}:
            continue
        paths.append(_dotted_to_path(module, ".cs"))
    return paths


def _go_repo_file(import_path: str) -> str | None:
    """Turn a Go import path into one repository file candidate.

    Args:
        import_path: Quoted path from an ``import`` declaration.

    Returns:
        A ``.go`` path, or None for the standard library and a bare module root.
    """
    parts = [part for part in import_path.split("/") if part]
    if not parts or parts[0] in _GO_STDLIB:
        return None
    if "." in parts[0]:
        if len(parts) <= 3:
            return None
        tail = "/".join(parts[3:])
    else:
        tail = import_path
    last = tail.rsplit("/", 1)[-1]
    return f"{tail}/{last}.go"


def _go_paths(source: str) -> list[str]:
    """Resolve Go import strings that point inside a repository.

    Args:
        source: Source text.

    Returns:
        Candidate ``.go`` paths.
    """
    specs = _GO_SINGLE.findall(source)
    for block in _GO_GROUP.findall(source):
        specs.extend(_GO_SPEC.findall(block))
    paths: list[str] = []
    for spec in specs:
        resolved = _go_repo_file(spec)
        if resolved is not None:
            paths.append(resolved)
    return paths


def _rust_base(file_path: str, kind: str) -> PurePosixPath | None:
    """Find the directory a Rust ``self`` or ``super`` path starts from.

    Args:
        file_path: File containing the ``use`` item.
        kind: ``self`` or ``super``.

    Returns:
        The starting directory, or None when ``super`` leaves the tree.
    """
    path = PurePosixPath(file_path)
    if path.name == "mod.rs":
        current = path.parent
        parent = current.parent
    else:
        current = path.with_suffix("")
        parent = path.parent
    if kind == "self":
        return current
    if str(parent) in {"", "."}:
        return None
    return parent


def _rust_paths(file_path: str, source: str) -> list[str]:
    """Resolve Rust ``use crate``, ``use super``, and ``use self`` paths.

    Args:
        file_path: File containing the ``use`` item.
        source: Source text.

    Returns:
        Candidate ``.rs`` paths. External crates are not matched.
    """
    paths: list[str] = []
    for raw in _RUST.findall(source):
        parts = [part for part in raw.split("::") if part and part != "*"]
        if not parts:
            continue
        if parts[0] == "crate":
            tail = parts[1:]
            if tail:
                paths.append("src/" + "/".join(tail) + ".rs")
            continue
        if parts[0] not in {"super", "self"}:
            continue
        directory = _rust_base(file_path, parts[0])
        index = 1
        while directory is not None and index < len(parts) and parts[index] == "super":
            directory = directory.parent
            if str(directory) in {"", "."}:
                directory = None
            index += 1
        if directory is None:
            continue
        tail = parts[index:]
        if not tail:
            continue
        paths.append(str(directory.joinpath(*tail)) + ".rs")
    return paths


def _ruby_paths(file_path: str, source: str) -> list[str]:
    """Resolve Ruby ``require_relative`` paths.

    Args:
        file_path: File containing the require.
        source: Source text.

    Returns:
        Candidate ``.rb`` paths. Bare ``require`` names are omitted.
    """
    paths: list[str] = []
    for spec in _RUBY.findall(source):
        joined = PurePosixPath(file_path).parent.joinpath(spec)
        normalized = PurePosixPath(str(joined))
        if normalized.suffix:
            paths.append(str(normalized))
        else:
            paths.append(str(normalized) + ".rb")
    return paths


def _php_paths(file_path: str, source: str) -> list[str]:
    """Resolve PHP ``use`` namespaces and quoted require paths.

    Args:
        file_path: File containing the statement.
        source: Source text.

    Returns:
        Candidate ``.php`` paths.
    """
    paths = [_dotted_to_path(name.replace("\\", "."), ".php") for name in _PHP_USE.findall(source)]
    for spec in _PHP_REQUIRE.findall(source):
        if spec.startswith(("/", "http://", "https://")):
            continue
        joined = PurePosixPath(file_path).parent.joinpath(spec)
        paths.append(str(PurePosixPath(str(joined))))
    return paths


def _c_include_paths(file_path: str, source: str) -> list[str]:
    """Resolve quoted C and C++ includes.

    Args:
        file_path: File containing the include.
        source: Source text.

    Returns:
        Paths from ``#include "..."``. Angle-bracket includes are omitted.
    """
    paths: list[str] = []
    for spec in _C_INCLUDE.findall(source):
        joined = PurePosixPath(file_path).parent.joinpath(spec)
        paths.append(str(PurePosixPath(str(joined))))
    return paths


def _dart_paths(file_path: str, source: str) -> list[str]:
    """Resolve Dart relative imports and ``package:`` imports.

    Args:
        file_path: File containing the import.
        source: Source text.

    Returns:
        Candidate ``.dart`` paths. ``dart:`` core libraries are omitted.
    """
    paths: list[str] = []
    for spec in _DART.findall(source):
        if spec.startswith("dart:"):
            continue
        if spec.startswith("package:"):
            rest = spec.removeprefix("package:")
            _, _, tail = rest.partition("/")
            if tail:
                paths.append(tail if tail.endswith(".dart") else tail + ".dart")
            continue
        joined = PurePosixPath(file_path).parent.joinpath(spec)
        normalized = _normalize(PurePosixPath(str(joined)))
        if normalized is not None:
            paths.append(normalized if normalized.endswith(".dart") else normalized + ".dart")
    return paths


def _reference_paths(file_path: str, source: str) -> list[str]:
    """Parse imports using the language implied by the file suffix.

    Args:
        file_path: File being scanned.
        source: Source or patch text.

    Returns:
        Candidate paths for that language. An unknown suffix yields nothing.
    """
    suffix = PurePosixPath(file_path).suffix.lower()
    if suffix == ".py":
        return _python_paths(file_path, source)
    if suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
        return [
            resolved
            for spec in _JS_RELATIVE.findall(source)
            if (resolved := _resolve_javascript(file_path, spec)) is not None
        ]
    if suffix in {".java", ".kt", ".kts", ".scala"}:
        return _java_family_paths(file_path, source)
    if suffix == ".cs":
        return _csharp_paths(source)
    if suffix == ".go":
        return _go_paths(source)
    if suffix == ".rs":
        return _rust_paths(file_path, source)
    if suffix == ".rb":
        return _ruby_paths(file_path, source)
    if suffix == ".php":
        return _php_paths(file_path, source)
    if suffix in {".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh"}:
        return _c_include_paths(file_path, source)
    if suffix == ".dart":
        return _dart_paths(file_path, source)
    return []


def _python_paths(file_path: str, source: str) -> list[str]:
    """Collect Python import candidates from one file.

    Args:
        file_path: File being scanned.
        source: Source or patch text.

    Returns:
        Candidate paths from ``from`` and ``import`` statements.
    """
    paths: list[str] = []
    for dots, module, raw_names in _PY_FROM.findall(source):
        paths.extend(_resolve_python(file_path, dots, module, _import_names(raw_names)))
    for raw in _PY_IMPORT.findall(source):
        for part in raw.split(","):
            module = part.strip().split(" as ", 1)[0].strip().split()[0]
            if module and all(piece.isidentifier() for piece in module.split(".")):
                paths.extend(_resolve_python(file_path, "", module, []))
    return paths


def related_paths(file_path: str, source: str, already_read: set[str]) -> list[str]:
    """List direct same-repository references in one file.

    Python, JavaScript, TypeScript, Java, Kotlin, Scala, C#, Go, Rust, Ruby,
    PHP, C, C++, and Dart statements are scanned. Each call is one hop: imports
    inside a discovered file are not followed. At most ``MAX_RELATED`` paths
    are returned.

    Args:
        file_path: Path of the file that was already read.
        source: Patch or source text to scan.
        already_read: Paths that must not be suggested again.

    Returns:
        Paths in first-seen order.
    """
    found: list[str] = []
    seen = set(already_read)
    seen.add(file_path)

    def add(path: str | None) -> None:
        if path is None or path in seen or is_ignored_path(path):
            return
        if len(found) >= MAX_RELATED:
            return
        seen.add(path)
        found.append(path)

    for path in _reference_paths(file_path, source):
        add(path)
        if len(found) >= MAX_RELATED:
            break
    return found


def search_hits(files: list[tuple[str, str | None]], query: str) -> dict[str, object]:
    """Search changed filenames and patches for one string.

    Args:
        files: Pairs of path and patch text.
        query: Text to find. Matching is case-insensitive.

    Returns:
        Up to ``MAX_HITS`` hits. ``truncated`` is true when more matches exist.
    """
    needle = query.lower()
    hits: list[dict[str, object]] = []
    truncated = False
    for path, patch in files:
        match = "filename" if needle in path.lower() else None
        snippet = None
        if match is None and patch and needle in patch.lower():
            match = "patch"
            index = patch.lower().find(needle)
            snippet = patch[max(0, index - 80): index + len(query) + 80]
        if match is None:
            continue
        if len(hits) >= MAX_HITS:
            truncated = True
            break
        item: dict[str, object] = {"path": path, "match": match}
        if snippet is not None:
            item["snippet"] = snippet
        hits.append(item)
    return {"query": query, "hits": hits, "truncated": truncated}
