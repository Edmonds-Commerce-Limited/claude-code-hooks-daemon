"""The sanctioned scratch directory is created, not assumed (Plan 00333).

`project_containment` denies a write outside the repository root and points the
agent at `untracked/scratch/`. In a project where that directory does not exist,
the guidance names nothing — the guard would block a real need and offer a path
that is not there. Owner ruling: create it, and make sure it is ignored.

Two properties matter and are asserted separately, because a directory that
exists but is TRACKED is worse than no directory at all: scratch would then flow
into review and history.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.utils.scratch_dir import (
    SCRATCH_IGNORE_CONTENT,
    ensure_scratch_dir,
)


class TestItCreatesWhatIsMissing:
    def test_the_scratch_directory_is_created(self, tmp_path: Path) -> None:
        ensure_scratch_dir(tmp_path)

        assert (tmp_path / "untracked" / "scratch").is_dir()

    def test_the_parent_is_created_too(self, tmp_path: Path) -> None:
        ensure_scratch_dir(tmp_path)

        assert (tmp_path / "untracked").is_dir()

    def test_an_ignore_file_is_written(self, tmp_path: Path) -> None:
        ensure_scratch_dir(tmp_path)

        assert (tmp_path / "untracked" / ".gitignore").read_text(
            encoding="utf-8"
        ) == SCRATCH_IGNORE_CONTENT

    def test_the_ignore_file_ignores_everything_but_itself(self, tmp_path: Path) -> None:
        """The two lines are the whole point: `*` keeps scratch out of git, and
        `!.gitignore` keeps the rule itself tracked so the next checkout has it."""
        ensure_scratch_dir(tmp_path)
        lines = SCRATCH_IGNORE_CONTENT.split()

        assert "*" in lines
        assert "!.gitignore" in lines

    def test_it_reports_that_it_acted(self, tmp_path: Path) -> None:
        assert ensure_scratch_dir(tmp_path) is True


class TestItIsIdempotent:
    def test_a_second_call_reports_no_change(self, tmp_path: Path) -> None:
        ensure_scratch_dir(tmp_path)

        assert ensure_scratch_dir(tmp_path) is False

    def test_a_second_call_does_not_raise(self, tmp_path: Path) -> None:
        ensure_scratch_dir(tmp_path)
        ensure_scratch_dir(tmp_path)

        assert (tmp_path / "untracked" / "scratch").is_dir()


class TestItNeverDestroys:
    def test_an_existing_ignore_file_is_left_alone(self, tmp_path: Path) -> None:
        """A project may already ignore `untracked/` from the repo root, or have
        its own rules here. Overwriting them would be a silent policy change,
        and the daemon has no business making one."""
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        existing = untracked / ".gitignore"
        existing.write_text("# hand-written\n*.log\n", encoding="utf-8")

        ensure_scratch_dir(tmp_path)

        assert existing.read_text(encoding="utf-8") == "# hand-written\n*.log\n"

    def test_existing_scratch_content_survives(self, tmp_path: Path) -> None:
        scratch = tmp_path / "untracked" / "scratch"
        scratch.mkdir(parents=True)
        kept = scratch / "notes.md"
        kept.write_text("# in progress", encoding="utf-8")

        ensure_scratch_dir(tmp_path)

        assert kept.read_text(encoding="utf-8") == "# in progress"

    def test_it_creates_the_ignore_file_when_only_the_directory_exists(
        self, tmp_path: Path
    ) -> None:
        """The half-built case: a project with an `untracked/` directory that
        nothing ignores. Leaving it would let scratch reach review."""
        (tmp_path / "untracked").mkdir()

        assert ensure_scratch_dir(tmp_path) is True
        assert (tmp_path / "untracked" / ".gitignore").is_file()
