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

#: Plan 00543: one file per entry, JOURNAL/YYYY-MM-DD/HHMMSSZ-<category>-<6 hex>.md.
_ENTRY_FILE_NAME = re.compile(r"^(\d{2})(\d{2})(\d{2})Z-([a-z]+)-([0-9a-f]{6})\.md$")
_DAY_FOLDER_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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


def _journal_dir(repo: Path) -> Path:
    return repo / "CLAUDE" / "Plan" / "00042-sample-plan" / "JOURNAL"


def _entry_files(repo: Path) -> list[Path]:
    """Every per-entry file of plan 00042, in path order."""
    return sorted(_journal_dir(repo).glob("*/*.md"))


class TestEntryFileLayout:
    """Plan 00543: each entry is its own NEW file under a per-day folder."""

    def test_an_entry_lands_in_a_dated_folder_with_a_stamped_name(self, plan_repo: Path) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")

        result = _run(plan_repo, "--journal", "42", "action", str(_write_body(plan_repo)))

        assert result.returncode == 0, result.stderr
        files = _entry_files(plan_repo)
        assert len(files) == 1
        assert _DAY_FOLDER_NAME.match(files[0].parent.name), files[0]
        name = _ENTRY_FILE_NAME.match(files[0].name)
        assert name is not None, files[0].name
        assert name.group(4) == "action"
        assert result.stdout.strip() == str(files[0])

    def test_no_legacy_day_file_is_created(self, plan_repo: Path) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")

        _run(plan_repo, "--journal", "42", "action", str(_write_body(plan_repo)))

        assert list(_journal_dir(plan_repo).glob("*-Journal-*.md")) == []

    def test_an_entry_file_holds_its_heading_a_blank_line_and_the_body_only(
        self, plan_repo: Path
    ) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")

        _run(plan_repo, "--journal", "42", "finding", str(_write_body(plan_repo, "Just this.\n")))

        content = _entry_files(plan_repo)[0].read_text()
        lines = content.splitlines()
        assert _ENTRY_HEADING.match(lines[0]), lines[0]
        assert lines[1:] == ["", "Just this."]
        assert len(_ENTRY_HEADING.findall(content)) == 1

    def test_the_file_name_time_equals_the_heading_time(self, plan_repo: Path) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")

        _run(plan_repo, "--journal", "42", "decision", str(_write_body(plan_repo)))

        path = _entry_files(plan_repo)[0]
        name = _ENTRY_FILE_NAME.match(path.name)
        heading = _ENTRY_HEADING.match(path.read_text().splitlines()[0])
        assert name is not None and heading is not None
        assert (name.group(1), name.group(2)) == (heading.group(1), heading.group(2))

    def test_two_entries_in_a_row_are_two_files(self, plan_repo: Path) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")
        (plan_repo / "b1.txt").write_text("First entry.\n")
        (plan_repo / "b2.txt").write_text("Second entry.\n")

        r1 = _run(plan_repo, "--journal", "42", "action", str(plan_repo / "b1.txt"))
        r2 = _run(plan_repo, "--journal", "42", "action", str(plan_repo / "b2.txt"))

        assert r1.returncode == 0, r1.stderr
        assert r2.returncode == 0, r2.stderr
        files = _entry_files(plan_repo)
        assert len(files) == 2, "the same category in the same second must still not collide"
        assert {f.read_text().splitlines()[-1] for f in files} == {"First entry.", "Second entry."}

    def test_a_refused_call_creates_no_dated_folder(self, plan_repo: Path) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")

        _run(plan_repo, "--journal", "42", "bogus", str(_write_body(plan_repo)))

        assert not _journal_dir(plan_repo).exists()


