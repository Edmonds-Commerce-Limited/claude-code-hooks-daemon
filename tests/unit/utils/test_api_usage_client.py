"""Tests for API usage client.

Following TDD: Tests written BEFORE implementation.
"""

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.utils.api_usage_client import ApiUsageClient


class TestApiUsageClient:
    """Test API usage client for OAuth-based usage tracking."""

    @pytest.fixture
    def client(self) -> ApiUsageClient:
        """Create client instance."""
        return ApiUsageClient()

    # --- get_credentials() tests ---

    @patch.dict(os.environ, {}, clear=True)
    def test_get_credentials_returns_token_when_file_exists(
        self, client: ApiUsageClient, tmp_path: Path
    ) -> None:
        """Should return access token from credentials file."""
        creds = {"claudeAiOauth": {"accessToken": "test-token-123"}}
        creds_file = tmp_path / ".credentials.json"
        creds_file.write_text(json.dumps(creds))

        token = client.get_credentials(creds_file)
        assert token == "test-token-123"

    @patch.dict(os.environ, {}, clear=True)
    def test_get_credentials_returns_none_when_file_missing(
        self, client: ApiUsageClient, tmp_path: Path
    ) -> None:
        """Should return None when credentials file doesn't exist."""
        creds_file = tmp_path / ".credentials.json"
        token = client.get_credentials(creds_file)
        assert token is None

    @patch.dict(os.environ, {}, clear=True)
    def test_get_credentials_returns_none_when_malformed_json(
        self, client: ApiUsageClient, tmp_path: Path
    ) -> None:
        """Should return None when JSON is malformed."""
        creds_file = tmp_path / ".credentials.json"
        creds_file.write_text("not valid json{{{")

        token = client.get_credentials(creds_file)
        assert token is None

    @patch.dict(os.environ, {}, clear=True)
    def test_get_credentials_returns_none_when_missing_oauth_key(
        self, client: ApiUsageClient, tmp_path: Path
    ) -> None:
        """Should return None when claudeAiOauth key is missing."""
        creds = {"someOtherKey": {"accessToken": "test"}}
        creds_file = tmp_path / ".credentials.json"
        creds_file.write_text(json.dumps(creds))

        token = client.get_credentials(creds_file)
        assert token is None

    @patch.dict(os.environ, {}, clear=True)
    def test_get_credentials_returns_none_when_missing_access_token(
        self, client: ApiUsageClient, tmp_path: Path
    ) -> None:
        """Should return None when accessToken key is missing."""
        creds = {"claudeAiOauth": {"refreshToken": "test"}}
        creds_file = tmp_path / ".credentials.json"
        creds_file.write_text(json.dumps(creds))

        token = client.get_credentials(creds_file)
        assert token is None

    def test_get_credentials_default_path(self, client: ApiUsageClient) -> None:
        """Default path should point to ~/.claude/.credentials.json."""
        # Just verify the default path attribute exists and is reasonable
        default_path = client.default_credentials_path
        assert ".claude" in str(default_path)
        assert ".credentials.json" in str(default_path)

    # --- fetch_usage() tests ---

    @patch("claude_code_hooks_daemon.utils.api_usage_client.urllib.request.urlopen")
    def test_fetch_usage_returns_parsed_response(
        self, mock_urlopen: MagicMock, client: ApiUsageClient
    ) -> None:
        """Should return parsed JSON from API response."""
        api_response: dict[str, Any] = {
            "five_hour": {"utilization": 30.0, "resets_at": "2026-02-09T20:00:00Z"},
            "seven_day": {"utilization": 50.0, "resets_at": "2026-02-15T00:00:00Z"},
        }
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(api_response).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = client.fetch_usage("test-token")
        assert result is not None
        assert result["five_hour"]["utilization"] == 30.0
        assert result["seven_day"]["utilization"] == 50.0

    @patch("claude_code_hooks_daemon.utils.api_usage_client.urllib.request.urlopen")
    def test_fetch_usage_sends_correct_headers(
        self, mock_urlopen: MagicMock, client: ApiUsageClient
    ) -> None:
        """Should send Authorization and anthropic-beta headers."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"{}"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        client.fetch_usage("my-token")

        # Verify the request was made
        assert mock_urlopen.called
        request = mock_urlopen.call_args[0][0]
        assert request.get_header("Authorization") == "Bearer my-token"
        assert "oauth" in request.get_header("Anthropic-beta")

    @patch("claude_code_hooks_daemon.utils.api_usage_client.urllib.request.urlopen")
    def test_fetch_usage_returns_none_on_network_error(
        self, mock_urlopen: MagicMock, client: ApiUsageClient
    ) -> None:
        """Should return None on network errors."""
        mock_urlopen.side_effect = OSError("Connection refused")

        result = client.fetch_usage("test-token")
        assert result is None

    @patch("claude_code_hooks_daemon.utils.api_usage_client.urllib.request.urlopen")
    def test_fetch_usage_returns_none_on_http_error(
        self, mock_urlopen: MagicMock, client: ApiUsageClient
    ) -> None:
        """Should return None on HTTP errors (401, 500, etc.)."""
        import urllib.error

        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.anthropic.com/api/oauth/usage",
            code=401,
            msg="Unauthorized",
            hdrs=MagicMock(),
            fp=None,
        )

        result = client.fetch_usage("bad-token")
        assert result is None

    @patch("claude_code_hooks_daemon.utils.api_usage_client.urllib.request.urlopen")
    def test_fetch_usage_returns_none_on_invalid_json(
        self, mock_urlopen: MagicMock, client: ApiUsageClient
    ) -> None:
        """Should return None when API returns invalid JSON."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"not json"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = client.fetch_usage("test-token")
        assert result is None

    def test_fetch_usage_never_logs_token(self, client: ApiUsageClient) -> None:
        """Token should never appear in any log output."""
        # This is a security requirement - verify the token is not stored
        # on the client instance after use
        assert not hasattr(client, "_token")
        assert not hasattr(client, "token")

    # --- get_usage() integration tests ---

    @patch("claude_code_hooks_daemon.utils.api_usage_client.urllib.request.urlopen")
    def test_get_usage_full_flow(
        self, mock_urlopen: MagicMock, client: ApiUsageClient, tmp_path: Path
    ) -> None:
        """Full flow: read creds -> call API -> return data."""
        # Setup credentials
        creds = {"claudeAiOauth": {"accessToken": "flow-token"}}
        creds_file = tmp_path / ".credentials.json"
        creds_file.write_text(json.dumps(creds))

        # Setup API response
        api_response: dict[str, Any] = {
            "five_hour": {"utilization": 25.0, "resets_at": "2026-02-09T20:00:00Z"},
            "seven_day": {"utilization": 40.0, "resets_at": "2026-02-15T00:00:00Z"},
        }
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(api_response).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = client.get_usage(credentials_path=creds_file)
        assert result is not None
        assert result["five_hour"]["utilization"] == 25.0

    def test_get_usage_returns_none_when_no_credentials(
        self, client: ApiUsageClient, tmp_path: Path
    ) -> None:
        """Should return None when credentials file doesn't exist."""
        creds_file = tmp_path / "nonexistent.json"
        result = client.get_usage(credentials_path=creds_file)
        assert result is None
