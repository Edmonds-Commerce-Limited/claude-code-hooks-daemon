"""The test-suite shards: named slices of ``tests/``, each its own QA checkpoint.

``scripts/qa/test_shards.yaml`` is the one declaration. A shard is either a
list of pytest ``paths`` or the ``remainder_of`` a directory: everything under
it that no other shard claims, so a new test directory lands in a shard without
anyone editing the file. ``tests/unit/qa/test_suite_shards.py`` checks the
declaration against every test file on disk, so sharding can neither drop nor
double-run a test.

A shard's ``scope`` is ``unit`` (everything under ``tests/unit``) or ``rest``
(everything else), the two scopes the extra interpreters run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final

import yaml

from claude_code_hooks_daemon.utils.path_containment import path_relative_to

SCOPE_UNIT: Final[str] = "unit"
SCOPE_REST: Final[str] = "rest"
SCOPES: Final[frozenset[str]] = frozenset({SCOPE_UNIT, SCOPE_REST})

#: pytest's ``python_files`` (pyproject.toml) for the walk of ``tests/``.
TEST_FILE_GLOB: Final[str] = "test_*.py"

_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_ALLOWED_KEYS: Final[frozenset[str]] = frozenset({"name", "scope", "paths", "remainder_of"})
_SKIPPED_DIRS: Final[frozenset[str]] = frozenset({"__pycache__", "node_modules", "venv", "build"})


class ShardError(ValueError):
    """The shard declaration is unreadable or inconsistent."""


@dataclass(frozen=True)
class Shard:
    """One slice of the suite: the pytest ``paths`` it runs minus what it ``ignore``s."""

    name: str
    scope: str
    paths: tuple[str, ...]
    ignore: tuple[str, ...] = ()

    @property
    def pytest_args(self) -> list[str]:
        """The pytest arguments that select exactly this shard."""
        return [*self.paths, *(f"--ignore={path}" for path in self.ignore)]


def _under(path: str, root: str) -> bool:
    """Whether ``path`` is ``root`` or inside it (a directory boundary, not a string prefix)."""
    return path == root or path.startswith(f"{root}/")


def _checked_path(shard: str, path: object) -> str:
    if not isinstance(path, str) or not path:
        raise ShardError(f"shard {shard}: {path!r} is not a path string")
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts:
        raise ShardError(f"shard {shard}: {path!r} must be a relative path with no '..'")
    return str(pure)


def _parse_entry(entry: object) -> tuple[str, str, list[str], str | None]:
    if not isinstance(entry, dict):
        raise ShardError(f"a shard entry must be a mapping, got {entry!r}")
    unknown = sorted(set(entry) - _ALLOWED_KEYS)
    if unknown:
        raise ShardError(f"shard entry has unknown keys {unknown}")
    name = entry.get("name")
    if not isinstance(name, str) or not _NAME_PATTERN.match(name):
        raise ShardError(f"shard name {name!r} must be lowercase words joined by '-'")
    scope = entry.get("scope")
    if scope not in SCOPES:
        raise ShardError(f"shard {name}: scope {scope!r} must be one of {sorted(SCOPES)}")
    has_paths, has_remainder = "paths" in entry, "remainder_of" in entry
    if has_paths == has_remainder:
        raise ShardError(f"shard {name}: give exactly one of paths or remainder_of")
    if has_remainder:
        return name, scope, [], _checked_path(name, entry["remainder_of"])
    raw_paths = entry["paths"]
    if not isinstance(raw_paths, list) or not raw_paths:
        raise ShardError(f"shard {name}: paths must be a non-empty list")
    return name, scope, [_checked_path(name, p) for p in raw_paths], None


def _prune_nested(paths: list[str]) -> tuple[str, ...]:
    """``paths`` without any path already inside another, sorted."""
    kept = [p for p in sorted(set(paths)) if not any(q != p and _under(p, q) for q in paths)]
    return tuple(kept)


def load_shards(path: Path) -> list[Shard]:
    """The shards declared in ``path``, in declaration order.

    Raises:
        ShardError: the file is unreadable or unparseable, or the declaration is
            malformed (bad or duplicate name, unknown scope, a path that is not
            relative, two remainders of one directory, no shards at all).
    """
    try:
        document: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ShardError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ShardError(f"cannot parse {path}: {exc}") from exc
    entries = document.get("shards") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        raise ShardError(f"{path} must hold a top-level `shards:` list")
    if not entries:
        raise ShardError(f"{path} declares no shards")

    parsed = [_parse_entry(entry) for entry in entries]
    names = [name for name, _, _, _ in parsed]
    for name in sorted({n for n in names if names.count(n) > 1}):
        raise ShardError(f"duplicate shard name {name}")
    remainders = [root for _, _, _, root in parsed if root is not None]
    for root in sorted({r for r in remainders if remainders.count(r) > 1}):
        raise ShardError(f"two shards are the remainder of {root}")

    shards: list[Shard] = []
    for name, scope, paths, remainder_of in parsed:
        if remainder_of is None:
            shards.append(Shard(name, scope, tuple(paths)))
            continue
        claimed = [
            p
            for other, _, other_paths, other_root in parsed
            if other != name
            for p in (other_paths or [other_root or ""])
            if _under(p, remainder_of)
        ]
        shards.append(Shard(name, scope, (remainder_of,), _prune_nested(claimed)))
    return shards


def shards_in_scope(shards: list[Shard], scope: str) -> list[Shard]:
    """The shards of ``scope``, in declaration order."""
    return [shard for shard in shards if shard.scope == scope]


def owning_shards(shards: list[Shard], test_file: str) -> list[Shard]:
    """Every shard that would run ``test_file`` (a repo-relative path); one is right."""
    return [
        shard
        for shard in shards
        if any(_under(test_file, path) for path in shard.paths)
        and not any(_under(test_file, path) for path in shard.ignore)
    ]


def collected_test_files(root: Path, tests_dir: str) -> list[str]:
    """Every pytest test file under ``root/tests_dir``, repo-relative and sorted.

    Hidden directories and the build/cache directories pytest never recurses
    into are skipped.
    """
    found: list[str] = []
    for file in (root / tests_dir).rglob(TEST_FILE_GLOB):
        relative = path_relative_to(file, root)
        parts = relative.parts
        if any(part.startswith(".") or part in _SKIPPED_DIRS for part in parts[:-1]):
            continue
        found.append(relative.as_posix())
    return sorted(found)
