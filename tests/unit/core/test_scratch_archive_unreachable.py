"""Only the ``scratch-sweep`` CLI reaches the archive modules (Plan 00627 Task 3.8).

The archive, claim, pack, removal and apply modules can delete from a scratch
root. Their one entry point is ``daemon/cli.py`` (``scratch-sweep --apply``,
``restore``, ``keep``); no handler, hook or other module may import or name
them, so the deleting path cannot be reached without the explicit command. The
flag surface itself is pinned in ``tests/unit/daemon/test_cli_scratch_apply.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import claude_code_hooks_daemon

_PACKAGE = Path(claude_code_hooks_daemon.__file__).parent

#: Every module outside ``core/scratch_archive*`` allowed to import or name them.
ALLOWED = ["daemon/cli.py"]


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


def _naming_modules() -> list[str]:
    found = []
    for path in sorted(_PACKAGE.rglob("*.py")):
        if _is_archive_module(path):
            continue
        text = path.read_text(encoding="utf-8")
        names = _imported(ast.parse(text))
        if any("scratch_archive" in name for name in names) or "scratch_archive" in text:
            found.append(path.relative_to(_PACKAGE).as_posix())
    return found


def test_only_the_cli_imports_or_names_archive_modules() -> None:
    assert _naming_modules() == ALLOWED


def test_the_cli_reaches_the_apply_module() -> None:
    names = _imported(ast.parse((_PACKAGE / "daemon" / "cli.py").read_text(encoding="utf-8")))
    assert "claude_code_hooks_daemon.core.scratch_archive_apply" in names
