"""Tests for GitBranchHandler."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.handlers.status_line import GitBranchHandler


class TestGitBranchHandler:
    """Tests for GitBranchHandler."""

    @pytest.fixture
    def handler(self) -> GitBranchHandler:
        """Create handler instance."""
        return GitBranchHandler()

    def test_handler_properties(self, handler: GitBranchHandler) -> None:
        """Test handler has correct properties."""
        assert handler.name == "status-git-branch"
        assert handler.priority == 20
        assert handler.terminal is False
        assert "status" in handler.tags
        assert "git" in handler.tags

    def test_matches_always_returns_true(self, handler: GitBranchHandler) -> None:
        """Handler should always match for status events."""
        assert handler.matches({}) is True
        assert handler.matches({"workspace": {"current_dir": "/tmp"}}) is True

    def test_handle_with_git_branch(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Test formatting with valid git branch."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        mock_result_toplevel = MagicMock()
        mock_result_toplevel.returncode = 0

        mock_result_branch = MagicMock()
        mock_result_branch.stdout = b"main\n"

        mock_result_symbolic_ref = MagicMock()
        mock_result_symbolic_ref.returncode = 0
        mock_result_symbolic_ref.stdout = b"refs/remotes/origin/main\n"

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                mock_result_toplevel,
                mock_result_branch,
                mock_result_symbolic_ref,
            ]
            result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert "| ⎇ " in result.context[0]
        assert "main" in result.context[0]

    def test_handle_not_a_git_repo(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Test returns empty context when not in git repo."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 0

    def test_handle_no_workspace_data(self, handler: GitBranchHandler) -> None:
        """Test returns empty context when workspace data missing."""
        result = handler.handle({})

        assert result.decision == "allow"
        assert len(result.context) == 0

    def test_handle_invalid_path(self, handler: GitBranchHandler) -> None:
        """Test returns empty context when path doesn't exist."""
        hook_input = {"workspace": {"current_dir": "/nonexistent/path"}}

        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 0

    def test_handle_git_error_silent_fail(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Test silent failure on git errors."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        with patch("subprocess.run", side_effect=Exception("Git error")):
            result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 0

    def test_handle_empty_branch_name(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Test returns empty context when branch name is empty."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        mock_result_toplevel = MagicMock()
        mock_result_toplevel.returncode = 0

        mock_result_branch = MagicMock()
        mock_result_branch.stdout = b"\n"

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [mock_result_toplevel, mock_result_branch]
            result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 0

    def test_uses_project_dir_fallback(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Test uses project_dir when current_dir not available."""
        hook_input = {"workspace": {"project_dir": str(tmp_path)}}

        mock_result_toplevel = MagicMock()
        mock_result_toplevel.returncode = 0

        mock_result_branch = MagicMock()
        mock_result_branch.stdout = b"develop\n"

        mock_result_symbolic_ref = MagicMock()
        mock_result_symbolic_ref.returncode = 0
        mock_result_symbolic_ref.stdout = b"refs/remotes/origin/main\n"

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                mock_result_toplevel,
                mock_result_branch,
                mock_result_symbolic_ref,
            ]
            result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert "| ⎇ " in result.context[0]
        assert "develop" in result.context[0]


class TestGitBranchColorCoding:
    """Tests for branch color-coding based on default branch detection."""

    _GREEN = "\033[32m"
    _ORANGE = "\033[38;5;208m"
    _RESET = "\033[0m"

    @pytest.fixture
    def handler(self) -> GitBranchHandler:
        return GitBranchHandler()

    def _make_run_side_effects(
        self,
        branch: str,
        symbolic_ref_returncode: int = 0,
        symbolic_ref_stdout: bytes = b"refs/remotes/origin/main\n",
    ) -> list[MagicMock]:
        mock_toplevel = MagicMock()
        mock_toplevel.returncode = 0

        mock_branch = MagicMock()
        mock_branch.stdout = branch.encode() + b"\n"

        mock_symbolic_ref = MagicMock()
        mock_symbolic_ref.returncode = symbolic_ref_returncode
        mock_symbolic_ref.stdout = symbolic_ref_stdout

        return [mock_toplevel, mock_branch, mock_symbolic_ref]

    def test_default_branch_is_green(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Branch matching origin/HEAD should be colored green."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        side_effects = self._make_run_side_effects("main")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = side_effects
            result = handler.handle(hook_input)

        assert self._GREEN in result.context[0]
        assert self._RESET in result.context[0]
        assert self._ORANGE not in result.context[0]

    def test_non_default_branch_is_orange(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Branch not matching origin/HEAD should be colored orange."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        side_effects = self._make_run_side_effects("feature/my-feature")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = side_effects
            result = handler.handle(hook_input)

        assert self._ORANGE in result.context[0]
        assert self._RESET in result.context[0]
        assert self._GREEN not in result.context[0]

    def test_default_branch_from_symbolic_ref(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """Correctly extracts default branch name from symbolic ref output."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        # Remote uses 'develop' as default branch
        side_effects = self._make_run_side_effects(
            "develop",
            symbolic_ref_stdout=b"refs/remotes/origin/develop\n",
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = side_effects
            result = handler.handle(hook_input)

        assert self._GREEN in result.context[0]

    def test_fallback_to_main_when_no_symbolic_ref(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """Falls back to checking 'main'/'master' when no remote HEAD."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        mock_toplevel = MagicMock()
        mock_toplevel.returncode = 0

        mock_branch_result = MagicMock()
        mock_branch_result.stdout = b"main\n"

        mock_symbolic_ref_fail = MagicMock()
        mock_symbolic_ref_fail.returncode = 128  # no remote HEAD

        mock_show_ref_main = MagicMock()
        mock_show_ref_main.returncode = 0  # 'main' exists locally

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                mock_toplevel,
                mock_branch_result,
                mock_symbolic_ref_fail,
                mock_show_ref_main,
            ]
            result = handler.handle(hook_input)

        assert self._GREEN in result.context[0]

    def test_fallback_master_when_no_main(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Falls back to 'master' when 'main' doesn't exist locally."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        mock_toplevel = MagicMock()
        mock_toplevel.returncode = 0

        mock_branch_result = MagicMock()
        mock_branch_result.stdout = b"master\n"

        mock_symbolic_ref_fail = MagicMock()
        mock_symbolic_ref_fail.returncode = 128

        mock_show_ref_main_fail = MagicMock()
        mock_show_ref_main_fail.returncode = 1  # 'main' doesn't exist

        mock_show_ref_master = MagicMock()
        mock_show_ref_master.returncode = 0  # 'master' exists

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                mock_toplevel,
                mock_branch_result,
                mock_symbolic_ref_fail,
                mock_show_ref_main_fail,
                mock_show_ref_master,
            ]
            result = handler.handle(hook_input)

        assert self._GREEN in result.context[0]

    def test_no_default_branch_found_is_grey(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """When default branch can't be determined, branch is shown in grey."""
        _GREY = "\033[37m"
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        mock_toplevel = MagicMock()
        mock_toplevel.returncode = 0

        mock_branch_result = MagicMock()
        mock_branch_result.stdout = b"feature/xyz\n"

        mock_symbolic_ref_fail = MagicMock()
        mock_symbolic_ref_fail.returncode = 128

        mock_show_ref_main_fail = MagicMock()
        mock_show_ref_main_fail.returncode = 1

        mock_show_ref_master_fail = MagicMock()
        mock_show_ref_master_fail.returncode = 1

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                mock_toplevel,
                mock_branch_result,
                mock_symbolic_ref_fail,
                mock_show_ref_main_fail,
                mock_show_ref_master_fail,
            ]
            result = handler.handle(hook_input)

        assert _GREY in result.context[0]
        assert self._GREEN not in result.context[0]
        assert self._ORANGE not in result.context[0]

    def test_handle_git_called_process_error_silent_fail(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """Test silent failure on CalledProcessError (e.g. git branch --show-current fails)."""
        import subprocess

        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        mock_result_toplevel = MagicMock()
        mock_result_toplevel.returncode = 0

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                mock_result_toplevel,
                subprocess.CalledProcessError(1, "git"),
            ]
            result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 0

    def test_get_default_branch_timeout_returns_none(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """_get_default_branch returns None when subprocess times out."""
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 5)):
            result = handler._get_default_branch(str(tmp_path))

        assert result is None

    def test_default_branch_detection_cached(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """Default branch detection runs only once across multiple handle() calls.

        Call sequence per handle(): rev-parse, branch --show-current, [symbolic-ref
        on first call only], git status --porcelain=v2, git stash list.
        """
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        def make_mocks(branch_name: str, include_symbolic_ref: bool) -> list[MagicMock]:
            mock_toplevel = MagicMock()
            mock_toplevel.returncode = 0
            mock_branch = MagicMock()
            mock_branch.stdout = branch_name.encode() + b"\n"
            mocks = [mock_toplevel, mock_branch]
            if include_symbolic_ref:
                mock_symbolic_ref = MagicMock()
                mock_symbolic_ref.returncode = 0
                mock_symbolic_ref.stdout = b"refs/remotes/origin/main\n"
                mocks.append(mock_symbolic_ref)
            mock_status = MagicMock()
            mock_status.returncode = 0
            mock_status.stdout = b""
            mock_stash = MagicMock()
            mock_stash.returncode = 0
            mock_stash.stdout = b""
            mocks.extend([mock_status, mock_stash])
            return mocks

        # First call: 5 subprocess invocations
        # (toplevel + branch + symbolic-ref + status + stash)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = make_mocks("main", include_symbolic_ref=True)
            handler.handle(hook_input)
            first_call_count = mock_run.call_count
        assert first_call_count == 5

        # Second call: 4 subprocess invocations (no symbolic-ref — cached)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = make_mocks("feature/x", include_symbolic_ref=False)
            handler.handle(hook_input)
            second_call_count = mock_run.call_count
        assert second_call_count == 4


class TestGitStatusIcons:
    """Tests for magicmonty-style status icons after branch name."""

    _GREEN = "\033[32m"
    _RED = "\033[31m"
    _YELLOW = "\033[33m"
    _CYAN = "\033[36m"
    _GREY = "\033[37m"
    _RESET = "\033[0m"

    @pytest.fixture
    def handler(self) -> GitBranchHandler:
        return GitBranchHandler()

    def _make_mocks(
        self,
        *,
        branch: str = "main",
        status_stdout: bytes = b"",
        stash_stdout: bytes = b"",
    ) -> list[MagicMock]:
        """Build the standard 5-call mock chain.

        toplevel, branch --show-current, symbolic-ref (origin/main),
        git status --porcelain=v2 --branch, git stash list.
        """
        mock_toplevel = MagicMock(returncode=0)
        mock_branch = MagicMock(stdout=branch.encode() + b"\n")
        mock_symbolic_ref = MagicMock(returncode=0, stdout=b"refs/remotes/origin/main\n")
        mock_status = MagicMock(returncode=0, stdout=status_stdout)
        mock_stash = MagicMock(returncode=0, stdout=stash_stdout)
        return [mock_toplevel, mock_branch, mock_symbolic_ref, mock_status, mock_stash]

    def test_ahead_shows_up_arrow(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """`# branch.ab +2 -0` should render ↑2 in green."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        status_stdout = (
            b"# branch.oid abc\n"
            b"# branch.head main\n"
            b"# branch.upstream origin/main\n"
            b"# branch.ab +2 -0\n"
        )
        mocks = self._make_mocks(status_stdout=status_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        assert f"{self._GREEN}↑2{self._RESET}" in rendered
        assert "↓" not in rendered

    def test_behind_shows_down_arrow(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """`# branch.ab +0 -3` should render ↓3 in red."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        status_stdout = (
            b"# branch.head main\n" b"# branch.upstream origin/main\n" b"# branch.ab +0 -3\n"
        )
        mocks = self._make_mocks(status_stdout=status_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        assert f"{self._RED}↓3{self._RESET}" in rendered
        assert "↑" not in rendered

    def test_ahead_and_behind_both_shown(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Diverged branch shows both arrows."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        status_stdout = (
            b"# branch.head main\n" b"# branch.upstream origin/main\n" b"# branch.ab +2 -1\n"
        )
        mocks = self._make_mocks(status_stdout=status_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        assert "↑2" in rendered
        assert "↓1" in rendered

    def test_staged_change_shown(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """`1 M. ...` (staged modification) renders ●1 in green."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        status_stdout = (
            b"# branch.head main\n" b"1 M. N... 100644 100644 100644 abc abc src/foo.py\n"
        )
        mocks = self._make_mocks(status_stdout=status_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        assert f"{self._GREEN}●1{self._RESET}" in rendered

    def test_unstaged_change_shown(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """`1 .M ...` (unstaged modification) renders ✚1 in yellow."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        status_stdout = (
            b"# branch.head main\n" b"1 .M N... 100644 100644 100644 abc abc src/foo.py\n"
        )
        mocks = self._make_mocks(status_stdout=status_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        assert f"{self._YELLOW}✚1{self._RESET}" in rendered

    def test_file_counted_in_both_staged_and_unstaged(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """`1 MM ...` (staged AND unstaged on same file) counts in both."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        status_stdout = (
            b"# branch.head main\n" b"1 MM N... 100644 100644 100644 abc abc src/foo.py\n"
        )
        mocks = self._make_mocks(status_stdout=status_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        assert "●1" in rendered
        assert "✚1" in rendered

    def test_untracked_file_shown(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """`? path` renders …1 in grey."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        status_stdout = b"# branch.head main\n? new_file.py\n"
        mocks = self._make_mocks(status_stdout=status_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        assert f"{self._GREY}…1{self._RESET}" in rendered

    def test_conflicts_shown(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """`u UU ...` (unmerged) renders ✖1 in red."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        status_stdout = (
            b"# branch.head main\n" b"u UU N... 100644 100644 100644 100644 a b c d conflict.py\n"
        )
        mocks = self._make_mocks(status_stdout=status_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        assert f"{self._RED}✖1{self._RESET}" in rendered

    def test_stashed_shown(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """`git stash list` with 2 lines renders ⚑2 in cyan."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        stash_stdout = b"stash@{0}: WIP on main: abc Fix\n" b"stash@{1}: WIP on main: def Other\n"
        mocks = self._make_mocks(stash_stdout=stash_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        assert f"{self._CYAN}⚑2{self._RESET}" in rendered

    def test_clean_repo_shows_only_branch(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Clean repo with synced upstream and no changes shows only branch."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        status_stdout = (
            b"# branch.head main\n" b"# branch.upstream origin/main\n" b"# branch.ab +0 -0\n"
        )
        mocks = self._make_mocks(status_stdout=status_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        for icon in ("↑", "↓", "●", "✚", "…", "⚑", "✖"):
            assert icon not in rendered, f"icon {icon!r} should not appear in clean repo"

    def test_no_upstream_omits_ahead_behind(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """Branch with no upstream tracking has no `# branch.ab` line, so no arrows."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        status_stdout = b"# branch.head feature/x\n"
        mocks = self._make_mocks(branch="feature/x", status_stdout=status_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        assert "↑" not in rendered
        assert "↓" not in rendered

    def test_status_silent_fail_keeps_branch(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """If `git status` raises, branch is still shown without icons."""
        import subprocess

        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        mock_toplevel = MagicMock(returncode=0)
        mock_branch = MagicMock(stdout=b"main\n")
        mock_symbolic_ref = MagicMock(returncode=0, stdout=b"refs/remotes/origin/main\n")
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                mock_toplevel,
                mock_branch,
                mock_symbolic_ref,
                subprocess.TimeoutExpired("git", 5),
                # stash should not be called since status failed first
            ]
            result = handler.handle(hook_input)
        assert "main" in result.context[0]
        for icon in ("↑", "↓", "●", "✚", "…", "⚑", "✖"):
            assert icon not in result.context[0]

    def test_combined_state_renders_in_documented_order(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """Combined state: ahead, staged, changed, untracked, stashed."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        status_stdout = (
            b"# branch.head main\n"
            b"# branch.upstream origin/main\n"
            b"# branch.ab +1 -0\n"
            b"1 M. N... 100644 100644 100644 a b src/foo.py\n"
            b"1 .M N... 100644 100644 100644 c d src/bar.py\n"
            b"? new.py\n"
        )
        stash_stdout = b"stash@{0}: WIP\n"
        mocks = self._make_mocks(status_stdout=status_stdout, stash_stdout=stash_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        # Order: ahead, behind, staged, changed, conflicts, untracked, stashed
        positions = {
            "↑1": rendered.index("↑1"),
            "●1": rendered.index("●1"),
            "✚1": rendered.index("✚1"),
            "…1": rendered.index("…1"),
            "⚑1": rendered.index("⚑1"),
        }
        assert (
            positions["↑1"] < positions["●1"] < positions["✚1"] < positions["…1"] < positions["⚑1"]
        )
