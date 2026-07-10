"""Tests for the standalone claude-supervise.py `main()`."""

from __future__ import annotations

import os
import subprocess  # nosec B404 - trusted, args-list only, no shell
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.unit.supervise._load import SCRIPT_PATH, load_supervisor_module

if TYPE_CHECKING:
    from collections.abc import Iterator

_mod = load_supervisor_module()
main = _mod.main
_resolve_decision_log = _mod._resolve_decision_log
DecisionLog = _mod.DecisionLog

_SUBPROCESS_TIMEOUT_SECONDS = 10


@pytest.fixture(autouse=True)
def _real_stdin_with_fileno(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give `sys.stdin` a real fileno() for the duration of each test.

    Pytest's captured stdin has no `fileno()`, but `supervise()` needs a real
    fd to select() on. A /dev/null file object supplies one without requiring
    a real controlling terminal.
    """
    devnull = Path(os.devnull).open(encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", devnull)
    yield
    devnull.close()


class TestMainUsage:
    """Argument parsing and usage errors."""

    def test_no_child_argv_returns_usage_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["--"])

        assert exit_code == 2
        captured = capsys.readouterr()
        assert "usage" in captured.err.lower()

    def test_missing_separator_returns_usage_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main([])

        assert exit_code == 2
        captured = capsys.readouterr()
        assert "usage" in captured.err.lower()


class TestMainExecution:
    """Full execution through main(), including exit-code propagation."""

    def test_runs_child_and_propagates_exit_code(
        self, tmp_path: Path, capfd: pytest.CaptureFixture[str]
    ) -> None:
        log_path = tmp_path / "decision.log"

        exit_code = main(
            ["--log", str(log_path), "--", "bash", "-lc", "printf 'MAIN_OUT\\n'; exit 7"]
        )

        assert exit_code == 7
        assert "MAIN_OUT" in capfd.readouterr().out
        assert log_path.exists()

    def test_arm_flag_is_accepted(self, tmp_path: Path) -> None:
        """--arm parses and runs; the fast child exits before any poll tick fires."""
        log_path = tmp_path / "decision.log"

        exit_code = main(["--arm", "--log", str(log_path), "--", "bash", "-lc", "exit 0"])

        assert exit_code == 0


class TestResolveDecisionLogDefaultPath:
    """`_resolve_decision_log(None)` derives its path from the environment."""

    def test_uses_claude_project_dir_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

        log = _resolve_decision_log(None)

        assert log.path == tmp_path / "untracked" / "supervise" / "decision.log"

    def test_explicit_path_bypasses_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "other"))
        explicit = tmp_path / "explicit" / "decision.log"

        log = _resolve_decision_log(explicit)

        assert log.path == explicit


class TestNoDaemonImport:
    """The standalone script must never import the hooks-daemon package."""

    def test_module_has_no_claude_code_hooks_daemon_import_statement(self) -> None:
        source_lines = SCRIPT_PATH.read_text(encoding="utf-8").splitlines()
        import_lines = [
            line for line in source_lines if line.startswith("import ") or line.startswith("from ")
        ]
        assert not any("claude_code_hooks_daemon" in line for line in import_lines)


class TestSystemPythonRuntime:
    """The script must run clean under the container's system python3 (no venv)."""

    def test_runs_under_system_python3_with_no_runtime_warning(self) -> None:
        result = subprocess.run(  # nosec B603 - fixed argv list, no shell
            [
                "/usr/bin/python3",
                str(SCRIPT_PATH),
                "--",
                "echo",
                "SUPERVISED_OK",
            ],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )

        assert result.returncode == 0
        assert "SUPERVISED_OK" in result.stdout
        assert "RuntimeWarning" not in result.stderr

    def test_usage_error_exits_two_under_system_python3(self) -> None:
        result = subprocess.run(  # nosec B603 - fixed argv list, no shell
            ["/usr/bin/python3", str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )

        assert result.returncode == 2
        assert "usage" in result.stderr.lower()
