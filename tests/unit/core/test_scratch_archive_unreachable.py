"""No CLI flag reaches the archive modules yet (Plan 00627 Tasks 3.1-3.4).

Task 3.8 wires ``--apply`` after the Task 3.9 review. Until then the archive,
claim, pack and removal modules must be unreachable from every entry point, so
the dry run stays the only reachable behaviour. Two checks: no module outside
``core/scratch_archive*`` imports or names them, and ``scratch-sweep`` has no
flag beyond the dry run's.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

import claude_code_hooks_daemon
from claude_code_hooks_daemon.daemon.cli import build_parser

_PACKAGE = Path(claude_code_hooks_daemon.__file__).parent


def _is_archive_module(path: Path) -> bool:
    return path.parent.name == "core" and path.name.startswith("scratch_archive")


def _imported(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def test_only_archive_modules_import_or_name_archive_modules() -> None:
    offenders = []
    for path in sorted(_PACKAGE.rglob("*.py")):
        if _is_archive_module(path):
            continue
        text = path.read_text(encoding="utf-8")
        names = _imported(ast.parse(text))
        if any("scratch_archive" in name for name in names) or "scratch_archive" in text:
            offenders.append(str(path.relative_to(_PACKAGE)))
    assert offenders == []


def test_scratch_sweep_has_only_dry_run_flags() -> None:
    parser = build_parser()
    subparsers = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    sweep = subparsers[0].choices["scratch-sweep"]
    flags = {opt for action in sweep._actions for opt in action.option_strings}
    assert flags == {"-h", "--help", "--json", "--root", "--budget-seconds", "--max-inodes"}
