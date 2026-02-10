"""Tests for AccountDisplayHandler."""

from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.handlers.status_line import AccountDisplayHandler


class TestAccountDisplayHandler:
    """Tests for AccountDisplayHandler."""

    @pytest.fixture
    def handler(self) -> AccountDisplayHandler:
        """Create handler instance."""
        return AccountDisplayHandler()

    def test_handler_properties(self, handler: AccountDisplayHandler) -> None:
        """Test handler has correct properties."""
        assert handler.name == "status-account-display"
        assert handler.priority == 5
        assert handler.terminal is False
        assert "status" in handler.tags
        assert "display" in handler.tags

    def test_matches_always_returns_true(self, handler: AccountDisplayHandler) -> None:
        """Handler should always match for status events."""
        assert handler.matches({}) is True
        assert handler.matches({"session_id": "test"}) is True

    def test_handle_with_valid_conf_file(self, handler: AccountDisplayHandler) -> None:
        """Test formatting with valid .last-launch.conf file."""
        conf_content = """
# Last launch configuration
LAST_TOKEN="ballicom_rohil"
LAST_TIME="2025-01-29T10:30:00Z"
"""
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", return_value=conf_content):
                result = handler.handle({})

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert "ballicom_rohil" in result.context[0]
        assert result.context[0] == "👤 ballicom_rohil |"

    def test_handle_with_different_username(self, handler: AccountDisplayHandler) -> None:
        """Test formatting with different username."""
        conf_content = 'LAST_TOKEN="john_doe"'

        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", return_value=conf_content):
                result = handler.handle({})

        assert result.decision == "allow"
        assert result.context == ["👤 john_doe |"]

    def test_handle_with_missing_file(self, handler: AccountDisplayHandler) -> None:
        """Test handling when .last-launch.conf doesn't exist."""
        with patch("pathlib.Path.exists", return_value=False):
            result = handler.handle({})

        # Should return empty context (silent fail)
        assert result.decision == "allow"
        assert result.context == []

    def test_handle_with_invalid_format(self, handler: AccountDisplayHandler) -> None:
        """Test handling when .last-launch.conf has invalid format."""
        conf_content = "SOME_OTHER_VAR=value\nINVALID_LINE"

        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", return_value=conf_content):
                result = handler.handle({})

        # Should return empty context (silent fail)
        assert result.decision == "allow"
        assert result.context == []

    def test_handle_with_read_error(self, handler: AccountDisplayHandler) -> None:
        """Test handling when reading file raises exception."""
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", side_effect=PermissionError("Access denied")):
                result = handler.handle({})

        # Should return empty context (silent fail)
        assert result.decision == "allow"
        assert result.context == []

    def test_handle_with_empty_token(self, handler: AccountDisplayHandler) -> None:
        """Test handling when token value is empty."""
        conf_content = 'LAST_TOKEN=""'

        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", return_value=conf_content):
                result = handler.handle({})

        # Empty token should still be shown
        assert result.decision == "allow"
        assert result.context == ["👤  |"]

    def test_conf_file_path_is_correct(self, handler: AccountDisplayHandler) -> None:
        """Test that handler looks in correct path."""
        with patch("pathlib.Path.exists", return_value=True) as mock_exists:
            with patch("pathlib.Path.read_text", return_value='LAST_TOKEN="test"') as mock_read:
                handler.handle({})

                # Verify exists() was called
                assert mock_exists.called
                # Verify read_text() was called (means we found the file)
                assert mock_read.called
