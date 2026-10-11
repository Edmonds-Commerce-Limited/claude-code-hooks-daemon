"""The first moments of a venv build read as "building", never as a failure (Plan 00488 Task 3.5).

uv creates the venv's interpreter BEFORE it installs the package. For that
sub-second to few-second window the venv resolves (``bin/python`` exists) yet
``import claude_code_hooks_daemon`` fails, so a hook that arrives then used to
fall past every venv-missing diagnosis into the generic failure: the status line
read ``DAEMON FAILED`` and PreToolUse denied the call. RULING-3.2 says the whole
build window fails open with an announcement, so a held venv build lock must
read as "building" whatever the half-built venv looks like.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.venv_bootstrap_sandbox import BASH, Sandbox


@pytest.fixture
def sandbox(tmp_path: Path) -> Iterator[Sandbox]:
    box = Sandbox(tmp_path)
    yield box
    box.cleanup()


def _write_half_built_python(path: Path) -> None:
    """An interpreter that runs, but whose venv has not had the package installed yet."""
    path.write_text(textwrap.dedent(f"""\
            #!/bin/bash
            case "$*" in
                *claude_code_hooks_daemon*) exit 1 ;;
            esac
            exec "{sys.executable}" "$@"
            """))
    path.chmod(0o755)


def _stub_uv_with_half_built_venv(sandbox: Sandbox, *, hold_seconds: int) -> Path:
    """A uv whose venv has an interpreter that cannot import the package for a while."""
    stub_dir = sandbox.root / "uv-stub"
    stub_dir.mkdir(parents=True, exist_ok=True)
    sandbox.stub_uv()
    real_uv = stub_dir / "uv-complete"
    (stub_dir / "uv").rename(real_uv)
    half_built = sandbox.root / "half-built-python"
    _write_half_built_python(half_built)
    (stub_dir / "uv").write_text(textwrap.dedent(f"""\
            #!/bin/bash
            mkdir -p "$UV_PROJECT_ENVIRONMENT/bin"
            cp "{half_built}" "$UV_PROJECT_ENVIRONMENT/bin/python"
            sleep {hold_seconds}
            exec "{real_uv}" "$@"
            """))
    (stub_dir / "uv").chmod(0o755)
    return stub_dir


def _wait_for_half_built_venv(sandbox: Sandbox) -> None:
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if list((sandbox.clone / "untracked").glob("venv-*/bin/python")):
            return
        time.sleep(0.05)
    raise AssertionError("the stub uv never created the half-built venv")


def _context(result: subprocess.CompletedProcess[str]) -> str:
    assert result.returncode == 0, result.stderr
    return str(json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"])


class TestAHookInTheHalfBuiltVenvWindow:
    def test_reads_as_a_running_build_and_does_not_deny(self, sandbox: Sandbox) -> None:
        _stub_uv_with_half_built_venv(sandbox, hold_seconds=4)
        assert "build has started" in _context(sandbox.hook()).lower()
        _wait_for_half_built_venv(sandbox)

        result = sandbox.hook()

        context = _context(result)
        assert "already running" in context.lower(), context
        assert "permissionDecision" not in result.stdout, result.stdout
        assert "keep to reads and ordinary edits" in context.lower(), context
        sandbox.wait_for_build()

    def test_names_the_building_state_on_the_status_line(self, sandbox: Sandbox) -> None:
        _stub_uv_with_half_built_venv(sandbox, hold_seconds=4)
        sandbox.hook()
        _wait_for_half_built_venv(sandbox)
        init_sh = sandbox.project / ".claude" / "init.sh"

        result = sandbox.run(
            [
                BASH,
                "-c",
                f'source "{init_sh}"\n'
                "_is_ci_environment() { return 1; }\n_is_ci_enforced() { return 1; }\n"
                'ensure_daemon || echo "TEXT=$_HOOKS_DAEMON_STATUS_DOWN_TEXT"',
            ]
        )

        assert "TEXT=⏳ HOOKS DAEMON VENV BUILDING" in result.stdout, result.stdout + result.stderr
        sandbox.wait_for_build()

    def test_a_broken_venv_with_no_build_running_is_still_a_failure(self, sandbox: Sandbox) -> None:
        """Only a HELD build lock earns the "building" reading."""
        _stub_uv_with_half_built_venv(sandbox, hold_seconds=0)
        sandbox.hook()
        sandbox.wait_for_build()
        venv_python = next((sandbox.clone / "untracked").glob("venv-*/bin/python"))
        _write_half_built_python(venv_python)

        result = sandbox.hook()

        assert "already running" not in result.stdout.lower(), result.stdout
        assert "build has started" not in result.stdout.lower(), result.stdout
        # Positive control: with no lock held, this same state is denied.
        assert "permissionDecision" in result.stdout, result.stdout
        assert "deny" in result.stdout, result.stdout
