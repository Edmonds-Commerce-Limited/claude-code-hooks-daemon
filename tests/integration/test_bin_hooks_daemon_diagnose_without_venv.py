"""``bin/hooks-daemon diagnose`` works with no usable venv and no daemon (Plan 00555 Task 2.5).

The Python CLI has no ``diagnose`` verb and cannot: it is needed exactly when no
interpreter can import the package. The wrapper therefore answers it itself,
ahead of venv resolution, by running the stdlib-only ``paths.py diagnose-venv``
under each venv's own interpreter and adding the last build record and the
daemon's pid/socket state. It is read-only.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.venv_bootstrap_sandbox import Sandbox, snapshot

_RUNNING = (sys.version_info.major, sys.version_info.minor)
_OTHER = (_RUNNING[0], _RUNNING[1] + 1)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_WRAPPER_COPIES = (
    _REPO_ROOT / "bin" / "hooks-daemon",
    _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "install" / "templates" / "hooks-daemon",
)


@pytest.fixture
def sandbox(tmp_path: Path) -> Iterator[Sandbox]:
    box = Sandbox(tmp_path)
    yield box
    box.cleanup()


def _venv(venv_dir: Path, cfg_version: tuple[int, int]) -> Path:
    """A venv whose interpreter is the running one and whose cfg says ``cfg_version``."""
    (venv_dir / "bin").mkdir(parents=True)
    (venv_dir / "bin" / "python").symlink_to(os.path.realpath(sys.executable))
    (venv_dir / "pyvenv.cfg").write_text(
        f"home = {Path(os.path.realpath(sys.executable)).parent}\n"
        f"version_info = {cfg_version[0]}.{cfg_version[1]}.5\n"
    )
    site = venv_dir / "lib" / f"python{_RUNNING[0]}.{_RUNNING[1]}" / "site-packages"
    (site / "claude_code_hooks_daemon").mkdir(parents=True)
    (site / "claude_code_hooks_daemon" / "__init__.py").write_text("")
    return venv_dir


class TestDriftedVenv:
    def test_names_the_drift_prints_the_fix_and_exits_nonzero(self, sandbox: Sandbox) -> None:
        _venv(sandbox.clone / "untracked" / "venv-drifted", _OTHER)

        result = sandbox.wrapper("diagnose")

        output = result.stdout + result.stderr
        assert result.returncode not in (0, 5), output
        assert f"drift: pyvenv.cfg records {_OTHER[0]}.{_OTHER[1]}" in output
        assert f"{sandbox.clone}/bin/hooks-daemon repair" in output
        assert "daemon: not running" in output

    def test_reports_the_last_build_and_its_log(self, sandbox: Sandbox) -> None:
        _venv(sandbox.clone / "untracked" / "venv-drifted", _OTHER)
        (sandbox.clone / "untracked" / ".venv-bootstrap.result").write_text(
            "result=failed\nfinished_at=2026-10-31T01:02:03Z\nlog=/tmp/build-xyz.log\n"
        )

        output = (r := sandbox.wrapper("diagnose")).stdout + r.stderr

        assert "Last venv build: failed at 2026-10-31T01:02:03Z" in output
        assert "Build log: /tmp/build-xyz.log" in output


class TestHealthyVenv:
    def test_exits_zero(self, sandbox: Sandbox) -> None:
        _venv(sandbox.clone / "untracked" / "venv-ok", _RUNNING)

        result = sandbox.wrapper("diagnose")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "claude_code_hooks_daemon importable: yes" in result.stdout + result.stderr

    def test_reads_a_live_pid_without_changing_anything(self, sandbox: Sandbox) -> None:
        _venv(sandbox.clone / "untracked" / "venv-ok", _RUNNING)
        sandbox.pid.write_text(f"{os.getpid()}\n")
        before = snapshot(sandbox.clone)

        result = sandbox.wrapper("diagnose")

        assert f"daemon: running (pid {os.getpid()})" in result.stdout + result.stderr
        assert snapshot(sandbox.clone) == before


class TestNoVenv:
    def test_prints_the_build_record_and_the_fix(self, sandbox: Sandbox) -> None:
        (sandbox.clone / "untracked" / ".venv-bootstrap.result").write_text(
            "result=failed\nfinished_at=2026-10-31T01:02:03Z\nlog=/tmp/build-xyz.log\n"
        )

        result = sandbox.wrapper("diagnose")

        output = result.stdout + result.stderr
        assert result.returncode not in (0, 5), output
        assert "no venv found" in output
        assert "Last venv build: failed at 2026-10-31T01:02:03Z" in output
        assert f"{sandbox.clone}/bin/hooks-daemon repair" in output

    def test_found_past_global_options(self, sandbox: Sandbox) -> None:
        result = sandbox.wrapper("--project-root", str(sandbox.project), "diagnose")

        assert "no venv found" in result.stdout + result.stderr


def test_wrapper_and_template_stay_identical() -> None:
    first, second = (path.read_bytes() for path in _WRAPPER_COPIES)
    assert first == second
