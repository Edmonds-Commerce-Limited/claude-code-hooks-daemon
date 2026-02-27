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
        """Default branch detection runs only once across multiple handle() calls."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        def make_mocks(branch_name: str) -> list[MagicMock]:
            mock_toplevel = MagicMock()
            mock_toplevel.returncode = 0
            mock_branch = MagicMock()
            mock_branch.stdout = branch_name.encode() + b"\n"
            mock_symbolic_ref = MagicMock()
            mock_symbolic_ref.returncode = 0
            mock_symbolic_ref.stdout = b"refs/remotes/origin/main\n"
            return [mock_toplevel, mock_branch, mock_symbolic_ref]

        # First call: 3 subprocess invocations (toplevel + branch + symbolic-ref)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = make_mocks("main")
            handler.handle(hook_input)
            first_call_count = mock_run.call_count
        assert first_call_count == 3

        # Second call: only 2 subprocess invocations (toplevel + branch; no symbolic-ref)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0),
                MagicMock(stdout=b"feature/x\n"),
            ]
            handler.handle(hook_input)
            second_call_count = mock_run.call_count
        assert second_call_count == 2
