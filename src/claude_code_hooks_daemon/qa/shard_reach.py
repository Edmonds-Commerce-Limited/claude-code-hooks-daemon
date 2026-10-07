"""Which test shards a change can reach, for the targeted ``changed`` tier.

``scripts/qa/changed_shard_reach.yaml`` is the declaration. A changed file the
name and import mapping cannot cover is not a reason to run the whole suite when
only some shards could exercise it. Two declared lists decide what is sound:

``whole_suite``
    Files nothing sound can be said about (build config, the root conftest, the
    QA tooling itself): the whole suite must cover them.
``floors``
    Shards a matching source file can always reach, whatever statically refers
    to it: end-to-end tests spawn the daemon and load handlers dynamically, so
    no import ever names the code they exercise.

The runner adds the shards of the tests that statically refer to the file on
top of its floor. The result is only ever wider than what is reachable, never
narrower.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml

from claude_code_hooks_daemon.qa.suite_shards import (
    Shard,
    ShardError,
    collected_test_files,
    owning_shards,
)

_ANY_DEPTH: Final[str] = "**"
_KEY_WHOLE_SUITE: Final[str] = "whole_suite"
_KEY_FLOORS: Final[str] = "floors"
_KEY_GLOB: Final[str] = "path_glob"
_KEY_WHY: Final[str] = "why"
_KEY_SHARDS: Final[str] = "shards"
_TOP_KEYS: Final[frozenset[str]] = frozenset({_KEY_WHOLE_SUITE, _KEY_FLOORS})
_WHOLE_KEYS: Final[frozenset[str]] = frozenset({_KEY_GLOB, _KEY_WHY})
_FLOOR_KEYS: Final[frozenset[str]] = frozenset({_KEY_GLOB, _KEY_WHY, _KEY_SHARDS})


def path_glob_matches(relative: str, pattern: str) -> bool:
    """Whether ``Path(root).glob(pattern)`` would yield ``relative``.

    Each segment is matched on its own, so ``*`` never crosses ``/``, and a
    ``**`` segment matches zero or more whole directories.
    """
    return _segments_match(relative.split("/"), pattern.split("/"))


def _segments_match(parts: Sequence[str], patterns: Sequence[str]) -> bool:
    if not patterns:
        return not parts
    head, rest = patterns[0], patterns[1:]
    if head == _ANY_DEPTH:
        return any(_segments_match(parts[skip:], rest) for skip in range(len(parts) + 1))
    return bool(parts) and fnmatch.fnmatchcase(parts[0], head) and _segments_match(parts[1:], rest)


@dataclass(frozen=True, slots=True)
class WholeSuiteRule:
    """A path glob the whole suite must cover, and why."""

    glob: str
    why: str


@dataclass(frozen=True, slots=True)
class FloorRule:
    """A path glob and the shards a matching file can always reach."""

    glob: str
    shards: tuple[str, ...]
    why: str


@dataclass(frozen=True, slots=True)
class ShardReach:
    """The declared whole-suite triggers and shard floors."""

    whole_suite: tuple[WholeSuiteRule, ...]
    floors: tuple[FloorRule, ...]


def _entries(document: dict[str, Any], key: str, allowed: frozenset[str]) -> list[dict[str, Any]]:
    raw = document.get(key, [])
    if not isinstance(raw, list):
        raise ShardError(f"`{key}` must be a list")
    for entry in raw:
        if not isinstance(entry, dict):
            raise ShardError(f"`{key}` entry {entry!r} must be a mapping")
        unknown = sorted(set(entry) - allowed)
        if unknown:
            raise ShardError(f"`{key}` entry has unknown keys {unknown}")
        for required in (_KEY_GLOB, _KEY_WHY):
            value = entry.get(required)
            if not isinstance(value, str) or not value.strip():
                raise ShardError(
                    f"`{key}` entry {entry!r}: `{required}` must be a non-empty string"
                )
    return raw


def load_shard_reach(path: Path, shards: Sequence[Shard]) -> ShardReach:
    """Read and validate the reach declaration against the declared ``shards``.

    Raises:
        ShardError: the file is unreadable, malformed, has an unknown key, or a
            floor names a shard that is not declared.
    """
    try:
        document: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ShardError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ShardError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ShardError(f"{path} must be a mapping")
    unknown = sorted(set(document) - _TOP_KEYS)
    if unknown:
        raise ShardError(f"{path} has unknown keys {unknown}")

    known = {shard.name for shard in shards}
    floors: list[FloorRule] = []
    for entry in _entries(document, _KEY_FLOORS, _FLOOR_KEYS):
        named = entry.get(_KEY_SHARDS)
        if not isinstance(named, list) or not named or not all(isinstance(n, str) for n in named):
            raise ShardError(f"floor {entry[_KEY_GLOB]!r}: `shards` must be a non-empty list")
        missing = sorted(set(named) - known)
        if missing:
            raise ShardError(f"floor {entry[_KEY_GLOB]!r} names undeclared shard(s) {missing}")
        floors.append(FloorRule(entry[_KEY_GLOB], tuple(named), entry[_KEY_WHY].strip()))
    whole = [
        WholeSuiteRule(entry[_KEY_GLOB], entry[_KEY_WHY].strip())
        for entry in _entries(document, _KEY_WHOLE_SUITE, _WHOLE_KEYS)
    ]
    return ShardReach(whole_suite=tuple(whole), floors=tuple(floors))


def whole_suite_reason(reach: ShardReach, relative: str) -> str | None:
    """Why ``relative`` needs the whole suite, or None when no trigger matches."""
    for rule in reach.whole_suite:
        if path_glob_matches(relative, rule.glob):
            return rule.why
    return None


def floor_shards(reach: ShardReach, relative: str) -> tuple[set[str], list[str]]:
    """The shards every matching floor names for ``relative``, and each floor's why."""
    names: set[str] = set()
    whys: list[str] = []
    for rule in reach.floors:
        if path_glob_matches(relative, rule.glob):
            names.update(rule.shards)
            whys.append(rule.why)
    return names, whys


def shard_names_of(shards: Sequence[Shard], test_files: Sequence[str]) -> set[str]:
    """The names of the shards that own ``test_files``."""
    shard_list = list(shards)
    return {shard.name for test in test_files for shard in owning_shards(shard_list, test)}


def shard_targets(shard: Shard, root: Path) -> list[str]:
    """The pytest paths that run exactly ``shard``.

    A shard with no ``ignore`` is its directories. One that ignores another
    shard's tests is its explicit files: an ``--ignore`` beside explicit
    selections would be a second place that decides what runs.
    """
    if not shard.ignore:
        return list(shard.paths)
    files: list[str] = []
    for path in shard.paths:
        files.extend(
            test for test in collected_test_files(root, path) if owning_shards([shard], test)
        )
    return sorted(set(files))


__all__ = [
    "FloorRule",
    "ShardReach",
    "WholeSuiteRule",
    "floor_shards",
    "load_shard_reach",
    "path_glob_matches",
    "shard_names_of",
    "shard_targets",
    "whole_suite_reason",
]
