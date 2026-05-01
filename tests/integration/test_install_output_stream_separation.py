"""Regression test for v3.10.0 print_info-on-stdout bug (fixed in v3.10.1).

v3.10.0 shipped with print_info / print_success / print_warning / print_verbose
/ print_header / log_step writing to stdout. The install scripts use the
``VAR=$(helper ...)`` capture pattern in several places (e.g. ensure_venv
echoes its return value via stdout); any progress message printed before the
echo corrupted the capture.

A representative breakage from a v3.10.0 user upgrade::

    VENV_PATH=$(ensure_venv ...)        # captures two lines:
                                        #   "→ ensure_venv: creating venv at ..."
                                        #   "/path/to/venv-py314-fefc85e6"
    "$VENV_PATH/bin/python" -V          # → "/path/to/venv ...
                                        #     /bin/python: No such file or directory"

Fix: every helper except print_error already wrote to stderr; print_info,
print_success, print_warning, print_verbose, print_header, and log_step are
now redirected to stderr too. print_error was already correct.

These tests guard the contract: only stdout writes from helpers that are
explicitly part of a function's return value pattern (none in output.sh).
Every progress / status helper writes to stderr.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_SH = REPO_ROOT / "scripts" / "install" / "output.sh"
BASH = shutil.which("bash") or "/bin/bash"

# Every progress / status helper in output.sh must write to stderr so that
# capture patterns like VAR=$(helper_that_echoes_a_value ...) are not
# corrupted by progress messages.
_STDERR_ONLY_HELPERS: tuple[tuple[str, str], ...] = (
    ("print_info", "info-message-XYZ"),
    ("print_success", "success-message-XYZ"),
    ("print_warning", "warning-message-XYZ"),
    ("print_header", "header-message-XYZ"),
)


def _run(snippet: str) -> subprocess.CompletedProcess[str]:
    """Source output.sh and run a snippet; return CompletedProcess."""
    script = f'source "{OUTPUT_SH}"\n{snippet}\n'
    return subprocess.run(
        [BASH, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(("helper", "needle"), _STDERR_ONLY_HELPERS)
def test_helper_writes_to_stderr_not_stdout(helper: str, needle: str) -> None:
    """Progress helpers must write to stderr, never stdout."""
    result = _run(f'{helper} "{needle}"')
    assert result.returncode == 0, result.stderr
    assert needle not in result.stdout, (
        f"{helper} wrote message to STDOUT — this corrupts VAR=$(helper) "
        f"captures (v3.10.0 regression). stdout was: {result.stdout!r}"
    )
    assert (
        needle in result.stderr
    ), f"{helper} did not write message to STDERR. stderr was: {result.stderr!r}"


def test_print_verbose_writes_to_stderr_when_enabled() -> None:
    """print_verbose only fires when VERBOSE=true; when it does, stderr."""
    result = _run('VERBOSE=true print_verbose "verbose-message-XYZ"')
    assert result.returncode == 0
    assert "verbose-message-XYZ" not in result.stdout
    assert "verbose-message-XYZ" in result.stderr


def test_log_step_writes_to_stderr_not_stdout() -> None:
    """log_step is multi-line; every line must go to stderr."""
    result = _run('log_step 1 "step-message-XYZ"')
    assert result.returncode == 0
    assert "step-message-XYZ" not in result.stdout
    assert "----------------------------------------" not in result.stdout
    assert "step-message-XYZ" in result.stderr


def test_print_error_writes_to_stderr() -> None:
    """print_error already wrote to stderr in v3.10.0 — guard against regression."""
    result = _run('print_error "error-message-XYZ"')
    assert result.returncode == 0
    assert "error-message-XYZ" not in result.stdout
    assert "error-message-XYZ" in result.stderr


def test_helper_then_echo_captures_only_echo_value() -> None:
    """The exact capture pattern that ensure_venv uses.

    A function that prints progress via helpers and then echoes its return
    value MUST yield only the echoed value when captured as VAR=$(fn).
    This is the v3.10.0 → v3.10.1 regression contract.
    """
    snippet = (
        "fake_ensure() {\n"
        '    print_info "creating venv at /tmp/fake-venv"\n'
        '    print_success "venv ready"\n'
        '    echo "/tmp/fake-venv"\n'
        "}\n"
        "VENV_PATH=$(fake_ensure)\n"
        'echo "CAPTURED:[${VENV_PATH}]"\n'
    )
    result = _run(snippet)
    assert result.returncode == 0, result.stderr
    # The capture must contain ONLY the echoed path — no info/success noise.
    assert "CAPTURED:[/tmp/fake-venv]" in result.stdout, (
        f"VAR=$(fn) capture was corrupted by progress messages. "
        f"stdout: {result.stdout!r}, stderr: {result.stderr!r}"
    )
