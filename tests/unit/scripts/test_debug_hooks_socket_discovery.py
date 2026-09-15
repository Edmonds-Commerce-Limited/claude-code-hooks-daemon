"""Socket discovery in ``scripts/debug_hooks.sh`` — Plan 00419 N1 (RED first).

Three documents route an agent to ``debug_hooks.sh`` as the sanctioned
alternative to guessing at a hook payload's shape: ``CLAUDE/DEBUGGING_HOOKS.md``,
``CLAUDE/HANDLER_DEVELOPMENT.md``'s "debug first", and Plan 00418's Task 1.1.
The script could not work in THIS repository, which is the one that dogfoods it.

Two independent defects, tested separately on purpose. A test covering only the
crash would pass against a script that still searches the wrong directory and
silently finds nothing — and a test covering only the layout would pass against
a script that dies before it reports anything.

These tests read the script's own source and exercise its discovery logic in a
real shell, rather than importing anything: the defect lives in shell semantics
(``set -e`` plus ``pipefail`` plus command substitution), which no Python-level
test could observe.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout

#: Ceiling for the discovery snippet's own shell run. The snippet does one
#: `find` over a tmp_path holding at most one file, so this is a wedged-shell
#: guard rather than a budget -- if it is ever approached, failing is right.
_SHELL_TIMEOUT = Timeout.VALIDATION_CHECK

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "debug_hooks.sh"


def _discovery_snippet() -> str:
    """The script's socket-discovery lines, up to the first usability check.

    Extracted rather than hardcoded so the test tracks the script: if the
    discovery block is rewritten, this follows it.
    """
    lines = _SCRIPT.read_text().splitlines()
    start = next(
        i
        for i, line in enumerate(lines)
        if "daemon socket" in line and line.lstrip().startswith("#")
    )
    end = next(
        i for i, line in enumerate(lines[start:], start) if 'if [[ ! -f "$VENV_PYTHON"' in line
    )
    return "\n".join(lines[start:end])


class TestSelfInstallLayoutIsFound:
    """Defect 1: the script searched only the CLIENT-install layout.

    In self-install mode the daemon IS the project, and its sockets live at
    ``<project_root>/untracked/``. ``<project_root>/.claude/hooks-daemon/``
    does not exist at all here.
    """

    def test_script_searches_the_self_install_socket_directory(self) -> None:
        source = _SCRIPT.read_text()

        assert '"$PROJECT_ROOT/untracked/"' in source or "$PROJECT_ROOT/untracked" in source, (
            "debug_hooks.sh never looks in the self-install socket location, so it "
            "cannot find a socket in this repository"
        )

    def test_finds_a_socket_in_the_self_install_location(self, tmp_path: Path) -> None:
        project_root = tmp_path / "proj"
        (project_root / "untracked").mkdir(parents=True)
        socket = project_root / "untracked" / "daemon-abc123.sock"
        socket.touch()

        script = f'set -euo pipefail\nPROJECT_ROOT="{project_root}"\n{_discovery_snippet()}\necho "FOUND:$SOCKET_PATH"\n'
        result = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, timeout=_SHELL_TIMEOUT
        )

        assert result.returncode == 0, f"discovery died: {result.stderr}"
        assert str(socket) in result.stdout, (
            f"self-install socket not discovered; got: {result.stdout!r}"
        )


class TestMissingDirectoryIsNotFatal:
    """Defect 2: it died before reaching its own fallback.

    ``find`` on a missing directory exits 1; ``pipefail`` carries that through
    ``head``'s success; the ASSIGNMENT therefore fails and ``set -e`` kills the
    script — before the ``CLAUDE_HOOKS_SOCKET_PATH`` fallback below it.

    The assignment form is load-bearing. Running the same pipeline bare reaches
    the next line and exits 0, so a reproduction that drops the assignment
    concludes there is no bug.
    """

    def test_absent_socket_directories_do_not_kill_the_script(self, tmp_path: Path) -> None:
        project_root = tmp_path / "nothing-here"
        project_root.mkdir()

        script = (
            f'set -euo pipefail\nPROJECT_ROOT="{project_root}"\n'
            f"{_discovery_snippet()}\n"
            'echo "REACHED_END"\n'
        )
        result = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, timeout=_SHELL_TIMEOUT
        )

        # The script SHOULD reach its own "no socket found" branch and exit 1
        # with a readable message. What it must never do is die inside the
        # search with no output at all, which is what set -e produced.
        assert "No daemon socket found" in result.stdout, (
            "the script died inside socket discovery instead of reaching its own "
            f"error path (rc={result.returncode}, out={result.stdout!r}, "
            f"stderr={result.stderr!r})"
        )

    def test_env_override_is_reachable_when_no_directory_exists(self, tmp_path: Path) -> None:
        """The fallback five lines below the search must actually be reachable."""
        project_root = tmp_path / "nothing-here"
        project_root.mkdir()
        override = tmp_path / "elsewhere" / "daemon-override.sock"
        override.parent.mkdir()
        override.touch()

        script = (
            f'set -euo pipefail\nPROJECT_ROOT="{project_root}"\n'
            f'export CLAUDE_HOOKS_SOCKET_PATH="{override}"\n'
            f"{_discovery_snippet()}\n"
            'echo "FOUND:$SOCKET_PATH"\n'
        )
        result = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, timeout=_SHELL_TIMEOUT
        )

        assert str(override) in result.stdout, (
            "CLAUDE_HOOKS_SOCKET_PATH is documented as the escape hatch but is "
            f"unreachable; got rc={result.returncode}, out={result.stdout!r}"
        )


class TestBothLayoutsStillWork:
    """The fix must not trade one layout for the other."""

    def test_client_install_layout_is_still_found(self, tmp_path: Path) -> None:
        project_root = tmp_path / "client"
        nested = project_root / ".claude" / "hooks-daemon" / "untracked"
        nested.mkdir(parents=True)
        socket = nested / "daemon.sock"
        socket.touch()

        script = f'set -euo pipefail\nPROJECT_ROOT="{project_root}"\n{_discovery_snippet()}\necho "FOUND:$SOCKET_PATH"\n'
        result = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, timeout=_SHELL_TIMEOUT
        )

        assert result.returncode == 0, f"discovery died: {result.stderr}"
        assert str(socket) in result.stdout, (
            f"client-install socket no longer discovered; got: {result.stdout!r}"
        )


@pytest.mark.parametrize("suppressor", ["|| true", "|| :"])
def test_fix_does_not_reach_for_error_suppression(suppressor: str) -> None:
    """``|| true`` is the shape this project blocks; an explicit test says what is meant."""
    assert suppressor not in _SCRIPT.read_text(), (
        f"socket discovery uses {suppressor!r} to dodge set -e; use an explicit "
        "directory test instead so the intent is readable"
    )
