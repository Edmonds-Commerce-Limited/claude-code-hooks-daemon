"""
YOLO Container Detection Handler.

Detects YOLO container environments (Claude Code CLI in containers) and provides
informational context to Claude during SessionStart events.

This handler is non-terminal and advisory - it never blocks execution, only
provides helpful context about the runtime environment.
"""

import os
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.hook_result import Decision


class YoloContainerDetectionHandler(Handler):
    """
    Detects YOLO container environments using multi-tier confidence scoring.

    Uses a confidence scoring system to detect YOLO containers:
    - Primary indicators (3 points each): Strong signals of YOLO environment
    - Secondary indicators (2 points each): Container-related signals
    - Tertiary indicators (1 point each): Weak signals

    Threshold: Score >= 3 triggers detection (prevents false positives)
    """

    def __init__(self) -> None:
        """Initialize handler with default configuration."""
        super().__init__(
            name="yolo-container-detection",
            priority=40,
            terminal=False,
            tags=["workflow", "environment", "advisory", "non-terminal"],
        )

        # Default configuration
        self.config: dict[str, Any] = {
            "min_confidence_score": 3,
            "show_detailed_indicators": True,
            "show_workflow_tips": True,
        }

    def configure(self, config: dict[str, Any]) -> None:
        """
        Apply configuration overrides.

        Args:
            config: Configuration dict with optional keys:
                - min_confidence_score: Threshold for detection (default 3)
                - show_detailed_indicators: Include indicator list (default True)
                - show_workflow_tips: Include workflow implications (default True)
        """
        # Merge with defaults (config overrides defaults)
        self.config.update(config)

    def _calculate_confidence_score(self) -> int:
        """
        Calculate confidence score based on detected indicators.

        Returns:
            Confidence score (0-12 possible range)
        """
        score = 0

        try:
            # Primary indicators (3 points each)
            if os.environ.get("CLAUDECODE") == "1":
                score += 3

            if os.environ.get("CLAUDE_CODE_ENTRYPOINT") == "cli":
                score += 3

            # Check for /workspace + .claude/ directory
            try:
                if Path.cwd() == Path("/workspace"):
                    claude_dir = Path(".claude")
                    if claude_dir.exists():
                        score += 3
            except (OSError, RuntimeError):
                # Filesystem errors - skip this check
                pass

            # Secondary indicators (2 points each)
            if os.environ.get("DEVCONTAINER") == "true":
                score += 2

            if os.environ.get("IS_SANDBOX") == "1":
                score += 2

            container_env = os.environ.get("container", "")
            if container_env in ["podman", "docker"]:
                score += 2

            # Tertiary indicators (1 point each)
            try:
                socket_path = Path(".claude/hooks-daemon/untracked/venv/socket")
                if socket_path.exists():
                    score += 1
            except (OSError, RuntimeError):
                # Filesystem errors - skip this check
                pass

            try:
                if os.getuid() == 0:
                    score += 1
            except AttributeError:
                # os.getuid() not available on Windows - skip
                pass

        except Exception:
            # Fail open - return 0 score on unexpected errors
            return 0

        return score

    def _get_detected_indicators(self) -> list[str]:
        """
        Get list of detected indicators with descriptions.

        Returns:
            List of detected indicator descriptions
        """
        indicators: list[str] = []

        try:
            # Primary indicators
            if os.environ.get("CLAUDECODE") == "1":
                indicators.append("CLAUDECODE=1 environment variable")

            if os.environ.get("CLAUDE_CODE_ENTRYPOINT") == "cli":
                indicators.append("CLAUDE_CODE_ENTRYPOINT=cli environment variable")

            try:
                if Path.cwd() == Path("/workspace") and Path(".claude").exists():
                    indicators.append("Working directory is /workspace with .claude/ present")
            except (OSError, RuntimeError):
                pass

            # Secondary indicators
            if os.environ.get("DEVCONTAINER") == "true":
                indicators.append("DEVCONTAINER=true environment variable")

            if os.environ.get("IS_SANDBOX") == "1":
                indicators.append("IS_SANDBOX=1 environment variable")

            container_env = os.environ.get("container", "")
            if container_env in ["podman", "docker"]:
                indicators.append(f"container={container_env} environment variable")

            # Tertiary indicators
            try:
                socket_path = Path(".claude/hooks-daemon/untracked/venv/socket")
                if socket_path.exists():
                    indicators.append("Hooks daemon Unix socket present")
            except (OSError, RuntimeError):
                pass

            try:
                if os.getuid() == 0:
                    indicators.append("Running as root user (UID 0)")
            except AttributeError:
                pass

        except Exception:
            # Fail open - return empty list on errors
            return []

        return indicators

    def matches(self, hook_input: dict[str, Any] | None) -> bool:
        """
        Check if this handler should run.

        Args:
            hook_input: Hook input data

        Returns:
            True if SessionStart event and confidence score >= threshold
        """
        if hook_input is None:
            return False

        if not isinstance(hook_input, dict):
            return False

        # Only match SessionStart events
        event_name = hook_input.get("hook_event_name")
        if event_name != "SessionStart":
            return False

        # Check confidence score
        try:
            score = self._calculate_confidence_score()
            threshold = int(self.config.get("min_confidence_score", 3))
            return score >= threshold
        except Exception:
            # Fail open - don't match on errors
            return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """
        Handle YOLO container detection.

        Args:
            hook_input: Hook input data

        Returns:
            HookResult with ALLOW decision and informational context
        """
        try:
            # Build context messages
            context: list[str] = []

            # Main detection message
            context.append("🐳 Running in YOLO container environment (Claude Code CLI in sandbox)")

            # Add detailed indicators if enabled
            if self.config.get("show_detailed_indicators", True):
                indicators = self._get_detected_indicators()
                if indicators:
                    context.append("Detected indicators:")
                    for indicator in indicators:
                        context.append(f"  • {indicator}")

            # Add workflow tips if enabled
            if self.config.get("show_workflow_tips", True):
                context.append("")
                context.append("Container workflow implications:")
                context.append("  • Full development environment available (git, gh, npm, pip)")
                context.append("  • Storage is ephemeral - commit and push work to persist")
                context.append("  • Running as root - install packages freely (apt, npm, pip)")
                context.append("  • Fast iteration enabled (YOLO mode, no permission prompts)")

            return HookResult(decision=Decision.ALLOW, reason=None, context=context)

        except Exception:
            # Fail open - return ALLOW with no context on errors
            return HookResult(decision=Decision.ALLOW, reason=None, context=[])
