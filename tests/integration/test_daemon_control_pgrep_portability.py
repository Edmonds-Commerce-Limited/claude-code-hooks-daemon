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
_PATTERN = "claude_code_hooks_daemon"


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
    assert (
        "MISSING" in result.stdout
    ), f"Expected MISSING when no daemon present.\n--- stdout ---\n{result.stdout}"


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


class TestHostilePathFallback:
    """Plan 00466 N30: `pgrep` is looked up on PATH -- when it is missing,
    `_daemon_process_exists` must not silently answer "not running" (the
    caller's retry fallback would then silently no-op, the same class of
    hazard BUG 3 above fixed for BSD's `\\|`). It falls back to a pure-bash
    /proc scan (Linux; no external command, so PATH cannot break it), and
    only when even that is unavailable does it fail loudly -- answering
    "maybe" rather than guessing "no"."""

    def _harness(self, body: str, *, path: str = "") -> str:
        path_line = f'export PATH="{path}"\n' if path else ""
        return textwrap.dedent(f"""\
            {path_line}export OUTPUT_SH_LOADED=1
            print_verbose() {{ :; }}
            print_error() {{ echo "PRINT_ERROR: $1" >&2; }}
            . "{DAEMON_CONTROL_SH}"
            {body}
            """)

    def _run(self, harness: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH, "-c", harness],
            capture_output=True,
            text=True,
            check=False,
            timeout=_TIMEOUT_SECONDS,
        )

    def _write_fake_cmdline(self, proc_dir: Path, pid: int, argv: list[str]) -> None:
        """A fabricated ``/proc/<pid>/cmdline`` -- NUL-separated argv, exactly
        the kernel's real format. A FIXTURE proc dir (rather than a real
        background process scanned via the host's real /proc) keeps this
        deterministic: the real /proc is host-wide and this container may
        already have an unrelated real daemon process running in it."""
        pid_dir = proc_dir / str(pid)
        pid_dir.mkdir(parents=True)
        (pid_dir / "cmdline").write_bytes(("\0".join(argv) + "\0").encode())

    def test_proc_fallback_finds_a_matching_process_with_no_pgrep_on_path(
        self, tmp_path: Path
    ) -> None:
        path_without_pgrep = tmp_path / "path-no-pgrep"
        path_without_pgrep.mkdir()
        proc_dir = tmp_path / "fake-proc"
        proc_dir.mkdir()
        self._write_fake_cmdline(proc_dir, 111, ["python", "-m", _PATTERN + ".daemon.cli"])

        harness = self._harness(
            textwrap.dedent(f"""\
                _HP_PROC_DIR="{proc_dir}"
                if _daemon_process_exists; then echo FOUND; else echo MISSING; fi
                """),
            path=str(path_without_pgrep),
        )
        result = self._run(harness)

        assert "FOUND" in result.stdout, (
            f"a matching process must be found via /proc, not silently missed just "
            f"because pgrep is unreachable. stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    def test_proc_fallback_reports_missing_when_nothing_matches(self, tmp_path: Path) -> None:
        path_without_pgrep = tmp_path / "path-no-pgrep"
        path_without_pgrep.mkdir()
        proc_dir = tmp_path / "fake-proc"
        proc_dir.mkdir()
        self._write_fake_cmdline(proc_dir, 222, ["some-other-process", "--flag"])

        harness = self._harness(
            textwrap.dedent(f"""\
                _HP_PROC_DIR="{proc_dir}"
                if _daemon_process_exists; then echo FOUND; else echo MISSING; fi
                """),
            path=str(path_without_pgrep),
        )
        result = self._run(harness)

        assert "MISSING" in result.stdout, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_loud_and_conservative_when_neither_pgrep_nor_proc_available(
        self, tmp_path: Path
    ) -> None:
        """Neither pgrep nor /proc: must not silently guess "not running" --
        says so loudly and answers "maybe" (FOUND), the safe direction for
        a caller that only uses this to decide whether to retry a status
        poll a little longer."""
        path_without_pgrep = tmp_path / "path-no-pgrep"
        path_without_pgrep.mkdir()
        harness = self._harness(
            textwrap.dedent(f"""\
                _HP_PROC_DIR="{tmp_path / "no-such-proc"}"
                if _daemon_process_exists; then echo FOUND; else echo MISSING; fi
                """),
            path=str(path_without_pgrep),
        )
        result = self._run(harness)

        assert "FOUND" in result.stdout, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert (
            "PRINT_ERROR" in result.stderr
        ), f"must say loudly that it could not determine an answer. stderr={result.stderr!r}"
