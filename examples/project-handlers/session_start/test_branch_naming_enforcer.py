"""Tests for branch naming enforcer handler."""

from unittest.mock import patch, MagicMock

from branch_naming_enforcer import BranchNamingEnforcerHandler
from claude_code_hooks_daemon.core.hook_result import Decision


class TestBranchNamingEnforcerHandler:
    """Tests for BranchNamingEnforcerHandler."""

    def setup_method(self) -> None:
        self.handler = BranchNamingEnforcerHandler()

    def test_init(self) -> None:
        assert self.handler.name == "branch-naming-enforcer"
        assert self.handler.priority == 30
        assert self.handler.terminal is False

    def test_always_matches(self) -> None:
        assert self.handler.matches({}) is True

    def test_allows_feature_branch(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "feature/add-login\n"
        with patch("branch_naming_enforcer.subprocess.run", return_value=mock_result):
            result = self.handler.handle({})
        assert result.decision == Decision.ALLOW

    def test_allows_fix_branch(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "fix/null-pointer\n"
        with patch("branch_naming_enforcer.subprocess.run", return_value=mock_result):
            result = self.handler.handle({})
        assert result.decision == Decision.ALLOW

    def test_allows_main_branch(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "main\n"
        with patch("branch_naming_enforcer.subprocess.run", return_value=mock_result):
            result = self.handler.handle({})
        assert result.decision == Decision.ALLOW

    def test_denies_bad_branch_name(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "my-random-branch\n"
        with patch("branch_naming_enforcer.subprocess.run", return_value=mock_result):
            result = self.handler.handle({})
        assert result.decision == Decision.DENY
        assert "my-random-branch" in (result.reason or "")

    def test_allows_on_git_failure(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        with patch("branch_naming_enforcer.subprocess.run", return_value=mock_result):
            result = self.handler.handle({})
        assert result.decision == Decision.ALLOW

    def test_allows_on_timeout(self) -> None:
        import subprocess
        with patch(
            "branch_naming_enforcer.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=5),
        ):
            result = self.handler.handle({})
        assert result.decision == Decision.ALLOW

    def test_acceptance_tests_defined(self) -> None:
        tests = self.handler.get_acceptance_tests()
        assert len(tests) >= 1
