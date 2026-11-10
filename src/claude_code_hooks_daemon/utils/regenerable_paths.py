"""Which ignored paths a worktree removal may destroy, because each is rebuilt on demand.

The list is ``branches.cleanup_after_merge.regenerable`` (Plan 00558 Task 3.1).
Entries are the ``git ls-files --others --ignored --directory`` form: relative to
the worktree root, a directory ending in ``/``.

Pattern dialect, a gitignore-style subset:

- A trailing ``/`` matches directories only (and so everything inside one).
- A pattern with no other ``/`` is a NAME: it matches a path segment at any depth.
- A pattern with a ``/`` (a leading one included) is anchored to the root, and
  each ``/``-separated segment is matched against one path segment.
- ``*`` and ``?`` never cross a ``/``.

:data:`NEVER_REGENERABLE` holds an agent's working notes, so no list may cover
it; the config load rejects one that does.
"""

from __future__ import annotations

import fnmatch
import json
import logging
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass

from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

logger = logging.getLogger(__name__)

#: The model default for ``branches.cleanup_after_merge.regenerable``.
DEFAULT_REGENERABLE_STORES: tuple[str, ...] = (
    "untracked/venv-*/",
    "untracked/qa/",
    "untracked/docs-qa/",
    "untracked/branch-inventory/",
    "untracked/daemon-*",
    "untracked/events-*",
    "untracked/.venv-bootstrap*",
    "untracked/lsp-venv/",
    "untracked/repair.log",
    "untracked/repair.txt",
    "untracked/.python-cmd-cache",
    "untracked/context-sidecar/",
    "untracked/logs/",
    "untracked/acceptance/",
    "untracked/spend-ledger/",
    "/.coverage",
    "/.CLAUDE.md.pre-inject",
    ".claude/hooks-daemon/",
    "*.egg-info/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
)

#: The scratch notes directory: always a blocker, whatever a project lists.
NEVER_REGENERABLE = "untracked/scratch/"

#: Entries checked to prove a pattern list leaves the scratch directory alone.
_NEVER_REGENERABLE_PROBES = (NEVER_REGENERABLE, f"{NEVER_REGENERABLE}notes.md")


def _matches(entry_parts: Sequence[str], entry_is_dir: bool, pattern: str) -> bool:
    """Whether ``pattern`` matches the entry or any directory above it."""
    dir_only = pattern.endswith("/")
    body = pattern.strip("/")
    anchored = pattern.startswith("/") or "/" in body
    segments = body.split("/")
    for depth in range(1, len(entry_parts) + 1):
        is_dir = depth < len(entry_parts) or entry_is_dir
        if dir_only and not is_dir:
            continue
        if anchored:
            if depth == len(segments) and all(
                fnmatch.fnmatchcase(part, segment)
                for part, segment in zip(entry_parts[:depth], segments, strict=True)
            ):
                return True
        elif fnmatch.fnmatchcase(entry_parts[depth - 1], body):
            return True
    return False


def _composer_outputs(manifest_text: str | None) -> tuple[str, ...]:
    """Composer's install directories: ``config.vendor-dir`` and ``config.bin-dir``.

    Read from the committed ``composer.json``; anything absent, malformed or
    pointing outside the manifest's directory falls back to ``vendor`` and
    ``vendor/bin``.
    """
    config: object = {}
    if manifest_text is not None:
        try:
            document = json.loads(manifest_text)
        except ValueError as exc:
            log_and_continue(
                logger,
                exc,
                reason="a malformed composer.json uses the default vendor and bin directories",
            )
            document = None
        if isinstance(document, dict):
            config = document.get("config", {})
    settings = config if isinstance(config, dict) else {}

    def setting(key: str, default: str) -> str:
        value = settings.get(key)
        if not isinstance(value, str):
            return default
        cleaned = value.strip().strip("/")
        if not cleaned or value.startswith("/") or ".." in cleaned.split("/"):
            return default
        return cleaned

    vendor = setting("vendor-dir", "vendor")
    return (f"{vendor}/", f"{setting('bin-dir', f'{vendor}/bin')}/")


@dataclass(frozen=True)
class LockRegeneratedRule:
    """A package manager that rebuilds ``outputs`` from a manifest and its lock file."""

    manifest: str
    locks: tuple[str, ...]
    outputs: tuple[str, ...]
    #: Derives ``outputs`` from the committed manifest text, when it can move them.
    resolve_outputs: Callable[[str | None], tuple[str, ...]] | None = None


#: One row per package manager; the single source for what a lock file regenerates.
LOCK_REGENERATED_RULES: tuple[LockRegeneratedRule, ...] = (
    LockRegeneratedRule(
        "composer.json", ("composer.lock",), ("vendor/", "vendor/bin/"), _composer_outputs
    ),
    LockRegeneratedRule(
        "package.json",
        ("package-lock.json", "yarn.lock", "pnpm-lock.yaml"),
        ("node_modules/",),
    ),
    LockRegeneratedRule("Gemfile", ("Gemfile.lock",), ("vendor/bundle/",)),
    LockRegeneratedRule("Cargo.toml", ("Cargo.lock",), ("target/",)),
    LockRegeneratedRule("pyproject.toml", ("uv.lock", "poetry.lock"), (".venv/",)),
)


def lock_regenerated_dirs(
    committed: Collection[str], read_committed: Callable[[str], str | None]
) -> tuple[str, ...]:
    """Directories a committed manifest + lock pair lets its package manager rebuild.

    ``committed`` is every path in the branch's tree. A directory qualifies when
    its manifest and one lock sit together in the tree, it is not under
    :data:`NEVER_REGENERABLE`, and no committed file lies inside it (a tracked
    file is work, whatever the manager does). ``read_committed`` returns a
    committed file's text, or None.
    """
    tree = set(committed)
    found: list[str] = []
    for path in sorted(tree):
        base, _, filename = path.rpartition("/")
        prefix = f"{base}/" if base else ""
        for rule in LOCK_REGENERATED_RULES:
            if filename != rule.manifest or not any(
                f"{prefix}{lock}" in tree for lock in rule.locks
            ):
                continue
            outputs = (
                rule.resolve_outputs(read_committed(path)) if rule.resolve_outputs else rule.outputs
            )
            for output in outputs:
                directory = f"{prefix}{output}"
                if (
                    directory not in found
                    and not under_any(directory, [NEVER_REGENERABLE])
                    and not any(under_any(other, [directory]) for other in tree)
                ):
                    found.append(directory)
    return tuple(found)


def under_any(entry: str, directories: Iterable[str]) -> bool:
    """Whether ``entry`` is one of ``directories`` (each ending ``/``) or lies inside one."""
    return any(entry.startswith(directory) for directory in directories)


def is_regenerable(entry: str, patterns: Sequence[str]) -> bool:
    """Whether an ignored ``ls-files --directory`` entry lies under one of ``patterns``."""
    parts = entry.strip("/").split("/")
    return any(_matches(parts, entry.endswith("/"), pattern) for pattern in patterns)


def never_regenerable_violations(patterns: Sequence[str]) -> list[str]:
    """The patterns that would class :data:`NEVER_REGENERABLE` as regenerable."""
    return [
        pattern
        for pattern in patterns
        if any(is_regenerable(probe, [pattern]) for probe in _NEVER_REGENERABLE_PROBES)
    ]


__all__ = [
    "DEFAULT_REGENERABLE_STORES",
    "NEVER_REGENERABLE",
    "is_regenerable",
    "never_regenerable_violations",
]
