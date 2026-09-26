"""Contract tests for scripts/dummy-client-repo.sh daemon targeting.

The daemon CLI picks the daemon it MANAGES (socket/PID/log) from the project
root resolved out of the CURRENT WORKING DIRECTORY — not from the interpreter's
location. A fixture helper that invokes the CLI without anchoring therefore acts
on whatever project the caller happens to be standing in.

That is not hypothetical. ``stop_dummy_daemon`` invoked ``... daemon.cli stop``
with neither a ``cd`` nor ``--project-root``, so when teardown ran from the
dogfood repo the stop resolved /workspace, found no dummy PID file, printed
"Daemon not running", exited 0 — and teardown then deleted the tree around a
still-live daemon, leaving an orphan whose cwd pointed at a deleted directory
while reporting a clean teardown.
"""

import os
import re
import signal
import subprocess
import sys
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.safe_signal import signal_own_session_child

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
_REAP_SECONDS: Final[int] = 10
_FIXTURE_SCRIPT: Final[Path] = _REPO_ROOT / "scripts" / "dummy-client-repo.sh"

#: A daemon-CLI invocation in the fixture script.
_CLI_INVOCATION: Final[re.Pattern[str]] = re.compile(r"claude_code_hooks_daemon\.daemon\.cli")

#: The two acceptable ways to anchor an invocation at the dummy project.
_EXPLICIT_ANCHOR: Final[re.Pattern[str]] = re.compile(r"--project-root")
_CD_ANCHOR: Final[re.Pattern[str]] = re.compile(r'cd\s+"\$DUMMY_ROOT"')

#: How many lines above an invocation a ``cd`` still counts as anchoring it.
_CD_LOOKBACK_LINES: Final[int] = 5


def _logical_lines() -> list[tuple[int, str]]:
    """Return (1-based starting line number, full text) for each logical line.

    Backslash continuations are joined, because a shell command is one logical
    invocation however it is wrapped — a ``--project-root`` on the continuation
    line anchors the call just as well as one on the first line.
    """
    raw = _FIXTURE_SCRIPT.read_text().splitlines()
    logical: list[tuple[int, str]] = []
    buffer: list[str] = []
    start_number = 0

    for number, line in enumerate(raw, start=1):
        if not buffer:
            start_number = number
        buffer.append(line.rstrip("\\"))
        if line.rstrip().endswith("\\"):
            continue
        logical.append((start_number, " ".join(buffer)))
        buffer = []

    if buffer:
        logical.append((start_number, " ".join(buffer)))
    return logical


def _invocation_lines() -> list[tuple[int, str]]:
    """Return (1-based line number, text) for every daemon-CLI invocation.

    Comment lines are excluded — prose describing the pattern is not a call.
    """
    return [
        (number, text)
        for number, text in _logical_lines()
        if _CLI_INVOCATION.search(text) and not text.lstrip().startswith("#")
    ]


class TestFixtureScriptAnchorsEveryDaemonInvocation:
    """Every CLI call must name the project it targets."""

    def test_fixture_script_exists(self) -> None:
        """Guard against the test silently passing if the script moves."""
        assert _FIXTURE_SCRIPT.is_file(), f"missing: {_FIXTURE_SCRIPT}"

    def test_at_least_one_invocation_is_present(self) -> None:
        """Guard against the regex silently matching nothing."""
        assert _invocation_lines(), (
            "No daemon-CLI invocations found — the detection regex has rotted "
            "and this test is no longer checking anything."
        )

    def test_every_invocation_is_anchored_to_the_dummy_project(self) -> None:
        """An unanchored invocation targets the CALLER's project, not the fixture."""
        lines = _FIXTURE_SCRIPT.read_text().splitlines()
        unanchored: list[tuple[int, str]] = []

        for number, line in _invocation_lines():
            # Anchored explicitly by flag, or by a cd in the same logical line
            # (e.g. `$(cd "$DUMMY_ROOT" && ... cli status)`).
            if _EXPLICIT_ANCHOR.search(line) or _CD_ANCHOR.search(line):
                continue
            # Or by a cd in the immediately preceding lines of the same function.
            start = max(0, number - 1 - _CD_LOOKBACK_LINES)
            preceding = "\n".join(lines[start : number - 1])
            if _CD_ANCHOR.search(preceding):
                continue
            unanchored.append((number, line.strip()))

        assert not unanchored, (
            "Unanchored daemon-CLI invocation(s) in dummy-client-repo.sh — these "
            "resolve the project root from the CALLER's cwd and so act on "
            "whichever daemon the caller is standing in:\n"
            + "\n".join(f"  line {n}: {text}" for n, text in unanchored)
            + '\nAnchor with --project-root "$DUMMY_ROOT" (preferred) or a '
            'preceding cd "$DUMMY_ROOT".'
        )


class TestTeardownVerifiesTheDaemonActuallyStopped:
    """Teardown must not report success while a daemon survives."""

    def test_destroy_asserts_no_surviving_daemon(self) -> None:
        """Regression: destroy deleted the tree around a live daemon, reporting success.

        The stop resolved the wrong project, said "Daemon not running", and
        teardown believed it. A post-condition check is what turns that silent
        orphan into a visible failure.
        """
        content = _FIXTURE_SCRIPT.read_text()
        assert "verify_dummy_daemon_stopped" in content, (
            "cmd_destroy must verify the dummy daemon is actually gone before "
            "deleting its directory — otherwise a failed stop silently orphans "
            "the process and teardown still reports success."
        )


