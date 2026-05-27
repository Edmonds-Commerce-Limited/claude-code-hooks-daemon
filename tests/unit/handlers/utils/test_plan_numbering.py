"""Tests for plan numbering utility."""

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.handlers.utils.plan_numbering import (
    get_next_plan_number,
    next_plan_number_for_target,
    read_plan_counter,
    record_plan_allocation,
    resolve_plan_repo_root,
    write_plan_counter,
)


def _git_init(repo_root: Path) -> Path:
    """Initialise a git repo at ``repo_root`` and return it.

    Plain ``git init`` is enough — the plan counter lives in ``.git/config``
    via ``git config --local`` and needs no user identity or commits.
    """
    repo_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", str(repo_root)],
        capture_output=True,
        check=True,
        timeout=10,
    )
    return repo_root


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

    # Regression tests for date-directory false positive bug

    def test_date_directories_not_counted_as_plan_numbers(self, temp_plan_dir: Path) -> None:
        """Date-formatted dirs like 2026-01-12 must not be treated as plan numbers.

        Regression test: date dirs in legacy archives matched ^(\\d+)- regex,
        causing plan numbers to jump from ~32 to ~2027.
        """
        (temp_plan_dir / "00005-svc-some-feature").mkdir()
        legacy = temp_plan_dir / "legacy" / "old-stuff" / "2026-01-12"
        legacy.mkdir(parents=True)

        result = get_next_plan_number(temp_plan_dir)
        assert result == "00006"  # NOT "02027"

    def test_date_directories_at_top_level_not_counted(self, temp_plan_dir: Path) -> None:
        """Date-formatted dirs directly in plan folder must not match."""
        (temp_plan_dir / "00010-real-plan").mkdir()
        (temp_plan_dir / "2026-01-12").mkdir()
        (temp_plan_dir / "2026-01-13").mkdir()

        result = get_next_plan_number(temp_plan_dir)
        assert result == "00011"  # NOT "02027"

    def test_date_directories_in_nested_archive_not_counted(self, temp_plan_dir: Path) -> None:
        """Date dirs nested several levels deep in archives must not match."""
        (temp_plan_dir / "00032-latest-plan").mkdir()
        deep_archive = temp_plan_dir / "legacy" / "top-level" / "container-management"
        deep_archive.mkdir(parents=True)
        (deep_archive / "2026-01-12").mkdir()
        (deep_archive / "2026-01-13").mkdir()

        result = get_next_plan_number(temp_plan_dir)
        assert result == "00033"  # NOT "02027"

    def test_uppercase_plan_names_counted(self, temp_plan_dir: Path) -> None:
        """Plan dirs starting with uppercase letter after hyphen should match."""
        (temp_plan_dir / "00005-Feature-work").mkdir()
        (temp_plan_dir / "00010-Refactor-handlers").mkdir()

        result = get_next_plan_number(temp_plan_dir)
        assert result == "00011"

    def test_numeric_only_directories_not_counted(self, temp_plan_dir: Path) -> None:
        """Directories like '2025' (year only, no hyphen) should not match."""
        (temp_plan_dir / "00005-real-plan").mkdir()
        archive = temp_plan_dir / "archive"
        archive.mkdir()
        (archive / "2025").mkdir()

        result = get_next_plan_number(temp_plan_dir)
        assert result == "00006"


class TestResolvePlanRepoRoot:
    """Resolve the nearest enclosing git repo for a target path."""

    def test_resolves_repo_root_for_path_inside_repo(self, tmp_path: Path) -> None:
        repo = _git_init(tmp_path / "proj")
        target = repo / "CLAUDE" / "Plan" / "00001-x" / "PLAN.md"

        resolved = resolve_plan_repo_root(target)

        assert resolved is not None
        assert resolved.resolve() == repo.resolve()

    def test_resolves_for_target_that_does_not_exist_yet(self, tmp_path: Path) -> None:
        """The plan folder is being CREATED, so the target path is absent — the
        resolver must walk up to an existing ancestor still inside the repo.
        """
        repo = _git_init(tmp_path / "proj")
        (repo / "CLAUDE" / "Plan").mkdir(parents=True)
        target = repo / "CLAUDE" / "Plan" / "00042-not-created-yet" / "PLAN.md"

        resolved = resolve_plan_repo_root(target)

        assert resolved is not None
        assert resolved.resolve() == repo.resolve()

    def test_resolves_nested_repo_not_outer_repo(self, tmp_path: Path) -> None:
        """A vendor lib with its OWN .git must resolve to the inner repo, not
        the outer project — this is the vendor-subdir fix.
        """
        outer = _git_init(tmp_path / "outer")
        inner = _git_init(outer / "vendor" / "acme-lib")
        target = inner / "CLAUDE" / "Plan" / "00001-x" / "PLAN.md"

        resolved = resolve_plan_repo_root(target)

        assert resolved is not None
        assert resolved.resolve() == inner.resolve()
        assert resolved.resolve() != outer.resolve()

    def test_returns_none_when_not_in_a_git_repo(self, tmp_path: Path) -> None:
        plain = tmp_path / "no-repo-here"
        plain.mkdir()
        target = plain / "CLAUDE" / "Plan" / "00001-x" / "PLAN.md"

        assert resolve_plan_repo_root(target) is None


