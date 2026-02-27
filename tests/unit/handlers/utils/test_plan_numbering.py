"""Tests for plan numbering utility."""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.handlers.utils.plan_numbering import get_next_plan_number


class TestGetNextPlanNumber:
    """Tests for get_next_plan_number function."""

    @pytest.fixture
    def temp_plan_dir(self, tmp_path: Path) -> Path:
        """Create temporary plan directory."""
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        plan_dir.mkdir(parents=True)
        return plan_dir

    def test_returns_00001_for_empty_directory(self, temp_plan_dir: Path) -> None:
        """First plan number is 00001 when directory is empty."""
        result = get_next_plan_number(temp_plan_dir)
        assert result == "00001"

    def test_returns_00002_when_one_plan_exists(self, temp_plan_dir: Path) -> None:
        """Second plan number is 00002 when one plan exists."""
        (temp_plan_dir / "00001-first-plan").mkdir()
        result = get_next_plan_number(temp_plan_dir)
        assert result == "00002"

    def test_returns_00003_when_two_plans_exist(self, temp_plan_dir: Path) -> None:
        """Third plan number is 00003 when two plans exist."""
        (temp_plan_dir / "00001-first-plan").mkdir()
        (temp_plan_dir / "00002-second-plan").mkdir()
        result = get_next_plan_number(temp_plan_dir)
        assert result == "00003"

    def test_handles_non_sequential_numbers(self, temp_plan_dir: Path) -> None:
        """Returns next number after highest, even if not sequential."""
        (temp_plan_dir / "00001-first-plan").mkdir()
        (temp_plan_dir / "00005-fifth-plan").mkdir()
        (temp_plan_dir / "00003-third-plan").mkdir()
        result = get_next_plan_number(temp_plan_dir)
        assert result == "00006"

    def test_ignores_non_numbered_directories(self, temp_plan_dir: Path) -> None:
        """Ignores directories that don't start with digits."""
        (temp_plan_dir / "00001-first-plan").mkdir()
        (temp_plan_dir / "archive").mkdir()
        (temp_plan_dir / "templates").mkdir()
        result = get_next_plan_number(temp_plan_dir)
        assert result == "00002"

    def test_scans_subdirectories_for_archived_plans(self, temp_plan_dir: Path) -> None:
        """Scans non-numbered subdirectories for archived plans."""
        (temp_plan_dir / "00001-first-plan").mkdir()
        archive_dir = temp_plan_dir / "archive"
        archive_dir.mkdir()
        (archive_dir / "00002-archived-plan").mkdir()
        (archive_dir / "00003-another-archived").mkdir()
        result = get_next_plan_number(temp_plan_dir)
        assert result == "00004"

    def test_excludes_numbered_subdirectories_from_scan(self, temp_plan_dir: Path) -> None:
        """Does not scan subdirectories that start with digits (they are plans)."""
        (temp_plan_dir / "00001-first-plan").mkdir()
        # Create a numbered subdirectory (should NOT be scanned)
        nested_plan = temp_plan_dir / "00002-plan-with-subdir"
        nested_plan.mkdir()
        (nested_plan / "00999-nested").mkdir()  # Should be ignored
        result = get_next_plan_number(temp_plan_dir)
        assert result == "00003"

    def test_handles_files_in_directory(self, temp_plan_dir: Path) -> None:
        """Ignores files when scanning for plan numbers."""
        (temp_plan_dir / "00001-first-plan").mkdir()
        (temp_plan_dir / "README.md").touch()
        (temp_plan_dir / "00002-notes.txt").touch()
        result = get_next_plan_number(temp_plan_dir)
        assert result == "00002"

    def test_handles_three_digit_legacy_numbers(self, temp_plan_dir: Path) -> None:
        """Handles legacy three-digit plan numbers correctly."""
        (temp_plan_dir / "001-legacy-plan").mkdir()
        (temp_plan_dir / "002-another-legacy").mkdir()
        result = get_next_plan_number(temp_plan_dir)
        assert result == "00003"

    def test_pads_to_five_digits(self, temp_plan_dir: Path) -> None:
        """Always returns five-digit zero-padded string."""
        (temp_plan_dir / "00099-plan-99").mkdir()
        result = get_next_plan_number(temp_plan_dir)
        assert result == "00100"
        assert len(result) == 5

    def test_handles_large_plan_numbers(self, temp_plan_dir: Path) -> None:
        """Handles large plan numbers correctly."""
        (temp_plan_dir / "09999-huge-plan").mkdir()
        result = get_next_plan_number(temp_plan_dir)
        assert result == "10000"
        assert len(result) == 5

    def test_raises_error_for_nonexistent_directory(self) -> None:
        """Raises FileNotFoundError if plan directory does not exist."""
        nonexistent = Path("/nonexistent/path/to/plans")
        with pytest.raises(FileNotFoundError, match="Plan directory does not exist"):
            get_next_plan_number(nonexistent)

    def test_handles_deeply_nested_archive_structure(self, temp_plan_dir: Path) -> None:
        """Scans deeply nested archive directories for plan numbers."""
        (temp_plan_dir / "00001-first-plan").mkdir()
        archive_dir = temp_plan_dir / "archive" / "2025" / "completed"
        archive_dir.mkdir(parents=True)
        (archive_dir / "00002-old-plan").mkdir()
        (archive_dir / "00005-another-old").mkdir()
        result = get_next_plan_number(temp_plan_dir)
        assert result == "00006"

    def test_handles_symlink_to_directory(self, temp_plan_dir: Path) -> None:
        """Handles symbolic links to directories."""
        (temp_plan_dir / "00001-first-plan").mkdir()
        target_dir = temp_plan_dir / "target"
        target_dir.mkdir()
        (target_dir / "00002-in-target").mkdir()
        symlink = temp_plan_dir / "link-to-target"
        symlink.symlink_to(target_dir)
        result = get_next_plan_number(temp_plan_dir)
        # Should scan symlink and find 00002
        assert result == "00003"

    def test_handles_broken_symlink(self, temp_plan_dir: Path) -> None:
        """Handles broken symbolic links gracefully."""
        (temp_plan_dir / "00001-first-plan").mkdir()
        # Create symlink to non-existent target
        symlink = temp_plan_dir / "broken-link"
        symlink.symlink_to(temp_plan_dir / "nonexistent")
        result = get_next_plan_number(temp_plan_dir)
        # Should ignore broken symlink
        assert result == "00002"

    def test_handles_empty_non_numbered_subdirectory(self, temp_plan_dir: Path) -> None:
        """Handles empty non-numbered subdirectories."""
        (temp_plan_dir / "00001-first-plan").mkdir()
        (temp_plan_dir / "archive").mkdir()
        (temp_plan_dir / "templates").mkdir()
        result = get_next_plan_number(temp_plan_dir)
        assert result == "00002"

    def test_scan_directory_skips_non_directory_entries(self, temp_plan_dir: Path) -> None:
        """scan_directory skips entries that are not directories (files, etc.)."""
        # Create an archive dir with a plan inside and a file alongside it
        archive = temp_plan_dir / "archive"
        archive.mkdir()
        (archive / "00003-archived-plan").mkdir()
        # Place a file directly in archive - should be ignored by the dir check
        (archive / "README.md").write_text("notes")
        result = get_next_plan_number(temp_plan_dir)
        assert result == "00004"
