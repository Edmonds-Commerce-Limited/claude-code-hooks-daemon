"""Guard: no code path reads the installed daemon version from venv metadata (Plan 00517).

The installed version is the installed source tree's ``version.py``
(``utils.deployed_version.read_installed_source_version``). A venv's
``.daemon-metadata.json`` ``daemon_version`` records which daemon built the
venv. The only consumer of the Pydantic metadata reader is the metadata module
itself; a new caller has to be added here on purpose, with a reason.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[3] / "src" / "claude_code_hooks_daemon"

_READER = "read_daemon_metadata"

#: Modules allowed to use the metadata reader, with why.
_ALLOWED = {
    "daemon/metadata.py": "defines the reader",
}


def _uses_reader(path: Path) -> bool:
    """Whether the module imports or references the reader in code (docstrings do not count)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(a.name == _READER for a in node.names):
            return True
        if isinstance(node, ast.Name) and node.id == _READER:
            return True
        if isinstance(node, ast.Attribute) and node.attr == _READER:
            return True
    return False


def test_only_the_metadata_module_uses_the_metadata_reader() -> None:
    offenders = sorted(
        str(path.relative_to(_SRC))
        for path in _SRC.rglob("*.py")
        if str(path.relative_to(_SRC)) not in _ALLOWED and _uses_reader(path)
    )
    assert offenders == [], (
        f"{offenders} read venv metadata; the installed version comes from "
        "read_installed_source_version, not from a venv's recorded daemon_version"
    )
