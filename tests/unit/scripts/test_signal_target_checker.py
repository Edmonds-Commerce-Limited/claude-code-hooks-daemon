"""The `signal-target` Detector — Plan 00466 N59 (Defence Before Fix, RED first).

The class: **a nonzero signal sent to a pid nobody proved is the intended process.**

A unit test's ``MagicMock`` Popen had a pid that coerces to 1, and
``os.killpg(os.getpgid(process.pid), SIGKILL)`` killed the container's init
twice. ``install/client_validator.py`` sent SIGTERM then SIGKILL to a raw pid
read from a PID file, which survives a container restart and can name any
process a restarted container reused that pid for.

A pid is proven only two ways: it came from ``read_pid_file(...,
verify_daemon=True)``, or the signal goes through
``claude_code_hooks_daemon.utils.safe_signal``, which verifies it. Signal 0
delivers nothing and is exempt. Everything here is source text fed to the
Detector; nothing in this file sends a signal.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHECKER = _REPO_ROOT / "scripts" / "qa" / "check_signal_targets.py"


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    """The Detector, imported from its script path."""
    spec = importlib.util.spec_from_file_location("check_signal_targets", _CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _rules(checker: ModuleType, source: str) -> list[tuple[int, str]]:
    violations = checker.scan_source(textwrap.dedent(source), "fixture.py")
    return [(v.line, v.rule) for v in violations]


class TestTheCrashShapesAreFound:
    def test_n53_killpg_of_getpgid_of_a_popen_pid(self, checker: ModuleType) -> None:
        source = """
            import os, signal, subprocess

            def run_git(argv):
                process = subprocess.Popen(argv)
                try:
                    return process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    raise
        """
        assert _rules(checker, source) == [(9, "raw-signal")]

    def test_client_validator_sigterm_then_sigkill_of_a_pid_file_pid(
        self, checker: ModuleType
    ) -> None:
        source = """
            import os, signal

            def stop(pid_file):
                pid = int(pid_file.read_text().strip())
                os.kill(pid, 0)
                os.kill(pid, signal.SIGTERM)
                os.kill(pid, 0)
                os.kill(pid, signal.SIGKILL)
        """
        assert _rules(checker, source) == [(7, "raw-signal"), (9, "raw-signal")]


class TestEverySpellingOfARawSignalIsFound:
    @pytest.mark.parametrize(
        "source",
        [
            "import os\ndef f(p, s):\n    os.kill(p, s)\n",
            "import os as o\ndef f(p):\n    o.kill(p, 15)\n",
            "from os import kill\ndef f(p):\n    kill(p, 9)\n",
            "from os import killpg as kpg\ndef f(g):\n    kpg(g, 9)\n",
            "import signal\ndef f(t):\n    signal.pthread_kill(t, signal.SIGUSR1)\n",
            "import os\nos.kill(123, 9)\n",
            "import os\ndef f(target):\n    os.kill(*target)\n",
            "import os\ndef f(pid, rest):\n    os.killpg(pid, *rest)\n",
        ],
    )
    def test_is_reported(self, checker: ModuleType, source: str) -> None:
        assert [rule for _, rule in _rules(checker, source)] == ["raw-signal"]

    def test_the_existence_probe_is_exempt(self, checker: ModuleType) -> None:
        source = """
            import os

            def alive(pid):
                os.kill(pid, 0)
                os.killpg(pid, 0)
        """
        assert _rules(checker, source) == []


class TestAPidFromAVerifiedDaemonPidFileIsProven:
    def test_read_pid_file_with_verify_daemon_true(self, checker: ModuleType) -> None:
        source = """
            import os, signal
            from claude_code_hooks_daemon.daemon.paths import read_pid_file

            def stop(path):
                pid = read_pid_file(str(path), verify_daemon=True)
                if pid is None:
                    return
                os.kill(pid, signal.SIGTERM)
        """
        assert _rules(checker, source) == []

    def test_read_pid_file_without_verification_is_not(self, checker: ModuleType) -> None:
        source = """
            import os, signal

            def stop(path):
                pid = read_pid_file(path)
                os.kill(pid, signal.SIGTERM)
        """
        assert _rules(checker, source) == [(6, "raw-signal")]

    def test_a_name_rebound_to_anything_else_is_not(self, checker: ModuleType) -> None:
        source = """
            import os, signal

            def stop(path, other):
                pid = read_pid_file(path, verify_daemon=True)
                if other:
                    pid = other
                os.kill(pid, signal.SIGTERM)
        """
        assert _rules(checker, source) == [(8, "raw-signal")]

    def test_a_parameter_of_the_same_name_is_not(self, checker: ModuleType) -> None:
        source = """
            import os, signal

            def stop(pid):
                os.kill(pid, signal.SIGTERM)

            def elsewhere(path):
                pid = read_pid_file(path, verify_daemon=True)
        """
        assert _rules(checker, source) == [(5, "raw-signal")]


class TestAProcessHandleMustBeProvenBeforeItIsSignalled:
    @pytest.mark.parametrize("method", ["terminate", "kill", "send_signal"])
    def test_a_psutil_process_built_from_a_raw_pid(self, checker: ModuleType, method: str) -> None:
        args = "15" if method == "send_signal" else ""
        source = f"""
            import psutil

            def stop(pid):
                process = psutil.Process(pid)
                process.{method}({args})
        """
        assert _rules(checker, source) == [(6, "unproven-process-handle")]

    def test_a_psutil_process_signalled_inline(self, checker: ModuleType) -> None:
        source = """
            from psutil import Process

            def stop(pid):
                Process(pid).terminate()
        """
        assert _rules(checker, source) == [(5, "unproven-process-handle")]

    def test_a_process_from_process_iter(self, checker: ModuleType) -> None:
        source = """
            import psutil

            def reap():
                for proc in psutil.process_iter():
                    proc.kill()
        """
        assert _rules(checker, source) == [(6, "unproven-process-handle")]

    def test_a_handle_from_the_verifying_helper_is_proven(self, checker: ModuleType) -> None:
        source = """
            from claude_code_hooks_daemon.utils.safe_signal import verified_daemon_process

            def stop(pid, root):
                process = verified_daemon_process(pid, project_root=root)
                process.terminate()
                process.kill()
        """
        assert _rules(checker, source) == []

    def test_a_popen_this_code_spawned_signals_its_own_child(self, checker: ModuleType) -> None:
        source = """
            import signal, subprocess

            def run(argv):
                proc = subprocess.Popen(argv)
                proc.send_signal(signal.SIGTERM)
                proc.terminate()
                proc.kill()
                with subprocess.Popen(argv) as other:
                    other.send_signal(signal.SIGINT)
        """
        assert _rules(checker, source) == []

    def test_send_signal_on_an_unknown_receiver(self, checker: ModuleType) -> None:
        source = """
            import signal

            def stop(handle):
                handle.send_signal(signal.SIGTERM)
                handle.send_signal(0)
        """
        assert _rules(checker, source) == [(5, "unproven-process-handle")]


class TestAKillCommandRunFromPythonIsFound:
    @pytest.mark.parametrize(
        "argv",
        [
            '["kill", "-TERM", str(pid)]',
            '["kill", str(pid)]',
            '("pkill", "-f", pattern)',
            '["killall", "python3"]',
        ],
    )
    def test_is_reported(self, checker: ModuleType, argv: str) -> None:
        source = f"""
            import subprocess

            def stop(pid, pattern):
                subprocess.run({argv}, check=False)
        """
        assert _rules(checker, source) == [(5, "kill-command")]

    def test_kill_zero_is_exempt(self, checker: ModuleType) -> None:
        source = """
            import subprocess

            def alive(pid):
                subprocess.run(["kill", "-0", str(pid)], check=False)
        """
        assert _rules(checker, source) == []


class TestTheHelperIsTheOnePlaceARawSignalIsSent:
    def test_the_helper_module_itself_is_not_reported(self, checker: ModuleType) -> None:
        helper = _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "utils" / "safe_signal.py"
        assert checker.scan_file(helper) == []

    def test_the_same_source_anywhere_else_is_reported(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        helper = _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "utils" / "safe_signal.py"
        copy = tmp_path / "safe_signal.py"
        copy.write_text(helper.read_text(encoding="utf-8"), encoding="utf-8")
        assert checker.scan_file(copy) != []


class TestTheRepository:
    def test_every_scanned_surface_is_covered(self, checker: ModuleType) -> None:
        roots = {path.relative_to(_REPO_ROOT).as_posix() for path in checker.scanned_files()}
        assert "src/claude_code_hooks_daemon/install/client_validator.py" in roots
        assert "scripts/debug_info.py" in roots
        assert ".claude/ccy/claude-supervise.py" in roots

    def test_the_repository_is_clean(self, checker: ModuleType) -> None:
        violations = [v for path in checker.scanned_files() for v in checker.scan_file(path)]
        assert violations == []
