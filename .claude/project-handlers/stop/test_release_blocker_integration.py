"""Integration tests for ReleaseBlockerHandler (project-specific handler).

Tests that the handler integrates correctly with the daemon system and
returns valid Stop event responses.
"""

import json
from pathlib import Path
from unittest.mock import patch

from .release_blocker import ReleaseBlockerHandler


def _write_state(root: Path) -> None:
    """Write a minimal in-flight release state under ``root``."""
    root.joinpath(*ReleaseBlockerHandler.RELEASE_STATE_PARTS[:-1]).mkdir(
        parents=True, exist_ok=True
    )
    root.joinpath(*ReleaseBlockerHandler.RELEASE_STATE_PARTS).write_text(
        json.dumps(
            {
                "version": "9.9.9",
                "authorised_by_human_at": "2026-01-01T00:00:00Z",
                "publish_authorised": False,
                "last_completed_step": 8,
            }
        ),
        encoding="utf-8",
    )


class TestReleaseBlockerIntegration:
    """Test ReleaseBlockerHandler integration with daemon system."""

    def test_handler_returns_valid_stop_response_when_blocking(self, tmp_path: Path) -> None:
        """Handler should return valid Stop event response format when blocking."""
        _write_state(tmp_path)
        handler = ReleaseBlockerHandler()

        with patch.object(ReleaseBlockerHandler, "_project_root", return_value=str(tmp_path)):
            assert handler.matches({}) is True
            result = handler.handle({})

        # Verify response structure
        assert hasattr(result, "decision")
        assert hasattr(result, "reason")
        assert result.decision is not None
        assert result.reason is not None
        assert isinstance(result.reason, str)

    def test_handler_allows_when_no_release_state_file(self, tmp_path: Path) -> None:
        """Handler should not match when no release is in flight.

        The project directory is deliberately left without a state file: that
        absence IS the documented meaning of "no release in progress".
        """
        handler = ReleaseBlockerHandler()

        with patch.object(ReleaseBlockerHandler, "_project_root", return_value=str(tmp_path)):
            assert handler.matches({}) is False

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
