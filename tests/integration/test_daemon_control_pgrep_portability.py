"""Plan 00123 BUG 3 (MEDIUM) — daemon_control.sh pgrep is portable on BSD.

``restart_daemon_verified`` has a fallback: if the status poll times out it
checks whether a daemon process exists via ``pgrep``. The pattern was
``pgrep -f "claude-hooks-daemon\\|claude_code_hooks_daemon"`` — the ``\\|``
alternation is a GNU regex extension. BSD ``pgrep`` (macOS) treats ``\\|``
literally, so it only matches the impossible literal string and NEVER finds a
real daemon → the recovery retry silently no-ops, making restart/install more
likely to falsely report "daemon failed to start" on a slow macOS box.

Fix: extract ``_daemon_process_exists`` using two separate ``pgrep -f``
invocations (no GNU alternation). These tests stub a BSD-style ``pgrep`` that
matches its pattern as a literal substring against a fake process table.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DAEMON_CONTROL_SH = REPO_ROOT / "scripts" / "install" / "daemon_control.sh"
BASH = shutil.which("bash") or "/bin/bash"

_TIMEOUT_SECONDS = 30
_FAKE_CMDLINE = "python -m claude_code_hooks_daemon.daemon.cli start"


def _run_exists(tmp_path: Path, *, process_present: bool) -> subprocess.CompletedProcess[str]:
    """Source daemon_control.sh, stub BSD pgrep, call _daemon_process_exists."""
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()

    fake_table = _FAKE_CMDLINE if process_present else ""
    # BSD-style pgrep: `pgrep -f PATTERN`. Treats PATTERN as a LITERAL substring
    # (no `\|` alternation). Matches against a single-line fake process table.
    pgrep_stub = stub_dir / "pgrep"
    pgrep_stub.write_text(textwrap.dedent(f"""\
            #!/bin/bash
            # args: -f PATTERN
            pattern="$2"
            table="{fake_table}"
            case "$table" in
                *"$pattern"*) echo 12345; exit 0 ;;
                *) exit 1 ;;
            esac
            """))
    pgrep_stub.chmod(0o755)

    harness = textwrap.dedent(f"""\
        export PATH="{stub_dir}:$PATH"
        export OUTPUT_SH_LOADED=1
        print_verbose() {{ :; }}
        print_error() {{ :; }}
        . "{DAEMON_CONTROL_SH}"
        if _daemon_process_exists; then echo FOUND; else echo MISSING; fi
        """)
    return subprocess.run(
        [BASH, "-c", harness],
        capture_output=True,
        text=True,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )


def test_detects_daemon_on_bsd_pgrep(tmp_path: Path) -> None:
    """A real daemon process is detected even under BSD pgrep (no `\\|`)."""
    result = _run_exists(tmp_path, process_present=True)
    assert "FOUND" in result.stdout, (
        "BUG 3: daemon process must be detected via separate pgrep patterns — "
        "BSD pgrep treats `\\|` literally and would miss it.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


def test_reports_missing_when_no_daemon(tmp_path: Path) -> None:
    """No daemon process → helper reports missing (exit non-zero)."""
    result = _run_exists(tmp_path, process_present=False)
    assert "MISSING" in result.stdout, (
        f"Expected MISSING when no daemon present.\n--- stdout ---\n{result.stdout}"
    )


def test_no_gnu_alternation_in_pgrep() -> None:
    r"""No ``\|`` GNU alternation may remain in executable (non-comment) code.

    Comment lines may quote the old buggy pattern for documentation; only
    executable lines are checked.
    """
    offenders: list[str] = []
    for lineno, line in enumerate(DAEMON_CONTROL_SH.read_text().splitlines(), start=1):
        if line.strip().startswith("#"):
            continue
        if r"\|" in line:
            offenders.append(f"{lineno}: {line.strip()}")
    assert not offenders, (
        r"BUG 3: GNU `\|` alternation must not appear in executable code — "
        "use separate pgrep invocations for BSD compatibility:\n" + "\n".join(offenders)
    )
