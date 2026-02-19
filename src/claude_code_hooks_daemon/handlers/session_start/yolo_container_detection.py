"""
YOLO Container Detection Handler.

Detects YOLO container environments (Claude Code CLI in containers) and provides
informational context to Claude during SessionStart events.

This handler is non-terminal and advisory - it never blocks execution, only
provides helpful context about the runtime environment.
"""

import logging
import os
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import Handler, HookResult, ProjectContext
from claude_code_hooks_daemon.core.hook_result import Decision

logger = logging.getLogger(__name__)


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
            handler_id=HandlerID.YOLO_CONTAINER_DETECTION,
            priority=Priority.YOLO_CONTAINER_DETECTION,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.ENVIRONMENT,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
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
                if ProjectContext.project_root() == Path("/workspace"):
                    if ProjectContext.config_dir().exists():
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

        except (OSError, RuntimeError, AttributeError) as e:
            logger.debug("Confidence score calculation failed: %s", e)
            return 0
        except Exception as e:
            logger.error("Unexpected error in confidence score: %s", e, exc_info=True)
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
                if (
                    ProjectContext.project_root() == Path("/workspace")
                    and ProjectContext.config_dir().exists()
                ):
                    indicators.append("Project root is /workspace with .claude/ present")
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

        except (OSError, RuntimeError, AttributeError) as e:
            logger.debug("Indicator detection failed: %s", e)
            return []
        except Exception as e:
            logger.error("Unexpected error detecting indicators: %s", e, exc_info=True)
            return []

        return indicators

    def _is_resume_session(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a resumed session (transcript exists with content).

        Args:
            hook_input: SessionStart hook input

        Returns:
            True if resume, False if new session
        """
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        if not transcript_path:
            return False

        try:
            path = Path(transcript_path)
            if not path.exists():
                return False

            # If file exists and has content (>100 bytes), it's a resume
            return path.stat().st_size > 100

        except (OSError, ValueError):
            return False

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
        event_name = hook_input.get(HookInputField.HOOK_EVENT_NAME)
        if event_name != "SessionStart":
            return False

        # Check confidence score
        try:
            score = self._calculate_confidence_score()
            threshold = int(self.config.get("min_confidence_score", 3))
            return score >= threshold
        except (ValueError, TypeError, AttributeError) as e:
            logger.debug("YOLO match check failed: %s", e)
            return False
        except Exception as e:
            logger.error("Unexpected error in YOLO matches(): %s", e, exc_info=True)
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
            # Check if this is a resume - if so, be brief
            is_resume = self._is_resume_session(hook_input)

            # Build context messages
            context: list[str] = []

            if is_resume:
                # Brief message for resume - context already loaded
                context.append("🐳 YOLO container (Claude Code CLI in sandbox)")
            else:
                # Detailed message for new sessions
                # Main detection message
                context.append(
                    "🐳 Running in YOLO container environment (Claude Code CLI in sandbox)"
                )

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

        except (OSError, RuntimeError, AttributeError) as e:
            logger.warning("YOLO container detection failed: %s", e, exc_info=True)
            return HookResult(
                decision=Decision.ALLOW, reason=None, context=[f"⚠️  YOLO detection failed: {e}"]
            )
        except Exception as e:
            logger.error("YOLO handler encountered unexpected error: %s", e, exc_info=True)
            return HookResult(
                decision=Decision.DENY,
                reason=f"YOLO handler error: {e}",
                context=["Contact support if this persists."],
            )

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
                title="yolo container detection handler test",
                command='echo "test"',
                description="Tests yolo container detection handler functionality",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
