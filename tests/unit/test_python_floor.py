"""One declared minimum Python, checked at every entry point (Plan 00546 Task 2.1).

``python_floor.py`` declares the minimum once. Each entry point an arbitrary
interpreter can start -- ``daemon/paths.py``, ``daemon/signal_standalone.py``,
``install.py`` and the package itself (``-m``) -- calls it, so an interpreter
below the minimum gets ONE line naming what it is and what is needed, and a
non-zero exit, never a traceback.

The subprocess tests need a real interpreter below the minimum. They look for
3.8 and 3.9 (``python3.N`` on PATH, else ``uv python find``) and skip when none
is present; the in-process tests below them run everywhere.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from claude_code_hooks_daemon import python_floor
from tests.old_python import OLD_VERSIONS, old_python_or_skip

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
PACKAGE = SRC / "claude_code_hooks_daemon"
FLOOR_SCRIPT = PACKAGE / "python_floor.py"


def _requires_python_minimum() -> tuple[int, int]:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^requires-python\s*=\s*">=(\d+)\.(\d+)"', text, re.MULTILINE)
    assert match is not None, "pyproject.toml has no simple '>=X.Y' requires-python"
    return int(match.group(1)), int(match.group(2))


class TestTheMinimumIsDeclaredOnce:
    def test_matches_pyproject_requires_python(self) -> None:
        assert python_floor.MIN_PYTHON == _requires_python_minimum()

    def test_no_entry_point_repeats_the_minimum_as_a_literal(self) -> None:
        """The old ``_MIN_PYTHON = (3, 8)`` shape must not come back."""
        for path in (
            PACKAGE / "daemon" / "signal_standalone.py",
            PACKAGE / "daemon" / "paths.py",
            REPO_ROOT / "install.py",
            REPO_ROOT / "bin" / "hooks-daemon",
        ):
            text = path.read_text(encoding="utf-8")
            assert "_MIN_PYTHON" not in text, path
            assert "(3, 8)" not in text, path
            assert "python_floor" in text, f"{path} does not call the shared guard"


class TestRequireMinPython:
    def test_returns_quietly_at_the_minimum(self, capsys: pytest.CaptureFixture[str]) -> None:
        python_floor.require_min_python("x.py", (*python_floor.MIN_PYTHON, 0))

        assert capsys.readouterr().err == ""

    def test_returns_quietly_above_the_minimum(self, capsys: pytest.CaptureFixture[str]) -> None:
        python_floor.require_min_python("x.py", (4, 0, 0))

        assert capsys.readouterr().err == ""

    def test_refuses_an_older_interpreter_with_one_line(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as raised:
            python_floor.require_min_python("daemon/paths.py", (3, 9, 25))

        assert raised.value.code == 1
        err = capsys.readouterr().err
        assert len(err.splitlines()) == 1
        assert "daemon/paths.py" in err
        assert "3.9.25" in err
        assert ".".join(str(p) for p in python_floor.MIN_PYTHON) in err


class TestRealOldInterpreters:
    """Each entry point, run for real under an interpreter below the minimum."""

    @staticmethod
    def _assert_one_clear_line(result: subprocess.CompletedProcess[str], found: str) -> None:
        assert result.returncode != 0
        assert "Traceback" not in result.stderr, result.stderr
        lines = [line for line in result.stderr.splitlines() if line.strip()]
        assert len(lines) == 1, result.stderr
        assert found in lines[0]
        assert ".".join(str(p) for p in python_floor.MIN_PYTHON) in lines[0]

    @staticmethod
    def _run(python: str, *argv: str) -> subprocess.CompletedProcess[str]:
        # No -I: it would drop PYTHONPATH, which the -m forms rely on.
        return subprocess.run(
            [python, *argv],
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO_ROOT,
            env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(SRC)},
        )

    @pytest.mark.parametrize("version", OLD_VERSIONS)
    @pytest.mark.parametrize(
        "argv",
        [
            pytest.param(
                ("src/claude_code_hooks_daemon/daemon/paths.py", "list-stale-venvs"),
                id="paths-script",
            ),
            pytest.param(
                ("src/claude_code_hooks_daemon/daemon/signal_standalone.py", "reboot-cancelled"),
                id="signal-script",
            ),
            pytest.param(("install.py", "--help"), id="install-script"),
            pytest.param(
                ("-m", "claude_code_hooks_daemon.daemon.paths", "list-stale-venvs"),
                id="paths-module",
            ),
            pytest.param(
                ("-m", "claude_code_hooks_daemon.daemon.signal_standalone", "reboot-cancelled"),
                id="signal-module",
            ),
            pytest.param(("-m", "claude_code_hooks_daemon.daemon.cli", "status"), id="cli-module"),
            pytest.param(("src/claude_code_hooks_daemon/python_floor.py", "probe"), id="floor"),
        ],
    )
    def test_an_old_interpreter_gets_one_line_and_a_nonzero_exit(
        self, version: str, argv: tuple[str, ...]
    ) -> None:
        python = old_python_or_skip(version)

        result = self._run(python, *argv)

        self._assert_one_clear_line(result, version)

    def test_the_floor_script_passes_under_the_running_interpreter(self) -> None:
        result = subprocess.run(
            [sys.executable, str(FLOOR_SCRIPT), "probe"],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