class TestNeverTouchesExistingFiles:
    """Plan 00543: the writer only ever ADDS a file (append-only by construction)."""

    def test_existing_entry_and_legacy_day_files_survive_byte_identical(
        self, plan_repo: Path
    ) -> None:
        folder = _make_plan(plan_repo, "00042", "sample-plan")
        (folder / "JOURNAL").mkdir()
        legacy = folder / "JOURNAL" / "00042-Journal-26-01-01.md"
        legacy.write_text("# Plan 00042 — Journal 26-01-01\n\n## 10:50 · finding · —\n\nOld.\n")
        _run(plan_repo, "--journal", "42", "finding", str(_write_body(plan_repo, "Earlier.\n")))
        first = _entry_files(plan_repo)[0]
        before = {legacy: legacy.read_bytes(), first: first.read_bytes()}

        result = _run(
            plan_repo, "--journal", "42", "action", str(_write_body(plan_repo, "Later.\n"))
        )

        assert result.returncode == 0, result.stderr
        assert {path: path.read_bytes() for path in before} == before
        assert len(_entry_files(plan_repo)) == 2

    def test_a_same_day_legacy_day_file_is_not_appended_to(self, plan_repo: Path) -> None:
        import datetime

        folder = _make_plan(plan_repo, "00042", "sample-plan")
        (folder / "JOURNAL").mkdir()
        today = datetime.datetime.now(datetime.UTC).strftime("%y-%m-%d")
        legacy = folder / "JOURNAL" / f"00042-Journal-{today}.md"
        legacy.write_text("# Plan 00042 — Journal\n\n## 00:00 · finding · —\n\nOld.\n")
        before = legacy.read_bytes()

        result = _run(plan_repo, "--journal", "42", "action", str(_write_body(plan_repo)))

        assert result.returncode == 0, result.stderr
        assert legacy.read_bytes() == before
        assert len(_entry_files(plan_repo)) == 1


class TestEntryShape:
    """The appended heading matches the grammar and honours --ref/--title."""

    def test_default_heading_has_no_ref_and_no_title(self, plan_repo: Path) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")
        body = _write_body(plan_repo, "Plain entry body.\n")

        _run(plan_repo, "--journal", "42", "decision", str(body))

        content = _entry_files(plan_repo)[0].read_text()
        new_heading = _last_heading(content)
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

        content = _entry_files(plan_repo)[0].read_text()
        assert "· blocker · T2.1" in content
        assert "waiting on upstream" in content

    def test_accepts_a_zero_padded_plan_number(self, plan_repo: Path) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")
        body = _write_body(plan_repo)

        result = _run(plan_repo, "--journal", "00042", "action", str(body))

        assert result.returncode == 0, result.stderr


_JOURNAL_DIR_PARTS = ("CLAUDE", "Plan", "00042-sample-plan", "JOURNAL")


def _only_entry(repo: Path) -> Path:
    files = _entry_files(repo)
    assert len(files) == 1, files
    return files[0]


def _last_heading(content: str) -> re.Match[str]:
    return list(_ENTRY_HEADING.finditer(content))[-1]


