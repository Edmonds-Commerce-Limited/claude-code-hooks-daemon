"""Tests for the capped protected-file tree scan (ledger 00483 N130, 00474 N348).

The scan answers "does a recursive search under this root read a protected
file?". Its one rule: an unfinished scan is never answered as "no". Past the
entry cap it raises ``TooManyToEnumerateError``, past the deadline
``TimeoutError``; only a scan that examined the whole view returns None.

Assertions are on work done (entries visited, calls made), never on wall clock.
"""

import subprocess  # nosec B404 - fixed git argv in a tmp repository
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils import git_repo
from claude_code_hooks_daemon.utils import protected_tree_scan as pts
from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.protected_tree_scan import TreeView, find_protected_in_tree
from claude_code_hooks_daemon.utils.shell_expansion import TooManyToEnumerateError

PROTECTED_GLOB = "*.p483vault"
PATTERNS = (PROTECTED_GLOB,)
PROTECTED_NAME = "key.p483vault"


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True
    )  # nosec B603 B607


def _populate(directory: Path, count: int, prefix: str = "f") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        (directory / f"{prefix}{index:05d}.txt").write_text("x\n")


class TestAllView:
    """``grep -r`` reads everything: hidden, ignored, and the lot."""

    def test_default_cap_is_the_measured_value(self) -> None:
        assert pts.TREE_SCAN_MAX_ENTRIES == 250_000

    def test_protected_file_after_five_thousand_clean_files_is_found(self, tmp_path: Path) -> None:
        """N130: the old walk stopped at 5000 files and answered None."""
        _populate(tmp_path / "a", 5500)
        deep = tmp_path / "zdeep" / "inner"
        deep.mkdir(parents=True)
        (deep / PROTECTED_NAME).write_text("x\n")
        found = find_protected_in_tree(str(tmp_path), PATTERNS, view=TreeView.ALL)
        assert found == PROTECTED_GLOB

    def test_clean_tree_past_a_small_cap_raises_never_none(self, tmp_path: Path) -> None:
        _populate(tmp_path, 20)
        with pytest.raises(TooManyToEnumerateError) as caught:
            find_protected_in_tree(str(tmp_path), PATTERNS, view=TreeView.ALL, max_entries=10)
        assert caught.value.limit == 10

    def test_directories_count_against_the_cap(self, tmp_path: Path) -> None:
        for index in range(20):
            (tmp_path / f"d{index}").mkdir()
        with pytest.raises(TooManyToEnumerateError):
            find_protected_in_tree(str(tmp_path), PATTERNS, view=TreeView.ALL, max_entries=10)

    def test_tree_exactly_at_the_cap_is_answered(self, tmp_path: Path) -> None:
        _populate(tmp_path, 10)
        assert (
            find_protected_in_tree(str(tmp_path), PATTERNS, view=TreeView.ALL, max_entries=10)
            is None
        )

    def test_deadline_is_checked_inside_the_walk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _populate(tmp_path, 5)
        monkeypatch.setattr(pts.time, "monotonic", lambda: 100.0)
        with pytest.raises(TimeoutError):
            find_protected_in_tree(str(tmp_path), PATTERNS, view=TreeView.ALL, deadline=50.0)

    def test_deadline_in_the_future_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _populate(tmp_path, 5)
        monkeypatch.setattr(pts.time, "monotonic", lambda: 10.0)
        assert (
            find_protected_in_tree(str(tmp_path), PATTERNS, view=TreeView.ALL, deadline=50.0)
            is None
        )

    @pytest.mark.parametrize(
        "patterns",
        [
            (PROTECTED_GLOB,),
            ("*.p483vault", "bak-p483*", "secrets483/**"),
            ("*",),
            ("a?c.p483*", "**"),
            ("zz-missing-name",),
        ],
    )
    def test_screened_walk_agrees_with_the_unscreened_matcher(
        self, tmp_path: Path, patterns: tuple[str, ...]
    ) -> None:
        """Includes patterns with no literal run, where the screen cannot be built."""
        names = ["a.txt", "abc.p483vault", "bak-p483.old", "x.p483", "q.py"]
        for directory in ("one", "two/three"):
            (tmp_path / directory).mkdir(parents=True)
            for name in names:
                (tmp_path / directory / name).write_text("x\n")
        project_root = sfm.resolve_project_root()
        expected = {
            sfm.first_matching_glob(str(path), patterns, project_root=project_root)
            for path in tmp_path.rglob("*")
            if path.is_file()
        } - {None}
        found = find_protected_in_tree(str(tmp_path), patterns, view=TreeView.ALL)
        if expected:
            assert found in expected
        else:
            assert found is None

    def test_exempt_file_is_skipped_but_a_plaintext_one_beside_it_flags(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "vault.p483vault").write_text("x\n")
        exempt = str(tmp_path / "vault.p483vault")
        assert (
            find_protected_in_tree(
                str(tmp_path), PATTERNS, view=TreeView.ALL, is_exempt=lambda path: path == exempt
            )
            is None
        )
        (tmp_path / PROTECTED_NAME).write_text("x\n")
        assert (
            find_protected_in_tree(
                str(tmp_path), PATTERNS, view=TreeView.ALL, is_exempt=lambda path: path == exempt
            )
            == PROTECTED_GLOB
        )

    def test_skip_prunes_directories_and_files(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / PROTECTED_NAME).write_text("x\n")
        pruned = find_protected_in_tree(
            str(tmp_path),
            PATTERNS,
            view=TreeView.ALL,
            skip=lambda path, is_dir: is_dir and path.endswith("sub"),
        )
        assert pruned is None
        kept = find_protected_in_tree(
            str(tmp_path), PATTERNS, view=TreeView.ALL, skip=lambda path, is_dir: False
        )
        assert kept == PROTECTED_GLOB

    def test_a_pruned_directory_is_not_listed(self, tmp_path: Path) -> None:
        _populate(tmp_path / "bulk", 50)
        assert (
            find_protected_in_tree(
                str(tmp_path),
                PATTERNS,
                view=TreeView.ALL,
                skip=lambda path, is_dir: is_dir and path.endswith("bulk"),
                max_entries=5,
            )
            is None
        )

    def test_non_directory_and_empty_patterns_answer_none(self, tmp_path: Path) -> None:
        target = tmp_path / "file.txt"
        target.write_text("x\n")
        assert find_protected_in_tree(str(target), PATTERNS, view=TreeView.ALL) is None
        assert find_protected_in_tree(str(tmp_path), (), view=TreeView.ALL) is None

    def test_symlink_to_a_directory_is_not_followed(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / PROTECTED_NAME).write_text("x\n")
        searched = tmp_path / "searched"
        searched.mkdir()
        (searched / "link").symlink_to(outside, target_is_directory=True)
        assert find_protected_in_tree(str(searched), PATTERNS, view=TreeView.ALL) is None


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository tracking ``tracked/<protected>`` and ignoring ``local/<protected>``."""
    _git(tmp_path, "init", "-q")
    (tmp_path / "tracked").mkdir()
    (tmp_path / "tracked" / PROTECTED_NAME).write_text("x\n")
    (tmp_path / "plain.txt").write_text("x\n")
    (tmp_path / ".gitignore").write_text("local/\n")
    (tmp_path / "local").mkdir()
    (tmp_path / "local" / PROTECTED_NAME).write_text("x\n")
    _git(tmp_path, "add", "tracked", "plain.txt", ".gitignore")
    return tmp_path


def _untrack_protected(repo: Path) -> None:
    """Leave the repository with no tracked protected file."""
    _git(repo, "rm", "-q", "--cached", "-r", "tracked")
    (repo / "tracked" / PROTECTED_NAME).unlink()


def _git_timed_out(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], git_repo.GIT_TIMED_OUT, "", "timed out")


class TestTrackedView:
    """``git grep`` reads the index and nothing else."""

    def test_tracked_protected_file_is_found(self, repo: Path) -> None:
        assert find_protected_in_tree(str(repo), PATTERNS, view=TreeView.TRACKED) == PROTECTED_GLOB

    def test_protected_file_listed_after_position_six_thousand_is_found(
        self, tmp_path: Path
    ) -> None:
        """The old listing was cut at 5000 entries and answered on the first 5000 only."""
        _git(tmp_path, "init", "-q")
        _populate(tmp_path / "a", 6000)
        (tmp_path / "z").mkdir()
        (tmp_path / "z" / PROTECTED_NAME).write_text("x\n")
        _git(tmp_path, "add", "-A")
        assert (
            find_protected_in_tree(str(tmp_path), PATTERNS, view=TreeView.TRACKED) == PROTECTED_GLOB
        )

    def test_untracked_and_ignored_files_are_not_read(self, repo: Path) -> None:
        _git(repo, "rm", "-q", "--cached", "-r", "tracked")
        assert find_protected_in_tree(str(repo), PATTERNS, view=TreeView.TRACKED) is None

    def test_outside_a_repository_git_grep_cannot_read_so_none(self, tmp_path: Path) -> None:
        (tmp_path / PROTECTED_NAME).write_text("x\n")
        assert find_protected_in_tree(str(tmp_path), PATTERNS, view=TreeView.TRACKED) is None

    def test_exempt_tracked_file_does_not_flag(self, repo: Path) -> None:
        exempt = str(repo / "tracked" / PROTECTED_NAME)
        assert (
            find_protected_in_tree(
                str(repo), PATTERNS, view=TreeView.TRACKED, is_exempt=lambda path: path == exempt
            )
            is None
        )

    def test_listing_past_the_cap_raises(self, repo: Path) -> None:
        with pytest.raises(TooManyToEnumerateError):
            find_protected_in_tree(str(repo), PATTERNS, view=TreeView.TRACKED, max_entries=1)

    def test_git_timeout_raises_never_none(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(pts, "run_git", _git_timed_out)
        with pytest.raises(TimeoutError):
            find_protected_in_tree(str(repo), PATTERNS, view=TreeView.TRACKED)


class TestUnignoredView:
    """``rg`` and ``ag`` read git's non-ignored set, minus what the tool skips."""

    def test_tracked_protected_file_is_found(self, repo: Path) -> None:
        assert (
            find_protected_in_tree(str(repo), PATTERNS, view=TreeView.UNIGNORED) == PROTECTED_GLOB
        )

    def test_ignored_protected_file_is_not_reported(self, repo: Path) -> None:
        _untrack_protected(repo)
        assert find_protected_in_tree(str(repo), PATTERNS, view=TreeView.UNIGNORED) is None

    def test_untracked_but_not_ignored_file_is_reported(self, repo: Path) -> None:
        _untrack_protected(repo)
        (repo / "fresh.p483vault").write_text("x\n")
        assert (
            find_protected_in_tree(str(repo), PATTERNS, view=TreeView.UNIGNORED) == PROTECTED_GLOB
        )

    def test_hidden_entry_is_skipped_when_the_skip_hook_says_so(self, tmp_path: Path) -> None:
        _git(tmp_path, "init", "-q")
        (tmp_path / ".hid").mkdir()
        (tmp_path / ".hid" / PROTECTED_NAME).write_text("x\n")
        (tmp_path / "a.txt").write_text("x\n")
        _git(tmp_path, "add", "-A")

        def hidden(path: str, is_dir: bool) -> bool:
            return Path(path).name.startswith(".")

        skipped = find_protected_in_tree(
            str(tmp_path), PATTERNS, view=TreeView.UNIGNORED, skip=hidden
        )
        assert skipped is None
        read = find_protected_in_tree(str(tmp_path), PATTERNS, view=TreeView.UNIGNORED)
        assert read == PROTECTED_GLOB

    def test_nested_repository_is_walked(self, repo: Path) -> None:
        _untrack_protected(repo)
        nested = repo / "vendor_clone"
        nested.mkdir()
        _git(nested, "init", "-q")
        (nested / PROTECTED_NAME).write_text("x\n")
        assert (
            find_protected_in_tree(str(repo), PATTERNS, view=TreeView.UNIGNORED) == PROTECTED_GLOB
        )

    def test_non_repository_falls_back_to_the_walk(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / PROTECTED_NAME).write_text("x\n")
        assert (
            find_protected_in_tree(str(tmp_path), PATTERNS, view=TreeView.UNIGNORED)
            == PROTECTED_GLOB
        )

    def test_explicitly_named_ignored_root_is_walked_and_found(self, repo: Path) -> None:
        assert (
            find_protected_in_tree(str(repo / "local"), PATTERNS, view=TreeView.UNIGNORED)
            == PROTECTED_GLOB
        )

    def test_explicitly_named_hidden_root_is_walked_and_found(self, tmp_path: Path) -> None:
        _git(tmp_path, "init", "-q")
        (tmp_path / ".hid").mkdir()
        (tmp_path / ".hid" / PROTECTED_NAME).write_text("x\n")
        assert (
            find_protected_in_tree(str(tmp_path / ".hid"), PATTERNS, view=TreeView.UNIGNORED)
            == PROTECTED_GLOB
        )

    def test_an_ignored_directory_is_never_visited(self, repo: Path) -> None:
        """The entry-count seam: 400 ignored files under a cap of 100 are not counted."""
        _untrack_protected(repo)
        (repo / ".gitignore").write_text("local/\nbig/\n")
        _populate(repo / "big", 400)
        assert (
            find_protected_in_tree(str(repo), PATTERNS, view=TreeView.UNIGNORED, max_entries=100)
            is None
        )
        with pytest.raises(TooManyToEnumerateError):
            find_protected_in_tree(str(repo), PATTERNS, view=TreeView.ALL, max_entries=100)

    def test_listing_past_the_cap_raises(self, tmp_path: Path) -> None:
        _git(tmp_path, "init", "-q")
        _populate(tmp_path, 20)
        with pytest.raises(TooManyToEnumerateError):
            find_protected_in_tree(str(tmp_path), PATTERNS, view=TreeView.UNIGNORED, max_entries=10)

    def test_git_timeout_raises_never_none(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(pts, "run_git", _git_timed_out)
        with pytest.raises(TimeoutError):
            find_protected_in_tree(str(repo), PATTERNS, view=TreeView.UNIGNORED)


class TestDirectoryContainsProtected:
    """The ALL-view wrapper for a caller that wants only the answer."""

    def test_directory_holding_protected_file_is_flagged(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / PROTECTED_NAME).write_text("x\n")
        assert pts.directory_contains_protected(str(tmp_path), PATTERNS) == PROTECTED_GLOB

    def test_clean_directory_is_not_flagged(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x\n")
        assert pts.directory_contains_protected(str(tmp_path), PATTERNS) is None

    def test_a_cap_is_never_an_answer(self, tmp_path: Path) -> None:
        _populate(tmp_path, 5)
        (tmp_path / "zzz.p483vault").write_text("x\n")
        with pytest.raises(TooManyToEnumerateError):
            pts.directory_contains_protected(str(tmp_path), PATTERNS, max_entries=2)
