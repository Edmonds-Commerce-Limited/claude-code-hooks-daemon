"""Tests for the shared subagent report persistence primitives (Plan 00460 Task 1.6).

The daemon persists EVERY sub-agent's ``last_assistant_message`` to a
gitignored, bounded location at SubagentStop. This module holds the pure,
reusable pieces both the persister handler and the size blocker need:
filename rendering, a never-overwrite atomic writer, and a glob-based
lookup the size blocker uses to find what the persister already saved
without any cross-handler in-memory coupling.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from claude_code_hooks_daemon.utils.subagent_report_paths import (
    DEFAULT_PERSISTED_REPORT_DIR,
    DEFAULT_REPORT_DIR,
    find_persisted_report,
    report_filename,
    resolve_confined_report_dir,
    write_new_file_never_overwrite,
)

# tests/unit/utils/test_subagent_report_paths.py -> repo root, same idiom as
# tests/integration/test_deployed_skill_trees.py's REPO_ROOT.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_GIT = shutil.which("git") or "git"


class TestReportFilename:
    def test_renders_the_documented_shape(self) -> None:
        when = datetime(2026, 9, 24, 13, 45, 30, tzinfo=UTC)
        assert (
            report_filename("Explore", "agent-1", when=when) == "260924-134530-Explore-agent-1.md"
        )

    def test_sanitises_unsafe_characters_in_agent_type(self) -> None:
        """A plugin-scoped agent type such as ``my-plugin:review:security``
        must not put a path separator or colon into the filename."""
        when = datetime(2026, 9, 24, 13, 45, 30, tzinfo=UTC)
        name = report_filename("my-plugin:review:security", "agent-1", when=when)
        assert "/" not in name
        assert ":" not in name

    def test_falls_back_to_placeholder_for_empty_agent_type(self) -> None:
        when = datetime(2026, 9, 24, 13, 45, 30, tzinfo=UTC)
        name = report_filename("", "agent-1", when=when)
        assert "unknown-agent-type" in name

    def test_falls_back_to_placeholder_for_empty_agent_id(self) -> None:
        when = datetime(2026, 9, 24, 13, 45, 30, tzinfo=UTC)
        name = report_filename("Explore", "", when=when)
        assert "unknown-agent-id" in name


class TestWriteNewFileNeverOverwrite:
    def test_writes_content_to_a_new_file(self, tmp_path: Path) -> None:
        path = write_new_file_never_overwrite(tmp_path, "report.md", "hello")

        assert path is not None
        assert path.read_text() == "hello"

    def test_creates_the_directory_if_missing(self, tmp_path: Path) -> None:
        target_dir = tmp_path / "nested" / "agent-reports"

        path = write_new_file_never_overwrite(target_dir, "report.md", "hello")

        assert path is not None
        assert path.parent == target_dir

    def test_never_overwrites_an_existing_file(self, tmp_path: Path) -> None:
        first = write_new_file_never_overwrite(tmp_path, "report.md", "first")
        second = write_new_file_never_overwrite(tmp_path, "report.md", "second")

        assert first is not None
        assert second is not None
        assert first != second
        assert first.read_text() == "first"
        assert second.read_text() == "second"

    def test_collision_uses_a_numeric_suffix(self, tmp_path: Path) -> None:
        write_new_file_never_overwrite(tmp_path, "report.md", "first")
        second = write_new_file_never_overwrite(tmp_path, "report.md", "second")

        assert second is not None
        assert second.name == "report-2.md"

    def test_third_collision_increments_the_suffix(self, tmp_path: Path) -> None:
        write_new_file_never_overwrite(tmp_path, "report.md", "first")
        write_new_file_never_overwrite(tmp_path, "report.md", "second")
        third = write_new_file_never_overwrite(tmp_path, "report.md", "third")

        assert third is not None
        assert third.name == "report-3.md"

    def test_returns_none_when_the_directory_cannot_be_created(self, tmp_path: Path) -> None:
        # A FILE where a directory is expected: mkdir(parents=True) raises.
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")

        path = write_new_file_never_overwrite(blocker / "sub", "report.md", "content")

        assert path is None

    def test_writes_a_self_ignoring_gitignore_into_a_fresh_repo_with_no_ignore_rule(
        self, tmp_path: Path
    ) -> None:
        """Review finding B1: the ONLY prior evidence that persisted reports
        are gitignored was a test against THIS repo's own `.gitignore` --
        nothing enforced it at runtime in a client repo with no matching
        rule. `git init` here with no `.gitignore` at all, mirroring a fresh
        client checkout, then assert the write is genuinely uncommittable."""
        subprocess.run([_GIT, "init", "-q"], cwd=tmp_path, check=True)
        target_dir = tmp_path / "untracked" / "agent-reports" / "auto"

        written = write_new_file_never_overwrite(target_dir, "report.md", "secret content")

        assert written is not None
        result = subprocess.run(
            [_GIT, "-C", str(tmp_path), "check-ignore", "-q", str(written)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert (
            result.returncode == 0
        ), "the written file must be gitignored, not just the string prefix"

    def test_the_gitignored_file_survives_git_add_dash_a(self, tmp_path: Path) -> None:
        """The same B1 guarantee, proven the way the failure scenario in the
        review describes it: `git add -A && git status` must show nothing
        under the report directory, in a repo with no prior ignore rule."""
        subprocess.run([_GIT, "init", "-q"], cwd=tmp_path, check=True)
        target_dir = tmp_path / "untracked" / "agent-reports" / "auto"
        write_new_file_never_overwrite(target_dir, "report.md", "a credential, say")

        subprocess.run([_GIT, "add", "-A"], cwd=tmp_path, check=True)
        status = subprocess.run(
            [_GIT, "-C", str(tmp_path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )

        assert "report.md" not in status.stdout

    def test_does_not_overwrite_an_existing_gitignore(self, tmp_path: Path) -> None:
        """A directory some earlier version already wrote to (or a project
        that hand-placed its own `.gitignore` there) must not have its
        content clobbered on every write."""
        target_dir = tmp_path / "agent-reports"
        target_dir.mkdir()
        (target_dir / ".gitignore").write_text("custom\n")

        write_new_file_never_overwrite(target_dir, "report.md", "x")

        assert (target_dir / ".gitignore").read_text() == "custom\n"

    def test_created_file_is_owner_only_mode(self, tmp_path: Path) -> None:
        """Review m8: persisted replies can carry sensitive material, so the
        file must land 0600, matching the 0600 hand-authored reports already
        in this directory (and `retention.cap_log_file`'s same convention)."""
        written = write_new_file_never_overwrite(tmp_path, "report.md", "x")

        assert written is not None
        assert (written.stat().st_mode & 0o777) == 0o600

    def test_created_directory_is_owner_only_mode(self, tmp_path: Path) -> None:
        target_dir = tmp_path / "agent-reports"

        write_new_file_never_overwrite(target_dir, "report.md", "x")

        assert (target_dir.stat().st_mode & 0o777) == 0o700

    def test_removes_a_partial_file_when_the_content_write_fails(self, tmp_path: Path) -> None:
        """Review m3: an `OSError` from `handle.write` after `O_CREAT|O_EXCL`
        already succeeded must not leave a truncated file behind -- it would
        later be cited by `find_persisted_report` (m2) and count against
        retention as if it were a real, complete reply."""
        with patch("os.fdopen") as mock_fdopen:
            mock_fdopen.side_effect = OSError("disk full")

            written = write_new_file_never_overwrite(tmp_path, "report.md", "content")

        assert written is None
        assert list(tmp_path.glob("*.md")) == []


class TestFindPersistedReport:
    def test_finds_a_report_matching_agent_type_and_id(self, tmp_path: Path) -> None:
        (tmp_path / "260924-134530-Explore-agent-1.md").write_text("x")

        found = find_persisted_report(tmp_path, "Explore", "agent-1")

        assert found == tmp_path / "260924-134530-Explore-agent-1.md"

    def test_returns_none_when_nothing_matches(self, tmp_path: Path) -> None:
        (tmp_path / "260924-134530-Explore-agent-1.md").write_text("x")

        assert find_persisted_report(tmp_path, "Explore", "agent-2") is None

    def test_returns_none_when_directory_is_missing(self, tmp_path: Path) -> None:
        assert find_persisted_report(tmp_path / "does-not-exist", "Explore", "agent-1") is None

    def test_matches_a_collision_suffixed_filename(self, tmp_path: Path) -> None:
        (tmp_path / "260924-134530-Explore-agent-1-2.md").write_text("x")

        found = find_persisted_report(tmp_path, "Explore", "agent-1")

        assert found is not None

    def test_returns_none_for_empty_agent_id(self, tmp_path: Path) -> None:
        (tmp_path / "260924-134530-Explore-agent-1.md").write_text("x")

        assert find_persisted_report(tmp_path, "Explore", "") is None

    def test_picks_the_most_recent_match_when_more_than_one_exists(self, tmp_path: Path) -> None:
        (tmp_path / "260924-090000-Explore-agent-1.md").write_text("older")
        (tmp_path / "260924-150000-Explore-agent-1.md").write_text("newer")

        found = find_persisted_report(tmp_path, "Explore", "agent-1")

        assert found == tmp_path / "260924-150000-Explore-agent-1.md"

    def test_picks_by_mtime_not_lexicographic_filename_order(self, tmp_path: Path) -> None:
        """Review m1: `-` (0x2d) sorts before `.` (0x2e), so a plain
        lexicographic sort puts a collision-suffixed `...-agent-1-2.md`
        BEFORE the unsuffixed original `...-agent-1.md` -- exactly backwards
        from write order, since the suffixed file is always the NEWER one.
        Same file names, deliberately identical timestamp-looking prefixes,
        only the mtimes differ, to isolate the sort key from the name."""
        original = tmp_path / "260924-090000-Explore-agent-1.md"
        suffixed = tmp_path / "260924-090000-Explore-agent-1-2.md"
        original.write_text("first")
        suffixed.write_text("second, actually newer")
        old_time = datetime(2026, 9, 24, 9, 0, 0, tzinfo=UTC).timestamp()
        new_time = datetime(2026, 9, 24, 9, 0, 5, tzinfo=UTC).timestamp()
        os.utime(original, (old_time, old_time))
        os.utime(suffixed, (new_time, new_time))

        found = find_persisted_report(tmp_path, "Explore", "agent-1")

        assert found == suffixed

    def test_picks_by_mtime_even_against_a_double_digit_suffix(self, tmp_path: Path) -> None:
        """Same defect, the other direction: lexicographic order also puts
        `-10` before `-2` (`'1' < '2'`), which is backwards from write order
        too."""
        second = tmp_path / "260924-090000-Explore-agent-1-2.md"
        tenth = tmp_path / "260924-090000-Explore-agent-1-10.md"
        second.write_text("2nd write")
        tenth.write_text("10th write, actually newest")
        base_time = datetime(2026, 9, 24, 9, 0, 0, tzinfo=UTC).timestamp()
        os.utime(second, (base_time, base_time))
        os.utime(tenth, (base_time + 10, base_time + 10))

        found = find_persisted_report(tmp_path, "Explore", "agent-1")

        assert found == tenth


class TestResolveConfinedReportDir:
    """Review M1: `report_dir` arrives from YAML, unvalidated. An empty,
    `.`, absolute or `..`-escaping value must never resolve to a real
    target -- doing so lets persistence write, and retention PRUNE, outside
    the intended tree (probes P2/P3 in the review: README.md deleted,
    files written outside the project root)."""

    def test_resolves_a_normal_relative_dir_under_root(self, tmp_path: Path) -> None:
        resolved = resolve_confined_report_dir(tmp_path, "untracked/agent-reports/auto")

        assert resolved == (tmp_path / "untracked" / "agent-reports" / "auto").resolve()

    def test_rejects_empty_string(self, tmp_path: Path) -> None:
        assert resolve_confined_report_dir(tmp_path, "") is None

    def test_rejects_dot(self, tmp_path: Path) -> None:
        assert resolve_confined_report_dir(tmp_path, ".") is None

    def test_rejects_dot_slash(self, tmp_path: Path) -> None:
        assert resolve_confined_report_dir(tmp_path, "./") is None

    def test_rejects_an_absolute_path(self, tmp_path: Path) -> None:
        assert resolve_confined_report_dir(tmp_path, "/etc") is None

    def test_rejects_a_parent_escaping_path(self, tmp_path: Path) -> None:
        assert resolve_confined_report_dir(tmp_path, "../outside") is None

    def test_rejects_a_path_that_escapes_via_a_later_segment(self, tmp_path: Path) -> None:
        assert resolve_confined_report_dir(tmp_path, "untracked/../../outside") is None

    def test_rejects_the_root_itself(self, tmp_path: Path) -> None:
        assert resolve_confined_report_dir(tmp_path, ".") is None


class TestDefaultReportDir:
    def test_is_under_untracked(self) -> None:
        assert DEFAULT_REPORT_DIR.startswith("untracked/")

    def test_is_actually_gitignored_in_this_repo(self) -> None:
        """Plan 00460 Task 1.6 pins this as a fact about THIS repo's
        `.gitignore`, not just a naming convention -- a string starting with
        "untracked/" would pass the sibling test above even if the pattern
        were ever narrowed to spare some of that tree."""
        probe = _REPO_ROOT / DEFAULT_REPORT_DIR / "probe.md"
        result = subprocess.run(
            [_GIT, "-C", str(_REPO_ROOT), "check-ignore", "-q", str(probe)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"{DEFAULT_REPORT_DIR} is not gitignored in {_REPO_ROOT} -- "
            "subagent_report_persistence would leak agent replies into git status"
        )


class TestDefaultPersistedReportDir:
    """Review B2: the persister must write into its OWN subdirectory, never
    the shared `untracked/agent-reports/` an agent or a coordinator is told
    to hand-author reports into -- otherwise retention prunes deliberate
    deliverables (22 of them existed in this checkout at review time)."""

    def test_is_nested_under_the_shared_report_dir(self) -> None:
        assert DEFAULT_PERSISTED_REPORT_DIR.startswith(DEFAULT_REPORT_DIR)
        assert DEFAULT_PERSISTED_REPORT_DIR != DEFAULT_REPORT_DIR

    def test_is_actually_gitignored_in_this_repo(self) -> None:
        probe = _REPO_ROOT / DEFAULT_PERSISTED_REPORT_DIR / "probe.md"
        result = subprocess.run(
            [_GIT, "-C", str(_REPO_ROOT), "check-ignore", "-q", str(probe)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