class TestPlanCounterReadWrite:
    """Read/write the per-repo plan counter via git config --local."""

    def test_read_returns_none_when_counter_absent(self, tmp_path: Path) -> None:
        repo = _git_init(tmp_path / "proj")
        assert read_plan_counter(repo) is None

    def test_write_then_read_roundtrips(self, tmp_path: Path) -> None:
        repo = _git_init(tmp_path / "proj")
        write_plan_counter(repo, 110)
        assert read_plan_counter(repo) == 110

    def test_write_overwrites_previous_value(self, tmp_path: Path) -> None:
        repo = _git_init(tmp_path / "proj")
        write_plan_counter(repo, 110)
        write_plan_counter(repo, 111)
        assert read_plan_counter(repo) == 111

    def test_read_returns_none_when_counter_value_not_an_integer(self, tmp_path: Path) -> None:
        """A corrupt/non-integer counter value must read as None (then the
        caller re-bootstraps) rather than crashing.
        """
        repo = _git_init(tmp_path / "proj")
        subprocess.run(
            ["git", "-C", str(repo), "config", "--local", "hooksdaemon.latestPlanNumber", "abc"],
            capture_output=True,
            check=True,
            timeout=10,
        )
        assert read_plan_counter(repo) is None

    def test_read_returns_none_when_git_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If invoking git raises OSError (e.g. binary missing), the read must
        degrade to None, not propagate.
        """
        repo = _git_init(tmp_path / "proj")

        def _raise_oserror(*_args: object, **_kwargs: object) -> None:
            raise OSError("git not found")

        monkeypatch.setattr(subprocess, "run", _raise_oserror)
        assert read_plan_counter(repo) is None

    def test_counter_survives_branch_switch(self, tmp_path: Path) -> None:
        """The whole point: the counter lives in .git/config (not tracked), so
        it is identical regardless of the checked-out branch.
        """
        repo = _git_init(tmp_path / "proj")
        # An initial commit is required before branches can be created.
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "t@t"],
            capture_output=True,
            check=True,
            timeout=10,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "t"],
            capture_output=True,
            check=True,
            timeout=10,
        )
        (repo / "f.txt").write_text("x")
        subprocess.run(
            ["git", "-C", str(repo), "add", "f.txt"], capture_output=True, check=True, timeout=10
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "init"],
            capture_output=True,
            check=True,
            timeout=10,
        )
        write_plan_counter(repo, 110)

        subprocess.run(
            ["git", "-C", str(repo), "checkout", "-b", "feature"],
            capture_output=True,
            check=True,
            timeout=10,
        )

        assert read_plan_counter(repo) == 110, "counter must be branch-independent"


class TestNextPlanNumberForTarget:
    """Next-number resolution: trust the counter, bootstrap from scan when absent."""

    def test_trusts_counter_when_present(self, tmp_path: Path) -> None:
        """Counter present → counter + 1, WITHOUT consulting the filesystem.

        Proof it ignores the scan: the on-disk plans only go up to 00003, but
        the counter says 110, so the answer must be 00111 (counter-driven), not
        00004 (scan-driven).
        """
        repo = _git_init(tmp_path / "proj")
        plan_dir = repo / "CLAUDE" / "Plan"
        plan_dir.mkdir(parents=True)
        (plan_dir / "00001-a").mkdir()
        (plan_dir / "00003-c").mkdir()
        write_plan_counter(repo, 110)
        target = plan_dir / "00111-new" / "PLAN.md"

        result = next_plan_number_for_target(target, "CLAUDE/Plan", repo)

        assert result == "00111"

    def test_bootstraps_from_scan_when_counter_absent(self, tmp_path: Path) -> None:
        """No counter yet → scan the folder, return scan_max + 1, and SEED the
        counter so subsequent reads are counter-driven.
        """
        repo = _git_init(tmp_path / "proj")
        plan_dir = repo / "CLAUDE" / "Plan"
        plan_dir.mkdir(parents=True)
        (plan_dir / "00005-a").mkdir()
        target = plan_dir / "00006-new" / "PLAN.md"

        result = next_plan_number_for_target(target, "CLAUDE/Plan", repo)

        assert result == "00006"
        # Counter seeded to the high-water mark (highest existing = 5).
        assert read_plan_counter(repo) == 5

    def test_bootstrap_seed_then_trust(self, tmp_path: Path) -> None:
        """After bootstrap, a second call is counter-driven (counter + 1)."""
        repo = _git_init(tmp_path / "proj")
        plan_dir = repo / "CLAUDE" / "Plan"
        plan_dir.mkdir(parents=True)
        (plan_dir / "00005-a").mkdir()
        target = plan_dir / "x" / "PLAN.md"

        first = next_plan_number_for_target(target, "CLAUDE/Plan", repo)
        second = next_plan_number_for_target(target, "CLAUDE/Plan", repo)

        assert first == "00006"
        # Counter was seeded to 5; trust path gives 5 + 1 = 6 again (advisory
        # read does not advance — only real creation does).
        assert second == "00006"

    def test_bootstrap_empty_repo_gives_00001(self, tmp_path: Path) -> None:
        repo = _git_init(tmp_path / "proj")
        (repo / "CLAUDE" / "Plan").mkdir(parents=True)
        target = repo / "CLAUDE" / "Plan" / "x" / "PLAN.md"

        assert next_plan_number_for_target(target, "CLAUDE/Plan", repo) == "00001"
        assert read_plan_counter(repo) == 0

    def test_bootstrap_scans_completed_subfolder(self, tmp_path: Path) -> None:
        """Bootstrap must scan Completed/ too (archived plans count)."""
        repo = _git_init(tmp_path / "proj")
        plan_dir = repo / "CLAUDE" / "Plan"
        completed = plan_dir / "Completed"
        completed.mkdir(parents=True)
        (plan_dir / "00007-active").mkdir()
        (completed / "00009-archived").mkdir()
        target = plan_dir / "x" / "PLAN.md"

        assert next_plan_number_for_target(target, "CLAUDE/Plan", repo) == "00010"
        assert read_plan_counter(repo) == 9

    def test_nested_repo_uses_own_counter(self, tmp_path: Path) -> None:
        """Vendor lib with its own repo gets its own counter, independent of
        the outer project's counter.
        """
        outer = _git_init(tmp_path / "outer")
        write_plan_counter(outer, 110)
        inner = _git_init(outer / "vendor" / "acme-lib")
        write_plan_counter(inner, 6)
        target = inner / "CLAUDE" / "Plan" / "00007-x" / "PLAN.md"

        result = next_plan_number_for_target(target, "CLAUDE/Plan", outer)

        assert result == "00007", "must use inner repo's counter (6+1), not outer's (110+1)"

    def test_non_git_target_falls_back_to_scan_against_fallback_root(self, tmp_path: Path) -> None:
        """No enclosing git repo → scan the fallback root's plan folder."""
        plain = tmp_path / "no-repo"
        plan_dir = plain / "CLAUDE" / "Plan"
        plan_dir.mkdir(parents=True)
        (plan_dir / "00004-a").mkdir()
        target = plan_dir / "x" / "PLAN.md"

        assert next_plan_number_for_target(target, "CLAUDE/Plan", plain) == "00005"

    def test_non_git_empty_fallback_gives_00001(self, tmp_path: Path) -> None:
        plain = tmp_path / "no-repo"
        plain.mkdir()
        target = plain / "CLAUDE" / "Plan" / "x" / "PLAN.md"

        assert next_plan_number_for_target(target, "CLAUDE/Plan", plain) == "00001"


