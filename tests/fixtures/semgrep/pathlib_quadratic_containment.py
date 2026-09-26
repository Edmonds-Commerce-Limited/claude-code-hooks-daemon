"""Fixture for the ``pathlib-quadratic-containment`` semgrep rule (Plan 00466 N106).

DELIBERATELY DEFECTIVE CODE. Nothing here is imported or executed. Each hit is
a spelling of a containment check that walks ``path.parents`` on Python 3.12+
and so costs O(depth^2); the first three are the call sites CI caught.

Markers drive the assertions in
``tests/unit/qa/test_semgrep_pathlib_quadratic_containment.py``:

* ``# EXPECT-HIT``   — the rule MUST report this line
* ``# EXPECT-CLEAN`` — the rule MUST NOT report this line
"""

from os.path import realpath
from pathlib import Path

from claude_code_hooks_daemon.utils import path_containment
from claude_code_hooks_daemon.utils.path_containment import (
    path_is_relative_to,
    path_relative_to,
)


def project_containment_is_within(candidate: str, container: Path) -> Path:
    return Path(realpath(candidate)).relative_to(container)  # EXPECT-HIT


def worktree_enclosing_checkout(absolute: Path, root: Path) -> bool:
    return absolute.is_relative_to(root)  # EXPECT-HIT


def plugin_advisor_under(path: Path, directory: Path) -> bool:
    return path.is_relative_to(directory.resolve())  # EXPECT-HIT


def workspace_contains(root: Path, candidate: Path) -> bool:
    return root in candidate.parents  # EXPECT-HIT


def not_under(root: Path, candidate: Path) -> bool:
    return root not in candidate.parents  # EXPECT-HIT


def unbound_method(path: Path, root: Path) -> bool:
    return Path.is_relative_to(path, root)  # EXPECT-HIT


def chained_parts(path: Path, root: Path) -> tuple[str, ...]:
    return path.resolve().relative_to(root.resolve()).parts  # EXPECT-HIT


def linear_is_relative_to(path: Path, root: Path) -> bool:
    return path_is_relative_to(path, root)  # EXPECT-CLEAN


def linear_relative_to(path: Path, root: Path) -> Path:
    return path_relative_to(path, root)  # EXPECT-CLEAN


def module_qualified(path: Path, root: Path) -> Path:
    return path_containment.path_relative_to(path, root)  # EXPECT-CLEAN


def walking_parents_to_probe(start: Path) -> Path | None:
    for candidate in start.parents:  # EXPECT-CLEAN
        if (candidate / ".git").exists():
            return candidate
    return None


def membership_in_something_else(root: Path, roots: list[Path]) -> bool:
    return root in roots  # EXPECT-CLEAN
