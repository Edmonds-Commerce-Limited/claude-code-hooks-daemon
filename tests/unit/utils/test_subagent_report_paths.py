"""Tests for the shared subagent report persistence primitives (Plan 00460 Task 1.6).

The daemon persists EVERY sub-agent's ``last_assistant_message`` to a
gitignored, bounded location at SubagentStop. This module holds the pure,
reusable pieces both the persister handler and the size blocker need:
filename rendering, a never-overwrite atomic writer, and a glob-based
lookup the size blocker uses to find what the persister already saved
without any cross-handler in-memory coupling.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from claude_code_hooks_daemon.utils.subagent_report_paths import (
    DEFAULT_REPORT_DIR,
    find_persisted_report,
    report_filename,
    write_new_file_never_overwrite,
)


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


class TestDefaultReportDir:
    def test_is_under_untracked(self) -> None:
        assert DEFAULT_REPORT_DIR.startswith("untracked/")