#: Runs the two teardown functions, extracted from the script, with stub
#: `info`/`fail` and no `main`.
_TEARDOWN_HARNESS: Final[str] = r"""
set -euo pipefail
info() { printf '%s\n' "$*" >&2; }
fail() { printf 'FAIL %s\n' "$*" >&2; return 1; }
source <(awk '/^_surviving_dummy_daemons\(\) \{/,/^\}$/' "$SCRIPT")
source <(awk '/^_is_dummy_daemon_pid\(\) \{/,/^\}$/' "$SCRIPT")
source <(awk '/^verify_dummy_daemon_stopped\(\) \{/,/^\}$/' "$SCRIPT")
verify_dummy_daemon_stopped
"""

#: Runs the identity check alone on "$PID"; its exit status is the verdict.
_IDENTITY_HARNESS: Final[str] = r"""
set -euo pipefail
source <(awk '/^_is_dummy_daemon_pid\(\) \{/,/^\}$/' "$SCRIPT")
_is_dummy_daemon_pid "$PID"
"""

#: Above Linux's default pid_max, so no process can have it.
_NONEXISTENT_PID: Final[int] = 2**22 + 7

#: A group leader that starts a stand-in dummy daemon and an unrelated
#: sibling in ITS group, prints both pids, and waits.
_GROUP_OF_TWO: Final[str] = """
import os, subprocess, sys, time
daemon = subprocess.Popen([os.environ["STAND_IN"], "-c", "import time; time.sleep(60)"])
sibling = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
print(daemon.pid, sibling.pid, flush=True)
time.sleep(60)
"""


class TestTeardownSignalsOnlyTheProvenPid:
    """Plan 00466 N59: a survivor's pid is proven by its command line; its group is not.

    The daemon does not lead its process group, so ``kill -- -<pgid>`` could
    reach init's group or teardown's own. Here the stand-in shares a group
    with an unrelated sibling: only the stand-in may be signalled.
    """

    def test_the_survivor_is_stopped_and_its_group_mate_is_not(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / ".claude" / "hooks-daemon"
        interpreter = daemon_dir / "untracked" / "venv-dummy" / "bin" / "python"
        interpreter.parent.mkdir(parents=True)
        interpreter.symlink_to(sys.executable)

        # The stand-in's path goes in the environment, not argv, so the only
        # command line naming the dummy venv is the stand-in's own.
        leader = subprocess.Popen(
            [sys.executable, "-c", _GROUP_OF_TWO],
            stdout=subprocess.PIPE,
            env={**os.environ, "STAND_IN": str(interpreter)},
            start_new_session=True,
        )
        try:
            assert leader.stdout is not None
            daemon_pid, sibling_pid = (int(p) for p in leader.stdout.readline().split())

            result = subprocess.run(
                ["bash", "-c", _TEARDOWN_HARNESS],
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "SCRIPT": str(_FIXTURE_SCRIPT),
                    "DUMMY_DAEMON_DIR": str(daemon_dir),
                },
                check=False,
            )

            assert result.returncode == 0, result.stderr
            assert "surviving daemon reaped" in result.stderr
            assert _is_running(sibling_pid), "teardown signalled the survivor's whole group"
            assert not _is_running(daemon_pid)
        finally:
            signal_own_session_child(leader, signal.SIGKILL)
            leader.wait(timeout=_REAP_SECONDS)


class TestTheSurvivorIsReIdentifiedImmediatelyBeforeTheSignal:
    """Plan 00466 N59: pgrep's answer is a moment old, and its pid may since be reused.

    ``_is_dummy_daemon_pid`` re-reads the pid's command line right before the
    kill, so a pid that no longer runs out of the dummy venv is not signalled.
    """

    def _verdict(self, daemon_dir: Path, pid: int) -> int:
        return subprocess.run(
            ["bash", "-c", _IDENTITY_HARNESS],
            capture_output=True,
            env={
                **os.environ,
                "SCRIPT": str(_FIXTURE_SCRIPT),
                "DUMMY_DAEMON_DIR": str(daemon_dir),
                "PID": str(pid),
            },
            check=False,
        ).returncode

    def test_a_process_running_out_of_the_dummy_venv(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / ".claude" / "hooks-daemon"
        interpreter = daemon_dir / "untracked" / "venv-dummy" / "bin" / "python"
        interpreter.parent.mkdir(parents=True)
        interpreter.symlink_to(sys.executable)
        stand_in = subprocess.Popen(
            [str(interpreter), "-c", "import time; time.sleep(60)"], start_new_session=True
        )
        try:
            assert self._verdict(daemon_dir, stand_in.pid) == 0
        finally:
            signal_own_session_child(stand_in, signal.SIGKILL)
            stand_in.wait(timeout=_REAP_SECONDS)

    def test_a_process_that_does_not(self, tmp_path: Path) -> None:
        bystander = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True
        )
        try:
            assert self._verdict(tmp_path / ".claude" / "hooks-daemon", bystander.pid) == 1
        finally:
            signal_own_session_child(bystander, signal.SIGKILL)
            bystander.wait(timeout=_REAP_SECONDS)

    def test_a_pid_nobody_has(self, tmp_path: Path) -> None:
        assert self._verdict(tmp_path / ".claude" / "hooks-daemon", _NONEXISTENT_PID) == 1


def _is_running(pid: int) -> bool:
    """Alive and not a zombie (an unreaped child of the group leader)."""
    try:
        status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    state = next(line for line in status.splitlines() if line.startswith("State:"))
    return "Z" not in state
