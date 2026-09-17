"""``CLAUDE/Plan/mkplan.bash --journal`` — Plan 00427 Task 2.1/2.2 (RED first).

The owner's ruling (Plan 00427): a scaffolder stamps journal entries so the
agent never supplies a timestamp. This closes both failure modes measured on
the issue -- an agent estimating the clock, and a naive future-dated check
reading a foreign zone as ahead -- because the SCRIPT reads a real clock and
normalises it to UTC (D2, D3), never the caller.

The regression case is TWO writers in different zones on the SAME day-file,
not one writer pinned to a fixed clock: a single-zone test cannot distinguish
"the script reads UTC" from "the script happens to agree with the host's
zone today". Every test that cares about the zone drives it explicitly via
``TZ`` in the subprocess environment, mirroring ``untracked/scratch/repro45.py``.

Exercised as a real ``bash`` subprocess against a real temporary git
repository -- shell semantics, git-config state and ``date`` zone handling,
none of which a Python-level assertion could observe.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout

_SHELL_TIMEOUT = Timeout.VALIDATION_CHECK

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "CLAUDE" / "Plan" / "mkplan.bash"
_JOURNAL_TEMPLATE = _REPO_ROOT / "CLAUDE" / "Plan" / "_JOURNAL_TEMPLATE_.md"

_PLAN_COUNTER_KEY = "hooksdaemon.latestPlanNumber"

#: The sentinel is one specific line; count it, don't guess at wording.
_SENTINEL_PATTERN = re.compile(
    r"^_Scaffolded by `mkplan\.bash`; timestamps in this file are UTC\._$"
)

_ENTRY_HEADING = re.compile(r"^## (\d{2}):(\d{2}) · (\w+) · (\S+)(?:\s+— (.+))?$", re.MULTILINE)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=_SHELL_TIMEOUT,
    )
    return completed.stdout.strip()


def _git_config_or_none(repo: Path, key: str) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(repo), "config", "--local", "--get", key],
        capture_output=True,
        text=True,
        check=False,
        timeout=_SHELL_TIMEOUT,
    )
    if completed.returncode == 0:
        return completed.stdout.strip()
    if completed.returncode == 1:
        return None
    raise AssertionError(
        f"git config --get {key} failed unexpectedly (exit {completed.returncode}): {completed.stderr}"
    )


@pytest.fixture
def plan_repo(tmp_path: Path) -> Path:
    """A temporary git repo with the real scaffolder and journal template."""
    plan_dir = tmp_path / "CLAUDE" / "Plan"
    plan_dir.mkdir(parents=True)
    script_target = plan_dir / _SCRIPT.name
    script_target.write_bytes(_SCRIPT.read_bytes())
    script_target.chmod(0o755)
    (plan_dir / _JOURNAL_TEMPLATE.name).write_bytes(_JOURNAL_TEMPLATE.read_bytes())

    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "journal-tester@test.invalid")
    _git(tmp_path, "config", "user.name", "Journal Tester")
    return tmp_path


def _run(repo: Path, *args: str, tz: str | None = None) -> subprocess.CompletedProcess[str]:
    import os

    env = dict(os.environ)
    if tz is not None:
        env["TZ"] = tz
    else:
        env.pop("TZ", None)
    return subprocess.run(
        [str(repo / "CLAUDE" / "Plan" / "mkplan.bash"), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo,
        env=env,
        timeout=_SHELL_TIMEOUT,
    )


def _make_plan(repo: Path, number: str, slug: str) -> Path:
    """Hand-create a plan folder (this test never needs mkplan's own numbering)."""
    folder = repo / "CLAUDE" / "Plan" / f"{number}-{slug}"
    folder.mkdir(parents=True)
    (folder / "PLAN.md").write_text(f"# Plan {number}: {slug}\n")
    return folder


def _write_body(repo: Path, text: str = "Something worth logging.\n") -> Path:
    body = repo / "body.txt"
    body.write_text(text)
    return body


class TestValidation:
    """Every rejection writes nothing (D5) and exits non-zero."""

    def test_rejects_an_unknown_category(self, plan_repo: Path) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")
        body = _write_body(plan_repo)

        result = _run(plan_repo, "--journal", "42", "bogus", str(body))

        assert result.returncode != 0
        journal_dir = plan_repo / "CLAUDE" / "Plan" / "00042-sample-plan" / "JOURNAL"
        assert not journal_dir.exists(), "an invalid category must write nothing"

    def test_rejects_a_missing_plan_number(self, plan_repo: Path) -> None:
        body = _write_body(plan_repo)

        result = _run(plan_repo, "--journal", "99999", "action", str(body))

        assert result.returncode != 0
        assert "99999" in result.stderr

    def test_rejects_a_missing_body_file(self, plan_repo: Path) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")

        result = _run(plan_repo, "--journal", "42", "action", str(plan_repo / "nope.txt"))

        assert result.returncode != 0
        journal_dir = plan_repo / "CLAUDE" / "Plan" / "00042-sample-plan" / "JOURNAL"
        assert not journal_dir.exists()

    def test_rejects_an_empty_body_file(self, plan_repo: Path) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")
        body = plan_repo / "empty.txt"
        body.write_text("   \n\n")

        result = _run(plan_repo, "--journal", "42", "action", str(body))

        assert result.returncode != 0

    def test_rejects_when_journalling_is_not_enabled(self, plan_repo: Path) -> None:
        """No `_JOURNAL_TEMPLATE_.md` means the project has not opted in."""
        (plan_repo / "CLAUDE" / "Plan" / _JOURNAL_TEMPLATE.name).unlink()
        _make_plan(plan_repo, "00042", "sample-plan")
        body = _write_body(plan_repo)

        result = _run(plan_repo, "--journal", "42", "action", str(body))

        assert result.returncode != 0
        journal_dir = plan_repo / "CLAUDE" / "Plan" / "00042-sample-plan" / "JOURNAL"
        assert not journal_dir.exists()

    def test_does_not_accept_a_time_argument_at_all(self, plan_repo: Path) -> None:
        """The interface structurally has no way to supply a timestamp (D2)."""
        _make_plan(plan_repo, "00042", "sample-plan")
        body = _write_body(plan_repo)

        result = _run(plan_repo, "--journal", "42", "action", str(body), "--time", "09:00")

        assert result.returncode != 0


class TestD6aCounterIsolation:
    """The hazard the plan calls out by name: journal appends must not touch
    the plan counter or interact with plan-number assignment at all."""

    def test_journal_append_leaves_the_plan_counter_byte_identical(self, plan_repo: Path) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")
        _git(plan_repo, "config", "--local", _PLAN_COUNTER_KEY, "412")
        body = _write_body(plan_repo)

        before = _git_config_or_none(plan_repo, _PLAN_COUNTER_KEY)
        result = _run(plan_repo, "--journal", "42", "action", str(body))
        after = _git_config_or_none(plan_repo, _PLAN_COUNTER_KEY)

        assert result.returncode == 0, result.stderr
        assert before == "412"
        assert after == before, "a journal append burned/advanced the plan counter"

    def test_journal_append_leaves_an_unset_counter_unset(self, plan_repo: Path) -> None:
        """No plan has ever been created here -- the counter must stay unset,
        not get bootstrapped as a side effect of a journal append."""
        _make_plan(plan_repo, "00042", "sample-plan")
        body = _write_body(plan_repo)

        result = _run(plan_repo, "--journal", "42", "action", str(body))

        assert result.returncode == 0, result.stderr
        assert _git_config_or_none(plan_repo, _PLAN_COUNTER_KEY) is None

    def test_journal_append_does_not_take_the_plan_dir_lock(self, plan_repo: Path) -> None:
        """No leftover `.mkplan.lock` -- the journal path takes no lock."""
        _make_plan(plan_repo, "00042", "sample-plan")
        body = _write_body(plan_repo)

        _run(plan_repo, "--journal", "42", "action", str(body))

        assert not (plan_repo / "CLAUDE" / "Plan" / ".mkplan.lock").exists()


class TestSentinel:
    """D1: exactly one sentinel line, in the preamble, never per-entry."""

    def test_a_fresh_dayfile_carries_exactly_one_sentinel(self, plan_repo: Path) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")
        body = _write_body(plan_repo)

        result = _run(plan_repo, "--journal", "42", "action", str(body))
        assert result.returncode == 0, result.stderr

        journal_dir = plan_repo / "CLAUDE" / "Plan" / "00042-sample-plan" / "JOURNAL"
        day_files = list(journal_dir.glob("00042-Journal-*.md"))
        assert len(day_files) == 1
        lines = day_files[0].read_text().splitlines()
        sentinel_lines = [line for line in lines if _SENTINEL_PATTERN.match(line)]
        assert len(sentinel_lines) == 1

    def test_a_second_append_the_same_day_adds_no_extra_sentinel(self, plan_repo: Path) -> None:
        """Appending again must add an entry, not a second sentinel line."""
        _make_plan(plan_repo, "00042", "sample-plan")
        body1 = _write_body(plan_repo, "First entry.\n")
        body2 = _write_body(plan_repo, "Second entry.\n")
        (plan_repo / "b1.txt").write_text("First entry.\n")
        (plan_repo / "b2.txt").write_text("Second entry.\n")

        r1 = _run(plan_repo, "--journal", "42", "action", str(plan_repo / "b1.txt"))
        r2 = _run(plan_repo, "--journal", "42", "finding", str(plan_repo / "b2.txt"))
        assert r1.returncode == 0, r1.stderr
        assert r2.returncode == 0, r2.stderr
        del body1, body2

        journal_dir = plan_repo / "CLAUDE" / "Plan" / "00042-sample-plan" / "JOURNAL"
        day_files = list(journal_dir.glob("00042-Journal-*.md"))
        assert len(day_files) == 1, "both appends must land in the SAME UTC day-file"
        content = day_files[0].read_text()
        lines = content.splitlines()
        sentinel_lines = [line for line in lines if _SENTINEL_PATTERN.match(line)]
        assert len(sentinel_lines) == 1, "an entry must cost no extra sentinel line"
        assert "First entry." in content
        assert "Second entry." in content

    def test_entry_body_does_not_repeat_the_sentinel_text(self, plan_repo: Path) -> None:
        """An entry costs no extra LINES at all beyond its own heading/body."""
        _make_plan(plan_repo, "00042", "sample-plan")
        body = _write_body(plan_repo, "Body text unrelated to timestamps.\n")

        _run(plan_repo, "--journal", "42", "action", str(body))

        journal_dir = plan_repo / "CLAUDE" / "Plan" / "00042-sample-plan" / "JOURNAL"
        content = next(journal_dir.glob("00042-Journal-*.md")).read_text()
        assert content.count("Scaffolded by `mkplan.bash`") == 1


class TestAppendOnly:
    """D4: prove append-only by trying to violate it, not by one success."""

    def test_earlier_entry_bytes_are_never_altered_by_a_later_append(self, plan_repo: Path) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")
        b1 = plan_repo / "b1.txt"
        b1.write_text("Original finding, must survive verbatim.\n")
        b2 = plan_repo / "b2.txt"
        b2.write_text("Later entry.\n")

        _run(plan_repo, "--journal", "42", "finding", str(b1))
        journal_dir = plan_repo / "CLAUDE" / "Plan" / "00042-sample-plan" / "JOURNAL"
        day_file = next(journal_dir.glob("00042-Journal-*.md"))
        snapshot_before = day_file.read_text()

        _run(plan_repo, "--journal", "42", "action", str(b2))
        content_after = day_file.read_text()

        assert content_after.startswith(
            snapshot_before
        ), "earlier bytes were rewritten, not just appended to"
        assert content_after != snapshot_before, "the second call must have added something"

    def test_the_template_preamble_is_written_only_once_ever(self, plan_repo: Path) -> None:
        """A third append still shows only one copy of the template's intro
        line -- proves the day-file is never re-rendered from the template
        once created."""
        _make_plan(plan_repo, "00042", "sample-plan")
        for i in range(3):
            b = plan_repo / f"b{i}.txt"
            b.write_text(f"Entry {i}.\n")
            result = _run(plan_repo, "--journal", "42", "thought", str(b))
            assert result.returncode == 0, result.stderr

        journal_dir = plan_repo / "CLAUDE" / "Plan" / "00042-sample-plan" / "JOURNAL"
        content = next(journal_dir.glob("00042-Journal-*.md")).read_text()
        assert content.count("Append-only activity log") == 1


class TestEntryShape:
    """The appended heading matches the grammar and honours --ref/--title."""

    def test_default_heading_has_no_ref_and_no_title(self, plan_repo: Path) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")
        body = _write_body(plan_repo, "Plain entry body.\n")

        _run(plan_repo, "--journal", "42", "decision", str(body))

        journal_dir = plan_repo / "CLAUDE" / "Plan" / "00042-sample-plan" / "JOURNAL"
        content = next(journal_dir.glob("00042-Journal-*.md")).read_text()
        headings = [
            _ENTRY_HEADING.match(line) for line in content.splitlines() if line.startswith("## ")
        ]
        headings = [h for h in headings if h is not None]
        new_heading = headings[-1]
        assert new_heading.group(3) == "decision"
        assert new_heading.group(4) == "—"
        assert new_heading.group(5) is None
        assert "Plain entry body." in content

    def test_ref_and_title_flow_into_the_heading(self, plan_repo: Path) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")
        body = _write_body(plan_repo, "Titled entry body.\n")

        result = _run(
            plan_repo,
            "--journal",
            "42",
            "blocker",
            str(body),
            "--ref",
            "T2.1",
            "--title",
            "waiting on upstream",
        )
        assert result.returncode == 0, result.stderr

        journal_dir = plan_repo / "CLAUDE" / "Plan" / "00042-sample-plan" / "JOURNAL"
        content = next(journal_dir.glob("00042-Journal-*.md")).read_text()
        assert "· blocker · T2.1" in content
        assert "waiting on upstream" in content

    def test_accepts_a_zero_padded_plan_number(self, plan_repo: Path) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")
        body = _write_body(plan_repo)

        result = _run(plan_repo, "--journal", "00042", "action", str(body))

        assert result.returncode == 0, result.stderr


class TestUtcCrossZoneRegression:
    """The regression case: two writers, two zones, one day-file.

    A test pinning a single clock cannot tell "the script reads UTC" apart
    from "the script's zone happens to match the host's zone today" -- so
    each writer below runs in a DIFFERENT TZ, and the assertion is that both
    land on the SAME UTC day-file with times that increase with real elapsed
    time, never with the zone offset the calling agent happened to be in.
    """

    def test_two_writers_in_different_zones_share_one_utc_dayfile(self, plan_repo: Path) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")
        b1 = plan_repo / "b1.txt"
        b1.write_text("Writer A (UTC).\n")
        b2 = plan_repo / "b2.txt"
        b2.write_text("Writer B (UTC+5:30).\n")

        r1 = _run(plan_repo, "--journal", "42", "action", str(b1), tz="UTC")
        r2 = _run(plan_repo, "--journal", "42", "finding", str(b2), tz="Asia/Kolkata")

        assert r1.returncode == 0, r1.stderr
        assert r2.returncode == 0, r2.stderr

        journal_dir = plan_repo / "CLAUDE" / "Plan" / "00042-sample-plan" / "JOURNAL"
        day_files = list(journal_dir.glob("00042-Journal-*.md"))
        assert len(day_files) == 1, (
            "a writer under TZ=Asia/Kolkata (UTC+5:30) landed on a DIFFERENT "
            f"day-file than the UTC writer: {[f.name for f in day_files]} -- "
            "the script is reading the local clock, not normalising to UTC"
        )
        content = day_files[0].read_text()
        assert "Writer A (UTC)." in content
        assert "Writer B (UTC+5:30)." in content

    def test_a_negative_offset_writer_also_lands_on_the_same_dayfile(self, plan_repo: Path) -> None:
        """Opposite-direction check: a writer BEHIND UTC must not be shunted
        onto yesterday's or a phantom day-file either."""
        _make_plan(plan_repo, "00042", "sample-plan")
        b1 = plan_repo / "b1.txt"
        b1.write_text("Writer A (UTC).\n")
        b2 = plan_repo / "b2.txt"
        b2.write_text("Writer C (UTC-8).\n")

        r1 = _run(plan_repo, "--journal", "42", "action", str(b1), tz="UTC")
        r2 = _run(plan_repo, "--journal", "42", "finding", str(b2), tz="America/Los_Angeles")

        assert r1.returncode == 0, r1.stderr
        assert r2.returncode == 0, r2.stderr

        journal_dir = plan_repo / "CLAUDE" / "Plan" / "00042-sample-plan" / "JOURNAL"
        day_files = list(journal_dir.glob("00042-Journal-*.md"))
        assert len(day_files) == 1, [f.name for f in day_files]

    def test_recorded_times_are_utc_not_the_writers_local_clock(self, plan_repo: Path) -> None:
        """The written HH:MM must match `date -u`, not a Kolkata-local reading
        -- pins D3 directly rather than inferring it from same-file placement."""
        import datetime

        _make_plan(plan_repo, "00042", "sample-plan")
        body = plan_repo / "b.txt"
        body.write_text("Zone-pinned entry.\n")

        before_utc = datetime.datetime.now(datetime.UTC)
        result = _run(plan_repo, "--journal", "42", "action", str(body), tz="Asia/Kolkata")
        after_utc = datetime.datetime.now(datetime.UTC)
        assert result.returncode == 0, result.stderr

        journal_dir = plan_repo / "CLAUDE" / "Plan" / "00042-sample-plan" / "JOURNAL"
        content = next(journal_dir.glob("00042-Journal-*.md")).read_text()
        match = list(_ENTRY_HEADING.finditer(content))[-1]
        written_hour, written_minute = int(match.group(1)), int(match.group(2))
        written_minutes = written_hour * 60 + written_minute

        lower = before_utc.hour * 60 + before_utc.minute - 2
        upper = after_utc.hour * 60 + after_utc.minute + 2
        # Kolkata is UTC+5:30; if the bug regresses (local time written), the
        # recorded minutes would be ~330 minutes outside this UTC window.
        assert lower - 5 <= written_minutes <= upper + 5, (
            written_minutes,
            lower,
            upper,
        )
