"""API usage client for OAuth-based usage tracking.

Reads API token from environment variable (ANTHROPIC_API_KEY) or Claude's
credentials file and fetches usage data from the Anthropic API. All errors
are handled gracefully - this module should never crash the status line.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"
ANTHROPIC_BETA_HEADER = "oauth-2025-04-20"
API_TIMEOUT_SECONDS = 5
# Environment variable names (priority order)
OAUTH_TOKEN_ENV_VAR = "CLAUDE_CODE_OAUTH_TOKEN"  # nosec B105
API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"  # nosec B105


class ApiUsageClient:
    """Client for fetching Claude usage data via OAuth API."""

    def __init__(self) -> None:
        self.default_credentials_path = Path.home() / ".claude" / ".credentials.json"

    def get_credentials(self, credentials_path: Path | None = None) -> str | None:
        """Read API token from environment variable or credentials file.

        Priority order:
        1. ANTHROPIC_API_KEY environment variable (Console API key - RECOMMENDED)
        2. CLAUDE_CODE_OAUTH_TOKEN environment variable (blocked for usage API since Jan 2026)
        3. ~/.claude/.credentials.json OAuth file (blocked for usage API since Jan 2026)

        Note: As of January 2026, Claude Code OAuth tokens cannot be used with third-party
        API calls. Use an API key from console.anthropic.com instead.

        Args:
            credentials_path: Path to credentials file. Defaults to ~/.claude/.credentials.json

        Returns:
            API token string, or None if unavailable
        """
        # Try ANTHROPIC_API_KEY first (works with usage API)
        api_key = os.getenv(API_KEY_ENV_VAR)
        if api_key:
            logger.debug("Using API key from %s environment variable", API_KEY_ENV_VAR)
            return api_key

        # Try CLAUDE_CODE_OAUTH_TOKEN (likely blocked for usage API)
        oauth_token = os.getenv(OAUTH_TOKEN_ENV_VAR)
        if oauth_token:
            logger.debug(
                "Using OAuth token from %s (may not work for usage API)", OAUTH_TOKEN_ENV_VAR
            )
            return oauth_token

        # Fall back to credentials file
        path = credentials_path or self.default_credentials_path

        if not path.exists():
            logger.debug(
                "No API key found: %s/%s not set and %s does not exist",
                OAUTH_TOKEN_ENV_VAR,
                API_KEY_ENV_VAR,
                path,
            )
            return None

        try:
            raw = path.read_text()
            data = json.loads(raw)
            oauth = data.get("claudeAiOauth")
            if not oauth:
                return None
            token: str | None = oauth.get("accessToken")
            return token
        except (json.JSONDecodeError, OSError):
            logger.info("Failed to read credentials file")
            return None

    def fetch_usage(self, token: str) -> dict[str, Any] | None:
        """Fetch usage data from Anthropic API.

        SECURITY: Token is used only for the request header and never logged or stored.

        Args:
            token: OAuth access token

        Returns:
            Parsed JSON response dict, or None on any error
        """
        request = urllib.request.Request(
            USAGE_API_URL,
            method="GET",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "Anthropic-beta": ANTHROPIC_BETA_HEADER,
                "User-Agent": "claude-code-hooks-daemon/1.0",
            },
        )

        try:
            # SECURITY: URL is a module-level constant (USAGE_API_URL) using https:// scheme only.
            # B310 flags urlopen for potential file:// scheme abuse, but this is safe because
            # the URL is hardcoded and never derived from user input.
            with urllib.request.urlopen(
                request, timeout=API_TIMEOUT_SECONDS
            ) as response:  # nosec B310
                raw = response.read()
                result: dict[str, Any] = json.loads(raw)
                return result
        except urllib.error.HTTPError as e:
            logger.info("API returned HTTP %d: %s", e.code, e.reason)
            return None
        except (urllib.error.URLError, OSError):
            logger.info("Failed to fetch usage data from API")
            return None
        except (json.JSONDecodeError, ValueError):
            logger.info("Failed to parse usage API response")
            return None

    def get_usage(self, credentials_path: Path | None = None) -> dict[str, Any] | None:
        """Full flow: read credentials and fetch usage data.

        Args:
            credentials_path: Optional path to credentials file

        Returns:
            Parsed usage data dict, or None if unavailable
        """
        token = self.get_credentials(credentials_path)
        if not token:
            return None

        return self.fetch_usage(token)