class TestCorrectionEntries:
    """Ledger 00422 N3, decision 5: a `correction` names the entry it corrects.

    The REF of a correction is the corrected entry's `HH:MM` in today's
    day-file, or `YY-MM-DD/HH:MM` for an entry in an earlier one. The script
    refuses a correction that names nothing, because a dangling reference is
    a correction nobody can follow — and the ordering check trusts the name.
    """

    def test_a_correction_naming_an_entry_in_todays_file_is_appended(self, plan_repo: Path) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")
        first = _run(plan_repo, "--journal", "42", "finding", str(_write_body(plan_repo)))
        assert first.returncode == 0, first.stderr
        corrected = _last_heading(_only_entry(plan_repo).read_text())
        first_entry = _only_entry(plan_repo)
        label = f"{corrected.group(1)}:{corrected.group(2)}"

        body = plan_repo / "correction.txt"
        body.write_text("That stamp was wrong.\n")
        result = _run(plan_repo, "--journal", "42", "correction", str(body), "--ref", label)

        assert result.returncode == 0, result.stderr
        (new_entry,) = [f for f in _entry_files(plan_repo) if f != first_entry]
        heading = _last_heading(new_entry.read_text())
        assert heading.group(3) == "correction"
        assert heading.group(4) == label

    def test_a_correction_may_name_an_entry_in_an_earlier_dayfile(self, plan_repo: Path) -> None:
        folder = _make_plan(plan_repo, "00042", "sample-plan")
        (folder / "JOURNAL").mkdir()
        (folder / "JOURNAL" / "00042-Journal-26-01-01.md").write_text(
            "# Plan 00042 — Journal 26-01-01\n\n## 10:50 · finding · —   — wrong\n\nBody.\n"
        )

        result = _run(
            plan_repo,
            "--journal",
            "42",
            "correction",
            str(_write_body(plan_repo)),
            "--ref",
            "26-01-01/10:50",
        )

        assert result.returncode == 0, result.stderr
        assert "· correction · 26-01-01/10:50" in _only_entry(plan_repo).read_text()

    def test_a_correction_may_name_an_entry_file_of_an_earlier_day(self, plan_repo: Path) -> None:
        folder = _make_plan(plan_repo, "00042", "sample-plan")
        day = folder / "JOURNAL" / "2026-01-01"
        day.mkdir(parents=True)
        old = day / "105001Z-finding-abc123.md"
        old.write_text("## 10:50 · finding · —\n\nWrong.\n")

        result = _run(
            plan_repo,
            "--journal",
            "42",
            "correction",
            str(_write_body(plan_repo)),
            "--ref",
            "26-01-01/10:50",
        )

        assert result.returncode == 0, result.stderr
        (new_entry,) = [f for f in _entry_files(plan_repo) if f != old]
        assert "· correction · 26-01-01/10:50" in new_entry.read_text()
        assert old.read_text().endswith("Wrong.\n")

    def test_a_correction_without_a_ref_is_refused(self, plan_repo: Path) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")

        result = _run(plan_repo, "--journal", "42", "correction", str(_write_body(plan_repo)))

        assert result.returncode != 0
        assert "--ref" in result.stderr
        assert not plan_repo.joinpath(*_JOURNAL_DIR_PARTS).exists(), "a refusal writes nothing"

    @pytest.mark.parametrize("ref", ["T2.1", "9:50", "26-01-01 10:50", "—"])
    def test_a_ref_that_is_not_an_entry_time_is_refused(self, plan_repo: Path, ref: str) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")

        result = _run(
            plan_repo, "--journal", "42", "correction", str(_write_body(plan_repo)), "--ref", ref
        )

        assert result.returncode != 0
        assert not plan_repo.joinpath(*_JOURNAL_DIR_PARTS).exists(), "a refusal writes nothing"

    def test_a_correction_naming_no_entry_in_todays_file_is_refused(self, plan_repo: Path) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")
        first = _run(plan_repo, "--journal", "42", "finding", str(_write_body(plan_repo)))
        assert first.returncode == 0, first.stderr
        before = _only_entry(plan_repo).read_bytes()
        existing = _last_heading(before.decode())
        absent = "00:01" if f"{existing.group(1)}:{existing.group(2)}" == "00:00" else "00:00"

        result = _run(
            plan_repo, "--journal", "42", "correction", str(_write_body(plan_repo)), "--ref", absent
        )

        assert result.returncode != 0
        assert absent in result.stderr
        assert _only_entry(plan_repo).read_bytes() == before, "a refusal writes nothing"

    def test_a_heading_quoted_inside_a_fence_is_not_an_entry(self, plan_repo: Path) -> None:
        folder = _make_plan(plan_repo, "00042", "sample-plan")
        (folder / "JOURNAL").mkdir()
        (folder / "JOURNAL" / "00042-Journal-26-01-01.md").write_text(
            "# Plan 00042 — Journal 26-01-01\n\n"
            "## 09:00 · finding · —\n\n```\n## 10:50 · finding · — quoted\n```\n"
        )

        result = _run(
            plan_repo,
            "--journal",
            "42",
            "correction",
            str(_write_body(plan_repo)),
            "--ref",
            "26-01-01/10:50",
        )

        assert result.returncode != 0

    def test_a_correction_naming_a_missing_dayfile_is_refused(self, plan_repo: Path) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")

        result = _run(
            plan_repo,
            "--journal",
            "42",
            "correction",
            str(_write_body(plan_repo)),
            "--ref",
            "26-01-01/10:50",
        )

        assert result.returncode != 0
        assert not plan_repo.joinpath(*_JOURNAL_DIR_PARTS).exists(), "a refusal writes nothing"


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

        day_folders = {f.parent.name for f in _entry_files(plan_repo)}
        assert len(day_folders) == 1, (
            "a writer under TZ=Asia/Kolkata (UTC+5:30) landed in a DIFFERENT "
            f"day folder than the UTC writer: {sorted(day_folders)} -- "
            "the script is reading the local clock, not normalising to UTC"
        )
        content = "".join(f.read_text() for f in _entry_files(plan_repo))
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

        day_folders = {f.parent.name for f in _entry_files(plan_repo)}
        assert len(day_folders) == 1, sorted(day_folders)

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

        content = _only_entry(plan_repo).read_text()
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


_TEMPLATE_SCRIPT = (
    _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "install" / "templates" / "mkplan.bash"
)


