"""Regression test for Plan 00104 Phase 2 Task 2.2 (Issue #6 — phantom).

The 2026-05-01 field report claimed health-check.sh "invokes the daemon CLI
via a separate hardcoded path rather than $PYTHON". Inspecting the v3.9.1
script source shows that claim is incorrect — every daemon CLI invocation
in health-check.sh already uses ``"$PYTHON"``. The field-report symptom
(daemon CLI executed under /usr/bin/python3.11) was actually caused by
Issue #4: ``write-venv-metadata`` stamping the base interpreter into
``.daemon-metadata.json::python_path``, which made ``$PYTHON`` resolve
to the system interpreter. Task 2.1 fixed that root cause.

This test guards the contract going forward: if any future edit to
health-check.sh re-introduces a hardcoded interpreter path or invokes
the daemon CLI without ``$PYTHON``, the test fails. The check is purely
static (parses the script source) — no subprocess, no fixture venv.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HEALTH_CHECK_SCRIPT = (
    REPO_ROOT
    / "src"
    / "claude_code_hooks_daemon"
    / "skills"
    / "hooks-daemon"
    / "scripts"
    / "health-check.sh"
)

CLI_MODULE = "claude_code_hooks_daemon.daemon.cli"
EXEC_PREFIX = '"$PYTHON" -m'
ECHO_PREFIX = "echo "


@pytest.fixture(scope="module")
def script_lines() -> list[str]:
    return HEALTH_CHECK_SCRIPT.read_text().splitlines()


def test_script_exists(script_lines: list[str]) -> None:
    assert HEALTH_CHECK_SCRIPT.is_file(), HEALTH_CHECK_SCRIPT
    assert script_lines, "health-check.sh is empty"


def test_every_cli_invocation_uses_resolved_python(script_lines: list[str]) -> None:
    """Every executed daemon-CLI call must run through ``"$PYTHON" -m ...``.

    Lines that only echo a command-string for user guidance are exempted —
    those are user-facing copy/paste hints, not script execution.
    """
    offending: list[tuple[int, str]] = []

    for lineno, raw in enumerate(script_lines, start=1):
        line = raw.strip()
        if CLI_MODULE not in line:
            continue
        if line.startswith(("#", '"#')):
            continue
        if line.lstrip().startswith(ECHO_PREFIX):
            continue
        if EXEC_PREFIX in line:
            continue
        offending.append((lineno, raw))

    assert not offending, (
        'health-check.sh has daemon CLI invocations that do NOT use "$PYTHON":\n'
        + "\n".join(f"  line {n}: {text}" for n, text in offending)
        + "\n\nIssue #6 (Plan 00104 Task 2.2) — every CLI invocation must run via "
        '"$PYTHON" so it uses the venv-resolved interpreter.'
    )


def test_no_hardcoded_system_interpreter(script_lines: list[str]) -> None:
    """No ``/usr/bin/python``, ``/usr/local/bin/python``, ``python3``-as-command,
    or other hardcoded interpreter path may execute daemon code.
    """
    forbidden_patterns = [
        re.compile(r"^\s*/usr/(local/)?bin/python"),
        re.compile(r"^\s*python3?\s+-m\s+claude_code_hooks_daemon"),
    ]
    offending: list[tuple[int, str]] = []
    for lineno, raw in enumerate(script_lines, start=1):
        for pattern in forbidden_patterns:
            if pattern.search(raw):
                offending.append((lineno, raw))
                break
    assert not offending, "health-check.sh contains a hardcoded interpreter path:\n" + "\n".join(
        f"  line {n}: {text}" for n, text in offending
    )
