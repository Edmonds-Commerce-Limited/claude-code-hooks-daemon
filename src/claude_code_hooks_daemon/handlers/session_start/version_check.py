"""Version check handler for SessionStart events.

Checks if the daemon is up-to-date with the latest GitHub release on new sessions only.
Uses 1-day cache to avoid excessive git operations.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    Timeout,
)
from claude_code_hooks_daemon.core import Handler, HookResult, ProjectContext
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.utils.git_repo import run_git
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session
from claude_code_hooks_daemon.version import __version__

logger = logging.getLogger(__name__)

#: Our own repo — ls-remote reads its tags to detect an available upgrade.
_GITHUB_REPO_URL: Final[str] = (
    "https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon.git"
)


class VersionCheckHandler(Handler):
    """Check daemon version against latest GitHub release on new sessions.

    Only runs on new sessions (not resume) to avoid annoying users.
    Caches result for 24 hours to minimize git overhead.
    """

    CACHE_TTL_SECONDS = 86400  # 24 hours

    def __init__(self) -> None:
        """Initialize handler."""
        super().__init__(
            handler_id=HandlerID.VERSION_CHECK,
            priority=Priority.VERSION_CHECK,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )

        self.config: dict[str, Any] = {
            "enabled": True,
            "cache_ttl_hours": 24,
        }

    def configure(self, config: dict[str, Any]) -> None:
        """Apply configuration."""
        self.config.update(config)

    def _get_cache_file(self) -> Path:
        """Get path to version check cache file."""
        try:
            cache_dir = ProjectContext.daemon_untracked_dir()
            return cache_dir / "version_check_cache.json"
        except (OSError, RuntimeError):
            # Fallback to project-relative untracked dir (avoid /tmp per B108)
            fallback = Path.cwd() / "untracked"
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback / "version_check_cache.json"

    def _is_cache_valid(self, cache_file: Path) -> bool:
        """Check if cache file exists and is not expired."""
        if not cache_file.exists():
            return False

        try:
            with open(cache_file) as f:
                cache_data = json.load(f)

            cached_at = float(cache_data.get("cached_at", 0))
            ttl_seconds = int(self.config.get("cache_ttl_hours", 24)) * 3600

            return bool((time.time() - cached_at) < ttl_seconds)
        except (OSError, json.JSONDecodeError, ValueError, KeyError):
            return False

    def _get_cached_result(self, cache_file: Path) -> dict[str, Any] | None:
        """Read cached version check result."""
        try:
            with open(cache_file) as f:
                data: dict[str, Any] = json.load(f)
                return data
        except (OSError, json.JSONDecodeError):
            return None

    def _write_cache(self, cache_file: Path, data: dict[str, Any]) -> None:
        """Write version check result to cache."""
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_file, "w") as f:
                json.dump(data, f)
        except (OSError, TypeError) as e:
            logger.debug("Failed to write version cache: %s", e)

    def _get_latest_version(self) -> str | None:
        """Get latest version tag from GitHub (git ls-remote).

        Returns:
            Latest version string (e.g., "2.7.0") or None if failed
        """
        # SECURITY: fixed argv, no shell, trusted URL (our own repository). ``-C``
        # needs an existing directory, but ls-remote talks only to the remote
        # URL, so the cwd is immaterial — the process cwd always exists.
        # run_git never raises: an absent git binary or a timeout comes back as
        # a non-zero returncode with the reason in stderr, so there is nothing
        # left to catch here.
        result = run_git(
            Path.cwd(),
            "ls-remote",
            "--tags",
            "--refs",
            "--sort=-v:refname",
            _GITHUB_REPO_URL,
            timeout=Timeout.VERSION_CHECK,
        )

        if result.returncode != 0:
            logger.debug("git ls-remote failed: %s", result.stderr)
            return None

        # Parse output: "hash refs/tags/vX.Y.Z"
        # Get first line (latest version)
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                tag = parts[1].split("/")[-1]  # refs/tags/v2.7.0 -> v2.7.0
                if tag.startswith("v"):
                    return tag[1:]  # v2.7.0 -> 2.7.0
                return tag

        return None

    def matches(self, hook_input: dict[str, Any] | None) -> bool:
        """Check if handler should run.

        Only runs on NEW SessionStart events (not resume).
        """
        if not hook_input or not isinstance(hook_input, dict):
            return False

        if not self.config.get("enabled", True):
            return False

        event_name = hook_input.get(HookInputField.HOOK_EVENT_NAME)
        if event_name != "SessionStart":
            return False

        # Only run on new sessions (not resume)
        return not is_resume_session(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Check daemon version and advise upgrade if outdated.

        Returns:
            HookResult with upgrade notice if outdated, empty if up-to-date
        """
        try:
            cache_file = self._get_cache_file()

            # Check cache first
            if self._is_cache_valid(cache_file):
                cached = self._get_cached_result(cache_file)
                if cached and not cached.get("is_outdated", False):
                    # Cache says we're up to date
                    return HookResult(decision=Decision.ALLOW, reason=None, context=[])

            # Fetch latest version
            latest_version = self._get_latest_version()

            if latest_version is None:
                # Failed to check - fail silently
                logger.debug("Could not check daemon version")
                return HookResult(decision=Decision.ALLOW, reason=None, context=[])

            # Compare versions
            current = __version__
            is_outdated = self._compare_versions(current, latest_version)

            # Cache result
            cache_data = {
                "cached_at": time.time(),
                "current_version": current,
                "latest_version": latest_version,
                "is_outdated": is_outdated,
            }
            self._write_cache(cache_file, cache_data)

            if not is_outdated:
                # Up to date - no message
                return HookResult(decision=Decision.ALLOW, reason=None, context=[])

            # Outdated - show upgrade notice
            context = [
                f"📦 Hooks daemon update available: v{current} → v{latest_version}",
                "",
                "To upgrade, use the hooks-daemon skill to upgrade "
                "(Skill tool: skill=hooks-daemon, args=upgrade).",
                "It fetches the latest upgrade script, runs it, reconciles project",
                "docs, and commits the result atomically — no manual steps needed.",
                "",
                "💡 New features and fixes available in the latest version.",
            ]

            return HookResult(decision=Decision.ALLOW, reason=None, context=context)

        except Exception as e:
            logger.error("Version check failed: %s", e, exc_info=True)
            return HookResult(decision=Decision.ALLOW, reason=None, context=[])

    def _compare_versions(self, current: str, latest: str) -> bool:
        """Compare semantic versions.

        Args:
            current: Current version (e.g., "2.6.1")
            latest: Latest version (e.g., "2.7.0")

        Returns:
            True if current < latest (outdated)
        """
        try:
            current_parts = [int(x) for x in current.split(".")]
            latest_parts = [int(x) for x in latest.split(".")]

            # Pad to same length
            while len(current_parts) < len(latest_parts):
                current_parts.append(0)
            while len(latest_parts) < len(current_parts):
                latest_parts.append(0)

            # Compare major.minor.patch
            return current_parts < latest_parts

        except (ValueError, AttributeError):
            # Parse error - assume not outdated
            return False

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="version check handler test",
                command='echo "test"',
                description="Tests version check handler on new session",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Advisory handler - provides version update notifications",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session, not resume)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