class TestHelpDocumentsJournalMode:
    """Plan 00461: an agent that checks the usage must find `--journal`.

    Journal entries are only accepted through this mode, so the usage an
    agent reaches for first cannot leave it out. Both the deployed copy and the
    template every client receives are checked.
    """

    @pytest.mark.parametrize("script", [_SCRIPT, _TEMPLATE_SCRIPT], ids=["deployed", "template"])
    def test_help_names_the_journal_mode_and_its_arguments(self, script: Path) -> None:
        result = subprocess.run(
            ["bash", str(script), "--help"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_SHELL_TIMEOUT,
        )

        assert result.returncode == 0, result.stderr
        assert "--journal <plan-number> <category> <body-file>" in result.stderr
        assert "UTC" in result.stderr
        for category in (
            "action",
            "finding",
            "decision",
            "thought",
            "blocker",
            "handoff",
            "correction",
        ):
            assert category in result.stderr


class TestScaffoldSeedsAnEntryFile:
    """Plan 00543: a new plan's seeded `plan scaffolded` entry is an entry file."""

    def test_a_scaffolded_plan_has_one_seed_entry_file_and_no_day_file(
        self, plan_repo: Path
    ) -> None:
        result = _run(plan_repo, "scaffold-seed-check")
        assert result.returncode == 0, result.stderr

        (plan_folder,) = (plan_repo / "CLAUDE" / "Plan").glob("*-scaffold-seed-check")
        journal = plan_folder / "JOURNAL"
        assert list(journal.glob("*-Journal-*.md")) == []
        (seed,) = journal.glob("*/*.md")
        assert _DAY_FOLDER_NAME.match(seed.parent.name)
        name = _ENTRY_FILE_NAME.match(seed.name)
        assert name is not None and name.group(4) == "action", seed.name
        lines = seed.read_text().splitlines()
        heading = _ENTRY_HEADING.match(lines[0])
        assert heading is not None and heading.group(3) == "action"
        assert (heading.group(1), heading.group(2)) == (name.group(1), name.group(2))
        assert "plan scaffolded" in lines[0]
        assert "{{" not in seed.read_text()


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", message)


class TestSameDayJournallingOnTwoBranchesMergesCleanly:
    """Plan 00543 Task 2.4: the point of the layout, shown with real git.

    Two branches journal the SAME plan on the SAME UTC day (same category too,
    the worst case for a name clash). With one file per day that is the
    conflict #135 reports; with one NEW file per entry the three-way merge adds
    two files and `git merge-tree --write-tree` exits 0 with a tree.
    """

    @staticmethod
    def _journal_on_branch(repo: Path, branch: str, text: str) -> None:
        _git(repo, "checkout", "--quiet", "-b", branch, "base")
        body = repo / f"{branch}-body.txt"
        body.write_text(text)
        result = _run(repo, "--journal", "42", "action", str(body))
        assert result.returncode == 0, result.stderr
        body.unlink()
        _commit_all(repo, f"journal on {branch}")

    @staticmethod
    def _merge_tree(repo: Path, left: str, right: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(repo), "merge-tree", "--write-tree", left, right],
            capture_output=True,
            text=True,
            check=False,
            timeout=_SHELL_TIMEOUT,
        )

    def test_two_branches_journalling_the_same_day_merge_without_conflict(
        self, plan_repo: Path
    ) -> None:
        _make_plan(plan_repo, "00042", "sample-plan")
        _commit_all(plan_repo, "base")
        _git(plan_repo, "branch", "base")

        self._journal_on_branch(plan_repo, "branch-a", "Written on branch A.\n")
        self._journal_on_branch(plan_repo, "branch-b", "Written on branch B.\n")
        merged = self._merge_tree(plan_repo, "branch-a", "branch-b")

        assert merged.returncode == 0, merged.stdout + merged.stderr
        tree = merged.stdout.splitlines()[0]
        listing = _git(plan_repo, "ls-tree", "-r", "--name-only", tree)
        entries = [line for line in listing.splitlines() if "/JOURNAL/" in line]
        assert len(entries) == 2, entries
        assert len({Path(line).parent for line in map(Path, entries)}) == 1, "one shared day folder"

    def test_a_legacy_day_file_on_the_base_does_not_make_the_merge_conflict(
        self, plan_repo: Path
    ) -> None:
        import datetime

        folder = _make_plan(plan_repo, "00042", "sample-plan")
        (folder / "JOURNAL").mkdir()
        today = datetime.datetime.now(datetime.UTC).strftime("%y-%m-%d")
        (folder / "JOURNAL" / f"00042-Journal-{today}.md").write_text(
            "# Plan 00042 — Journal\n\n## 00:00 · finding · —\n\nBefore the switch.\n"
        )
        _commit_all(plan_repo, "base")
        _git(plan_repo, "branch", "base")

        self._journal_on_branch(plan_repo, "branch-a", "A.\n")
        self._journal_on_branch(plan_repo, "branch-b", "B.\n")
        merged = self._merge_tree(plan_repo, "branch-a", "branch-b")

        assert merged.returncode == 0, merged.stdout + merged.stderr
