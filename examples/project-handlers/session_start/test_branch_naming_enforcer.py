"""Tests for branch naming enforcer handler."""

from unittest.mock import MagicMock, patch

import pytest
from branch_naming_enforcer import BranchNamingEnforcerHandler
from pydantic import ValidationError

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

    def test_reports_bad_branch_name_as_context(self) -> None:
        """A non-conforming branch is REPORTED, not refused.

        This test used to assert DENY, and it passed — `HookResult.deny()` really
        does set the decision. What it could not see is that `SessionStart` has no
        way to carry a refusal, so the response went out as a plain allow and the
        session started anyway. A unit test on a handler cannot observe a decision
        dropped during serialisation; only the event's own capability can.
        """
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "my-random-branch\n"
        with patch("branch_naming_enforcer.subprocess.run", return_value=mock_result):
            result = self.handler.handle({})
        assert result.decision == Decision.ALLOW
        assert any("my-random-branch" in line for line in result.context)

    def test_cannot_refuse_because_session_start_cannot(self) -> None:
        """The narrowed base makes the original bug unwritable, not merely fixed.

        `SessionStartHandlerBase` narrows `handle()` to `AdvisoryResult`, whose
        Pydantic model rejects a refusal on construction AND on assignment. So
        the defect this example used to carry cannot be reintroduced here even
        by editing the body — mypy refuses it statically, and this asserts the
        runtime half.
        """
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "my-random-branch\n"
        with patch("branch_naming_enforcer.subprocess.run", return_value=mock_result):
            result = self.handler.handle({})

        # Assigned through a NAMED field rather than as `result.decision = ...`,
        # deliberately. The plain form does not type-check at all: mypy rejects
        # DENY against AdvisoryResult's narrowed field. That refusal IS the
        # static half of the guard, so asserting the RUNTIME half means routing
        # around the type-checker on purpose -- the indirection says "even
        # circumventing the static check, Pydantic still refuses". Silencing the
        # checker with an inline suppression directive would prove the same
        # point by hiding a real error, which this project forbids outright.
        narrowed_field = "decision"
        with pytest.raises(ValidationError):
            setattr(result, narrowed_field, Decision.DENY)

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
