"""init.sh names each daemon-down state on the status line (Plan 00488, GitHub #72).

With the status-line forwarder exiting 0 on its daemon-down branch, the text it
prints is what the human sees for the whole outage. ``init.sh`` already knew
four states (not provisioned, version mismatch, venv building, venv missing)
but named only the first, so the others would read as the generic
``DAEMON FAILED`` -- a misdescription of a normal, self-healing state.

Each test drives the real ``ensure_daemon`` into one state and asserts on
``_HOOKS_DAEMON_STATUS_DOWN_TEXT``, the variable the forwarder prints.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from tests.integration.test_init_sh_stale_clone_version import _project, _run
from tests.venv_bootstrap_sandbox import BASH, Sandbox

#: A status bar is one short line.
_MAX_STATUS_TEXT_LENGTH: Final[int] = 80

_PROBE: Final[str] = """\
_is_ci_environment() { return 1; }
_is_ci_enforced() { return 1; }
if ensure_daemon; then
    echo "DOWN_TEXT=<daemon came up>"
else
    echo "DOWN_TEXT=$_HOOKS_DAEMON_STATUS_DOWN_TEXT"
fi
"""


@pytest.fixture
def sandbox(tmp_path: Path) -> Iterator[Sandbox]:
    box = Sandbox(tmp_path)
    yield box
    box.cleanup()


def _down_text(sandbox: Sandbox) -> str:
    init_sh = sandbox.project / ".claude" / "init.sh"
    result = sandbox.run([BASH, "-c", f'source "{init_sh}"\n{_PROBE}'])
    assert result.returncode == 0, result.stderr
    lines = [ln for ln in result.stdout.splitlines() if ln.startswith("DOWN_TEXT=")]
    assert len(lines) == 1, result.stdout
    return lines[0].removeprefix("DOWN_TEXT=")


def _assert_status_bar_sized(text: str) -> None:
    assert text, "the state must name itself"
    assert "\n" not in text
    assert len(text) <= _MAX_STATUS_TEXT_LENGTH, text


class TestVenvBuilding:
    def test_the_first_hook_that_starts_the_build_says_building(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv(sleep=3)

        text = _down_text(sandbox)

        _assert_status_bar_sized(text)
        assert "BUILDING" in text, text
        sandbox.wait_for_build()

    def test_a_hook_during_the_build_says_building(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv(sleep=3)
        _down_text(sandbox)

        text = _down_text(sandbox)

        assert "BUILDING" in text, text
        sandbox.wait_for_build()


class TestVenvMissingWithNoSelfHeal:
    def test_a_refused_build_says_venv_missing_not_building(self, sandbox: Sandbox) -> None:
        # No uv on PATH: the driver refuses and changes nothing.
        text = _down_text(sandbox)

        _assert_status_bar_sized(text)
        assert "VENV MISSING" in text, text
        assert "BUILDING" not in text

    def test_a_failed_build_says_venv_missing(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv(fail=True)
        _down_text(sandbox)
        sandbox.wait_for_build()

        text = _down_text(sandbox)

        assert "VENV MISSING" in text, text

    def test_an_orphan_venv_without_a_clone_says_venv_missing(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        sandbox.other_view_venv()
        (sandbox.clone / "scripts" / "lib" / "resolve_venv.sh").unlink()

        text = _down_text(sandbox)

        _assert_status_bar_sized(text)
        assert "VENV MISSING" in text, text


class TestVersionMismatch:
    def test_a_stale_clone_says_version_mismatch(self, tmp_path: Path) -> None:
        result: subprocess.CompletedProcess[str] = _run(
            _project(tmp_path),
            "is_daemon_running() { return 1; }\n"
            "start_daemon() { return 1; }\n"
            "_is_ci_environment() { return 1; }\n"
            "_is_ci_enforced() { return 1; }\n"
            "_is_daemon_installed() { return 0; }\n"
            "if ! ensure_daemon; then :; fi\n"
            'echo "DOWN_TEXT=$_HOOKS_DAEMON_STATUS_DOWN_TEXT"',
        )

        lines = [ln for ln in result.stdout.splitlines() if ln.startswith("DOWN_TEXT=")]
        assert len(lines) == 1, result.stdout + result.stderr
        text = lines[0].removeprefix("DOWN_TEXT=")
        _assert_status_bar_sized(text)
        assert "VERSION MISMATCH" in text, text
