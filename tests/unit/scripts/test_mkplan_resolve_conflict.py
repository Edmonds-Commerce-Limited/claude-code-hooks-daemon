"""``CLAUDE/Plan/mkplan.bash --resolve-conflict`` — ledger 00474 N345 (RED first).

Two branches that each append an entry to the same JOURNAL day-file conflict
on merge. No hand edit can resolve that (``plan_qa_edit`` and
``plan_journal_guard`` refuse it) and ``git checkout --ours`` silently drops
the other side's entries. ``--resolve-conflict <day-file>`` is the sanctioned
route: it writes the UNION of both sides' entries in time order and stages it.

Exercised as a real ``bash`` subprocess against a real temporary git
repository with a genuine merge conflict, because the mode reads git's index
stages.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout

_SHELL_TIMEOUT = Timeout.VALIDATION_CHECK

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "CLAUDE" / "Plan" / "mkplan.bash"

_PLAN_FOLDER = "CLAUDE/Plan/00042-sample-plan"
_PAST_DAYFILE = f"{_PLAN_FOLDER}/JOURNAL/00042-Journal-26-10-03.md"

_HEADER = (
    "# Plan 00042 — Journal 26-10-03\n"
    "\n"
    "_Scaffolded by `mkplan.bash`; timestamps in this file are UTC._\n"
    "\n"
    "> **Append-only activity log** for plan 00042.\n"
)


def _entry(time: str, body: str, category: str = "action", ref: str = "—") -> str:
    return f"\n## {time} · {category} · {ref}\n\n{body}\n"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=check,
        timeout=_SHELL_TIMEOUT,
    )


def _resolve(repo: Path, dayfile: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(repo / "CLAUDE" / "Plan" / "mkplan.bash"), "--resolve-conflict", dayfile],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo,
        timeout=_SHELL_TIMEOUT,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo carrying the real scaffolder, ready to hold a day-file."""
    plan_dir = tmp_path / "CLAUDE" / "Plan"
    plan_dir.mkdir(parents=True)
    target = plan_dir / _SCRIPT.name
    target.write_bytes(_SCRIPT.read_bytes())
    target.chmod(0o755)
    (tmp_path / _PLAN_FOLDER / "JOURNAL").mkdir(parents=True)
    (tmp_path / _PLAN_FOLDER / "PLAN.md").write_text("# Plan 00042\n")

    _git(tmp_path, "init", "--quiet", "--initial-branch=main")
    _git(tmp_path, "config", "user.email", "journal-tester@test.invalid")
    _git(tmp_path, "config", "user.name", "Journal Tester")
    return tmp_path


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", message)


def _conflict(repo: Path, base: str, ours: str, theirs: str, dayfile: str = _PAST_DAYFILE) -> None:
    """Leave ``repo`` mid-merge: main holds ``ours``, branch ``other`` holds ``theirs``."""
    path = repo / dayfile
    path.write_text(base)
    _commit_all(repo, "base")
    _git(repo, "checkout", "--quiet", "-b", "other")
    path.write_text(theirs)
    _commit_all(repo, "theirs")
    _git(repo, "checkout", "--quiet", "main")
    path.write_text(ours)
    _commit_all(repo, "ours")
    merged = _git(repo, "merge", "--no-ff", "--no-edit", "other", check=False)
    assert merged.returncode != 0, "the fixture must produce a genuine merge conflict"
    assert "<<<<<<<" in path.read_text()


def _unmerged(repo: Path) -> str:
    return _git(repo, "ls-files", "--unmerged").stdout.strip()


