"""Runtime strings never name the bare self-install wrapper (issue #147, part 3).

A client install keeps the wrapper at ``.claude/hooks-daemon/bin/hooks-daemon`` and has no
root ``bin/``. Output that names ``bin/hooks-daemon`` is wrong there, so runtime text must be
built with ``daemon_cli_command_for_docs``. This scan keeps the conversions from regrowing:
every string constant under ``src/`` that holds the bare spelling must be listed below with
the reason it is deliberate.
"""

import ast
import re
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src" / "claude_code_hooks_daemon"
_BARE = re.compile(
    r"(?<!\.claude/hooks-daemon/)(?<!\{daemon_path\}/)(?<!\{daemon_dir\}/)bin/hooks-daemon"
)

#: Relative path (under the package) -> why its bare ``bin/hooks-daemon`` strings are deliberate.
_ALLOWED: dict[str, str] = {
    "core/hook_result.py": "recovery carve-out names both spellings on purpose",
    "core/project_context.py": "the self-install symlink target is the root wrapper by definition",
    "daemon/paths.py": "repair hints are built from an explicit daemon directory, not the root",
    "install/forwarder_generator.py": "generated shell messages; no Python mode is available",
    "issue_report/reproduction.py": "list of launcher spellings the reproduction scrubber knows",
    "config/models.py": "provenance label recorded in generated config docs",
}


def _bare_string_files() -> dict[str, list[int]]:
    """Package-relative path -> line numbers of non-docstring string constants naming the wrapper."""
    found: dict[str, list[int]] = {}
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            id(node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        }
        lines = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
            and _BARE.search(node.value)
        ]
        if lines:
            found[path.relative_to(_SRC).as_posix()] = lines
    return found


def test_no_unlisted_runtime_string_names_the_bare_wrapper() -> None:
    """Only the allowlisted modules hold a bare ``bin/hooks-daemon`` string constant."""
    unlisted = {f: ln for f, ln in _bare_string_files().items() if f not in _ALLOWED}
    assert unlisted == {}, (
        "runtime strings name the self-install wrapper; build them with "
        "daemon_cli_command_for_docs or add a reasoned entry to _ALLOWED"
    )


@pytest.mark.parametrize("module", sorted(_ALLOWED))
def test_every_allowlist_entry_still_needs_its_exemption(module: str) -> None:
    """A stale allowlist entry is removed rather than left to hide a regrowth."""
    assert module in _bare_string_files(), f"{module} no longer holds a bare wrapper string"
