"""The WorktreeCreate forwarder must report the daemon's OWN failure reason.

Plan 00419 N10. Four worktree agents were dispatched and all four came back
with::

    HOOKS DAEMON: WorktreeCreate produced no worktree path
    (is the worktree_create handler enabled?)

The handler WAS enabled, at priority 50, and had matched the event. It ran and
raised ``WorktreeSeedError``. The parenthetical named the one cause that was
provably false, and the first diagnostic step went to checking a registration
that was never in doubt — a message that confidently names the wrong cause is
worse than one that names none, because it is actionable in the wrong
direction.

The reason was never missing. A handler exception is accumulated into the
result's context, and for this event that serialises as
``{"systemMessage": "Handler exception: ..."}`` — already on the wire, in the
very bytes ``print_worktree`` receives. It was simply discarded.

``print_worktree`` lives inside ``init.sh``'s inline ``python3`` rung, so it is
extracted and run in a subprocess rather than imported. That is deliberate
twice over: the test pins the code that actually ships in the forwarder rather
than a copy that could drift, and a subprocess exercises the real ``sys.exit``
and the real stream separation, which is the half of this contract that matters
— stdout is parsed by Claude Code as the worktree PATH, so a diagnostic that
leaked there would be taken as a directory name.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INIT_SH = _REPO_ROOT / "init.sh"

_FUNCTION_HEADER = "def print_worktree(output):"
_RUN_TIMEOUT_SECONDS = 30


def _extract_print_worktree() -> str:
    """The real ``print_worktree`` source, lifted out of ``init.sh``.

    The body ends at the first unindented non-blank line, which is how the
    function ends inside the rung.
    """
    lines = _INIT_SH.read_text(encoding="utf-8").splitlines()
    start = next(
        (index for index, line in enumerate(lines) if line.strip() == _FUNCTION_HEADER), None
    )
    assert start is not None, (
        f"{_INIT_SH} no longer defines {_FUNCTION_HEADER!r}. If the forwarder's "
        "worktree response mode was renamed or removed, retarget this test — do "
        "not delete it; it pins a diagnostic that cost a wasted investigation."
    )

    body = [lines[start]]
    for line in lines[start + 1 :]:
        if line.strip() and not line.startswith((" ", "\t")):
            break
        body.append(line)
    return "\n".join(body)


@pytest.fixture(scope="module")
def driver(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A runnable script: the shipped function plus a one-line call."""
    script = tmp_path_factory.mktemp("worktree-rung") / "driver.py"
    script.write_text(
        "import json\nimport sys\n\n"
        + _extract_print_worktree()
        + "\n\nprint_worktree(sys.argv[1])\n",
        encoding="utf-8",
    )
    return script


def _run(driver: Path, payload: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(driver), payload],
        capture_output=True,
        text=True,
        timeout=_RUN_TIMEOUT_SECONDS,
    )


class TestTheHappyPathIsUnchanged:
    def test_a_path_is_printed_raw_and_exits_zero(self, driver: Path) -> None:
        """Claude Code parses stdout as the PATH, so nothing else may go there."""
        result = _run(driver, json.dumps({"worktreePath": "/repo/.claude/worktrees/alpha"}))

        assert result.returncode == 0
        assert result.stdout.strip() == "/repo/.claude/worktrees/alpha"
        assert result.stderr == ""


class TestTheDaemonsOwnReasonIsSurfaced:
    """The defect: the reason was on the wire and was thrown away."""

    def test_a_system_message_reaches_stderr(self, driver: Path) -> None:
        reason = (
            "Handler exception: WorktreeSeedError: Cannot seed worktree - "
            "1 configured entry is unusable"
        )
        result = _run(driver, json.dumps({"systemMessage": reason}))

        assert result.returncode == 1
        assert (
            result.stdout == ""
        ), "stdout is parsed as the worktree PATH; keep it empty on failure"
        assert reason in result.stderr

    def test_a_deny_reason_reaches_stderr(self, driver: Path) -> None:
        """A handler may refuse outright rather than crash."""
        result = _run(driver, json.dumps({"reason": "worktrees are disabled here"}))

        assert result.returncode == 1
        assert "worktrees are disabled here" in result.stderr

    def test_the_false_cause_is_not_asserted_when_a_reason_is_known(self, driver: Path) -> None:
        """The whole point. Naming a cause the daemon contradicted is the defect."""
        result = _run(
            driver, json.dumps({"systemMessage": "Handler exception: WorktreeSeedError: boom"})
        )

        assert "is the worktree_create handler enabled?" not in result.stderr


class TestNoReasonAvailable:
    """With nothing on the wire, say so — do not invent a cause."""

    def test_an_empty_response_still_fails_cleanly(self, driver: Path) -> None:
        result = _run(driver, "{}")

        assert result.returncode == 1
        assert result.stdout == ""
        assert "produced no worktree path" in result.stderr

    def test_unparseable_output_still_fails_cleanly(self, driver: Path) -> None:
        """Never echo '{}' or garbage: Claude Code would take it as a real path."""
        result = _run(driver, "not json at all")

        assert result.returncode == 1
        assert result.stdout == ""
        assert result.stderr.strip() != ""

    def test_the_reader_is_pointed_at_the_log_rather_than_at_a_guess(self, driver: Path) -> None:
        """When the cause is unknown, name where the cause IS written down."""
        result = _run(driver, "{}")

        assert "logs" in result.stderr