class TestRecordPlanAllocation:
    """High-water-mark write on real plan creation."""

    def test_advances_counter_to_created_number(self, tmp_path: Path) -> None:
        repo = _git_init(tmp_path / "proj")
        write_plan_counter(repo, 110)
        target = repo / "CLAUDE" / "Plan" / "00111-new" / "PLAN.md"

        record_plan_allocation(target, 111)

        assert read_plan_counter(repo) == 111

    def test_never_lowers_counter(self, tmp_path: Path) -> None:
        """Creating a lower-numbered plan must NOT regress the high-water mark."""
        repo = _git_init(tmp_path / "proj")
        write_plan_counter(repo, 110)
        target = repo / "CLAUDE" / "Plan" / "00050-old" / "PLAN.md"

        record_plan_allocation(target, 50)

        assert read_plan_counter(repo) == 110

    def test_seeds_counter_when_absent(self, tmp_path: Path) -> None:
        repo = _git_init(tmp_path / "proj")
        target = repo / "CLAUDE" / "Plan" / "00007-new" / "PLAN.md"

        record_plan_allocation(target, 7)

        assert read_plan_counter(repo) == 7

    def test_self_heals_drift_above_counter(self, tmp_path: Path) -> None:
        """If a higher-numbered plan is created than the counter knew about, the
        counter advances to it — so the NEXT read (counter+1) won't collide.
        """
        repo = _git_init(tmp_path / "proj")
        write_plan_counter(repo, 110)
        target = repo / "CLAUDE" / "Plan" / "00120-jumped" / "PLAN.md"

        record_plan_allocation(target, 120)
        next_num = next_plan_number_for_target(
            repo / "CLAUDE" / "Plan" / "x" / "PLAN.md", "CLAUDE/Plan", repo
        )

        assert read_plan_counter(repo) == 120
        assert next_num == "00121"

    def test_no_op_when_target_not_in_git_repo(self, tmp_path: Path) -> None:
        """Recording against a non-git target is a silent no-op (nothing to
        write the counter to) — must not raise.
        """
        plain = tmp_path / "no-repo"
        plain.mkdir()
        target = plain / "CLAUDE" / "Plan" / "00007-x" / "PLAN.md"

        record_plan_allocation(target, 7)  # must not raise
