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

import re
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
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