class TestUnion:
    def test_past_day_file_keeps_both_sides_in_time_order(self, repo: Path) -> None:
        base = _HEADER + _entry("09:00", "Shared entry.")
        ours = base + _entry("10:00", "Main's entry.")
        theirs = base + _entry("09:30", "Branch's entry.")
        _conflict(repo, base, ours, theirs)

        result = _resolve(repo, _PAST_DAYFILE)

        assert result.returncode == 0, result.stderr
        expected = (
            _HEADER
            + _entry("09:00", "Shared entry.")
            + _entry("09:30", "Branch's entry.")
            + _entry("10:00", "Main's entry.")
        )
        assert (repo / _PAST_DAYFILE).read_text() == expected
        assert _unmerged(repo) == "", "the resolved day-file must be staged"

    def test_equal_stamps_keep_ours_first_and_both_bodies(self, repo: Path) -> None:
        base = _HEADER + _entry("09:00", "Shared entry.")
        ours = base + _entry("10:00", "From main.")
        theirs = base + _entry("10:00", "From the branch.")
        _conflict(repo, base, ours, theirs)

        result = _resolve(repo, _PAST_DAYFILE)

        assert result.returncode == 0, result.stderr
        text = (repo / _PAST_DAYFILE).read_text()
        assert text == (
            _HEADER
            + _entry("09:00", "Shared entry.")
            + _entry("10:00", "From main.")
            + _entry("10:00", "From the branch.")
        )

    def test_byte_identical_entries_appear_once(self, repo: Path) -> None:
        base = _HEADER + _entry("09:00", "Shared entry.")
        same = _entry("10:00", "Recorded on both sides.")
        ours = base + same + _entry("10:30", "Only main.")
        theirs = base + same + _entry("10:15", "Only the branch.")
        _conflict(repo, base, ours, theirs)

        result = _resolve(repo, _PAST_DAYFILE)

        assert result.returncode == 0, result.stderr
        text = (repo / _PAST_DAYFILE).read_text()
        assert text.count("Recorded on both sides.") == 1
        assert text.index("10:15") < text.index("10:30")

    def test_fenced_entry_lookalikes_stay_inside_their_entry(self, repo: Path) -> None:
        fenced = _entry("10:00", "Quoted log:\n\n```\n## 09:00 · fake · —\nnot an entry\n```")
        base = _HEADER
        ours = base + fenced
        theirs = base + _entry("09:30", "Branch.")
        _conflict(repo, base, ours, theirs)

        result = _resolve(repo, _PAST_DAYFILE)

        assert result.returncode == 0, result.stderr
        assert (repo / _PAST_DAYFILE).read_text() == (
            _HEADER + _entry("09:30", "Branch.") + fenced
        )

    def test_add_add_conflict_with_no_common_base(self, repo: Path) -> None:
        """Both branches create the day-file: git has no stage 1."""
        path = repo / _PAST_DAYFILE
        (repo / "README.md").write_text("x\n")
        (repo / _PLAN_FOLDER / "JOURNAL" / ".gitkeep").write_text("")
        _commit_all(repo, "base")
        _git(repo, "checkout", "--quiet", "-b", "other")
        path.write_text(_HEADER + _entry("09:30", "Branch."))
        _commit_all(repo, "theirs")
        _git(repo, "checkout", "--quiet", "main")
        path.write_text(_HEADER + _entry("10:00", "Main."))
        _commit_all(repo, "ours")
        assert _git(repo, "merge", "--no-edit", "other", check=False).returncode != 0

        result = _resolve(repo, _PAST_DAYFILE)

        assert result.returncode == 0, result.stderr
        assert (repo / _PAST_DAYFILE).read_text() == (
            _HEADER + _entry("09:30", "Branch.") + _entry("10:00", "Main.")
        )
        assert _unmerged(repo) == ""

    def test_markers_in_the_working_file_are_read_when_there_are_no_stages(
        self, repo: Path
    ) -> None:
        path = repo / _PAST_DAYFILE
        path.write_text(
            _HEADER
            + _entry("09:00", "Shared entry.")
            + "\n<<<<<<< HEAD\n"
            + _entry("10:00", "Main.").lstrip("\n")
            + "=======\n"
            + _entry("09:30", "Branch.").lstrip("\n")
            + ">>>>>>> other\n"
        )
        _commit_all(repo, "file carrying markers")
        assert _unmerged(repo) == ""

        result = _resolve(repo, _PAST_DAYFILE)

        assert result.returncode == 0, result.stderr
        assert (repo / _PAST_DAYFILE).read_text() == (
            _HEADER
            + _entry("09:00", "Shared entry.")
            + _entry("09:30", "Branch.")
            + _entry("10:00", "Main.")
        )
        assert "<<<<<<<" not in (repo / _PAST_DAYFILE).read_text()


