"""Integration tests for ReleaseBlockerHandler (project-specific handler).

Tests that the handler integrates correctly with the daemon system and
returns valid Stop event responses.
"""

from unittest.mock import MagicMock, patch

from .release_blocker import ReleaseBlockerHandler


class TestReleaseBlockerIntegration:
    """Test ReleaseBlockerHandler integration with daemon system."""

    @patch("subprocess.run")
    def test_handler_returns_valid_stop_response_when_blocking(self, mock_run: MagicMock) -> None:
        """Handler should return valid Stop event response format when blocking."""
        handler = ReleaseBlockerHandler()

        # Mock release context (modified pyproject.toml)
        mock_run.return_value = MagicMock(returncode=0, stdout="M  pyproject.toml\n")

        # Verify handler matches (release context)
        hook_input = {}
        assert handler.matches(hook_input) is True

        # Execute handler
        result = handler.handle(hook_input)

        # Verify response structure
        assert hasattr(result, "decision")
        assert hasattr(result, "reason")
        assert result.decision is not None
        assert result.reason is not None
        assert isinstance(result.reason, str)

    @patch("subprocess.run")
    def test_handler_allows_when_no_release_context(self, mock_run: MagicMock) -> None:
        """Handler should not match when no release files modified."""
        handler = ReleaseBlockerHandler()

        # Mock no release files modified
        mock_run.return_value = MagicMock(returncode=0, stdout="M  tests/test_something.py\n")

        hook_input = {}
        assert handler.matches(hook_input) is False

    def test_handler_has_required_attributes(self) -> None:
        """Handler should have all required attributes for daemon integration."""
        handler = ReleaseBlockerHandler()

        # Required attributes
        assert hasattr(handler, "handler_id")
        assert hasattr(handler, "priority")
        assert hasattr(handler, "terminal")
        assert hasattr(handler, "matches")
        assert hasattr(handler, "handle")
        assert hasattr(handler, "get_acceptance_tests")

        # Attributes should have correct types
        assert handler.handler_id is not None
        assert isinstance(handler.priority, int)
        assert isinstance(handler.terminal, bool)
        assert callable(handler.matches)
        assert callable(handler.handle)
        assert callable(handler.get_acceptance_tests)

    def test_handler_acceptance_tests_returns_list(self) -> None:
        """Handler should return valid acceptance tests list."""
        handler = ReleaseBlockerHandler()

        tests = handler.get_acceptance_tests()

        assert isinstance(tests, list)
        assert len(tests) >= 1  # At least one test defined
