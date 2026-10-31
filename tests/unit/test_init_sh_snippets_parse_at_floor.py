"""Every allowlisted ``python3`` snippet in ``init.sh`` is checked at the 3.6 floor (Plan 00546 Task 3.1).

``scripts/qa/bare-python-allowlist.json`` lets the hook forwarder run a bare
``python3`` because no resolved interpreter exists there. That is only safe if
whatever ``python3`` the host has, down to the oldest anyone runs, can parse and
run the snippet. ``uv`` offers nothing below 3.8, so the floor below that is
proven statically, on every host, with no interpreter:

* each snippet body is extracted from ``init.sh`` at the lines the allowlist
  names, with the shell's own substitutions applied, and must
  ``ast.parse(..., feature_version=FORWARDER_PYTHON_FLOOR)``;
* its imports must stay inside :data:`ALLOWED_IMPORTS`.

Limit: ``feature_version`` rejects grammar the floor lacks (walrus,
positional-only parameters, ``async`` as a name). It does not reject library
APIs added later (``shlex.join``, ``str.removeprefix``), which is why the import
set is asserted too and why the 3.8 and 3.9 runtime tests still run.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.old_python import FORWARDER_PYTHON_FLOOR

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = REPO_ROOT / "scripts" / "qa" / "bare-python-allowlist.json"
INIT_SH = REPO_ROOT / "init.sh"

#: The only modules a no-venv snippet may import; all exist on the 3.6 floor.
# fnmatch (protected-path globs) and time (daemon-down stop log stamp) are
# stdlib and present at the floor.
ALLOWED_IMPORTS = frozenset({"fnmatch", "json", "os", "shlex", "socket", "sys", "time"})

_RECOVERY_PY_OPEN = "_hooks_daemon_recovery_py() {"
_SHELL_VARIABLE = re.compile(r"\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*")
_DOUBLE_QUOTE_ESCAPE = re.compile(r'\\(["\\$`])')


@dataclass(frozen=True)
class Snippet:
    """One allowlisted invoking line and the Python source it runs."""

    line_number: int
    source: str


def _recovery_source(lines: list[str]) -> str:
    """The text ``_hooks_daemon_recovery_py`` assigns (a single-quoted shell string)."""
    start = lines.index(_RECOVERY_PY_OPEN)
    opener = next(i for i in range(start, len(lines)) if lines[i].endswith("'%s' '"))
    closer = next(i for i in range(opener + 1, len(lines)) if lines[i].startswith("'"))
    return "\n".join(lines[opener + 1 : closer]) + "\n"


def _body_after(lines: list[str], index: int, quote: str) -> str:
    closer = next(i for i in range(index + 1, len(lines)) if lines[i].startswith(quote))
    return "\n".join(lines[index + 1 : closer]) + "\n"


def _snippet_source(lines: list[str], index: int, recovery: str) -> str:
    line = lines[index]
    if "-c 'import sys" in line:
        return line.split("-c '", 1)[1].rsplit("')", 1)[0]
    if line.endswith('"$recovery_py"\''):
        return recovery + _body_after(lines, index, "'")
    if line.endswith("-c '"):
        return _body_after(lines, index, "'")
    assert line.endswith('-c "'), f"unrecognised invoking line shape: {line!r}"
    body = _body_after(lines, index, '"')
    body = body.replace("$_recovery_py", recovery)
    body = _SHELL_VARIABLE.sub("0", body)
    return _DOUBLE_QUOTE_ESCAPE.sub(r"\1", body)


def _init_sh_snippets() -> list[Snippet]:
    entries = json.loads(ALLOWLIST.read_text(encoding="utf-8"))["entries"]
    lines = INIT_SH.read_text(encoding="utf-8").splitlines()
    recovery = _recovery_source(lines)
    snippets: list[Snippet] = []
    for entry in entries:
        if entry["file"] != "init.sh":
            continue
        indices = [i for i, line in enumerate(lines) if line.rstrip() == entry["line"]]
        for index in indices:
            snippets.append(Snippet(index + 1, _snippet_source(lines, index, recovery)))
    return snippets


SNIPPETS = _init_sh_snippets()


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def test_every_allowlisted_init_sh_line_was_extracted() -> None:
    entries = json.loads(ALLOWLIST.read_text(encoding="utf-8"))["entries"]
    expected = sum(e.get("occurrences", 1) for e in entries if e["file"] == "init.sh")
    assert len(SNIPPETS) == expected == 10


def test_the_floor_check_rejects_newer_grammar() -> None:
    with pytest.raises(SyntaxError):
        ast.parse("if (n := 1):\n    pass\n", feature_version=FORWARDER_PYTHON_FLOOR)


@pytest.mark.parametrize("snippet", SNIPPETS, ids=lambda s: f"init.sh:{s.line_number}")
class TestSnippetAtTheFloor:
    def test_parses_at_the_floor(self, snippet: Snippet) -> None:
        assert "sys" in snippet.source, "extraction produced no real Python body"
        ast.parse(snippet.source, feature_version=FORWARDER_PYTHON_FLOOR)

    def test_imports_stay_in_the_declared_set(self, snippet: Snippet) -> None:
        tree = ast.parse(snippet.source, feature_version=FORWARDER_PYTHON_FLOOR)
        assert _imported_modules(tree) <= ALLOWED_IMPORTS