class TestRefusals:
    """Every refusal exits non-zero with a clear message and leaves the file alone."""

    def test_refuses_a_path_that_is_not_a_journal_day_file(self, repo: Path) -> None:
        notes = repo / "CLAUDE" / "Plan" / "00042-sample-plan" / "NOTES.md"
        notes.write_text("<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> other\n")

        result = _resolve(repo, "CLAUDE/Plan/00042-sample-plan/NOTES.md")

        assert result.returncode != 0
        assert "day-file" in result.stderr
        assert "<<<<<<<" in notes.read_text()

    def test_refuses_when_there_is_no_conflict(self, repo: Path) -> None:
        path = repo / _PAST_DAYFILE
        path.write_text(_HEADER + _entry("09:00", "Fine."))
        _commit_all(repo, "clean")

        result = _resolve(repo, _PAST_DAYFILE)

        assert result.returncode != 0
        assert "no merge conflict" in result.stderr
        assert path.read_text() == _HEADER + _entry("09:00", "Fine.")

    def test_refuses_a_missing_file(self, repo: Path) -> None:
        result = _resolve(repo, _PAST_DAYFILE)

        assert result.returncode != 0
        assert "not found" in result.stderr

    def test_refuses_a_side_with_text_that_is_not_an_entry(self, repo: Path) -> None:
        base = _HEADER + _entry("09:00", "Shared entry.")
        ours = base + "\n## Notes\n\nfree text under a heading that is no entry\n"
        theirs = base + _entry("09:30", "Branch.")
        _conflict(repo, base, ours, theirs)
        before = (repo / _PAST_DAYFILE).read_text()

        result = _resolve(repo, _PAST_DAYFILE)

        assert result.returncode != 0
        assert "## Notes" in result.stderr
        assert (repo / _PAST_DAYFILE).read_text() == before
        assert _unmerged(repo) != "", "a refusal must not stage anything"

    def test_refuses_a_side_with_an_unclosed_fence(self, repo: Path) -> None:
        base = _HEADER + _entry("09:00", "Shared entry.")
        ours = base + _entry("10:00", "Open fence.\n\n```\nnever closed")
        theirs = base + _entry("09:30", "Branch.")
        _conflict(repo, base, ours, theirs)

        result = _resolve(repo, _PAST_DAYFILE)

        assert result.returncode != 0
        assert "fence" in result.stderr

    def test_refuses_when_the_two_headers_differ(self, repo: Path) -> None:
        base = _HEADER + _entry("09:00", "Shared entry.")
        ours = base + _entry("10:00", "Main.")
        theirs = base.replace("Append-only", "Rewritten header") + _entry("09:30", "Branch.")
        _conflict(repo, base, ours, theirs)

        result = _resolve(repo, _PAST_DAYFILE)

        assert result.returncode != 0
        assert "header" in result.stderr

    def test_refuses_a_conflict_where_one_side_deleted_the_file(self, repo: Path) -> None:
        path = repo / _PAST_DAYFILE
        base = _HEADER + _entry("09:00", "Shared entry.")
        path.write_text(base)
        _commit_all(repo, "base")
        _git(repo, "checkout", "--quiet", "-b", "other")
        _git(repo, "rm", "--quiet", _PAST_DAYFILE)
        _git(repo, "commit", "--quiet", "-m", "theirs deletes")
        _git(repo, "checkout", "--quiet", "main")
        path.write_text(base + _entry("10:00", "Main."))
        _commit_all(repo, "ours edits")
        assert _git(repo, "merge", "--no-edit", "other", check=False).returncode != 0

        result = _resolve(repo, _PAST_DAYFILE)

        assert result.returncode != 0
        assert "only one side" in result.stderr
