"""YOLO Container Detection Handler.

Detects when Claude Code is running inside a real container (Docker, Podman, or
generic OCI) and injects informational context about the container environment
during SessionStart events.

This handler is non-terminal and advisory — it never blocks execution, only
provides helpful context about the runtime environment.  It fires ONLY when an
honest container marker is present (``/.dockerenv``, ``/run/.containerenv``,
``/proc/1/cgroup`` token, or the ``container`` env var).  It does NOT fire on
desktop sessions, even when ``CLAUDECODE=1`` / ``CLAUDE_CODE_ENTRYPOINT=cli``
are set — those signals indicate "running under Claude Code", not "in a
container".
"""

import logging
import os
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.utils.container_detection import (
    detect_container_runtime,
    in_container,
    is_yolo_sandbox,
)

logger = logging.getLogger(__name__)

# Container-runtime icon mapping (no magic strings: keys match util return values)
_RUNTIME_DOCKER = "docker"
_ICON_DOCKER = "🐳"
_ICON_CONTAINER = "📦"  # podman + generic

# Transcript size threshold: files larger than this are treated as resume sessions
_RESUME_TRANSCRIPT_MIN_BYTES = 100

# Config key names (no magic strings)
_CFG_SHOW_DETAILED_INDICATORS = "show_detailed_indicators"
_CFG_SHOW_WORKFLOW_TIPS = "show_workflow_tips"

# Default config values
_DEFAULT_SHOW_DETAILED_INDICATORS = True
_DEFAULT_SHOW_WORKFLOW_TIPS = True

# Session event name constant (avoids magic string)
_EVENT_SESSION_START = "SessionStart"

# Fallback label when detect_container_runtime() returns None inside handle()
_FALLBACK_RUNTIME_LABEL = "container"


def _runtime_icon(runtime: str) -> str:
    """Return the display icon for a container runtime string."""
    if runtime == _RUNTIME_DOCKER:
        return _ICON_DOCKER
    return _ICON_CONTAINER


class YoloContainerDetectionHandler(Handler):
    """Detects YOLO container environments using precise OS-level container markers.

    Fires only when ``in_container()`` returns True (honest container markers:
    ``/.dockerenv``, ``/run/.containerenv``, ``/proc/1/cgroup`` token, or the
    ``container`` env var).  Never fires on desktop Claude Code sessions where
    those markers are absent.
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

        # Default configuration — only the two display-control keys are meaningful.
        # Unknown keys passed via configure() are stored but ignored (tolerated).
        self.config: dict[str, Any] = {
            _CFG_SHOW_DETAILED_INDICATORS: _DEFAULT_SHOW_DETAILED_INDICATORS,
            _CFG_SHOW_WORKFLOW_TIPS: _DEFAULT_SHOW_WORKFLOW_TIPS,
        }

    def configure(self, config: dict[str, Any]) -> None:
        """Apply configuration overrides.

        Args:
            config: Configuration dict with optional keys:
                - show_detailed_indicators: Include indicator list (default True)
                - show_workflow_tips: Include workflow implications (default True)

        Unknown keys are stored but ignored — the handler never crashes on
        unrecognised options (backward-compatible tolerance).
        """
        self.config.update(config)

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
            return path.stat().st_size > _RESUME_TRANSCRIPT_MIN_BYTES
        except (OSError, ValueError):
            return False

    def _build_indicators(self, runtime: str) -> list[str]:
        """Build the list of honest container indicators.

        Args:
            runtime: Detected container runtime label.

        Returns:
            List of human-readable indicator strings.
        """
        indicators: list[str] = [f"Container runtime: {runtime}"]

        # is_yolo_sandbox() is itself fail-safe (returns False, logging internally).
        if is_yolo_sandbox():
            indicators.append("YOLO/auto-approve sandbox detected (IS_SANDBOX or DEVCONTAINER)")

        # os.getuid() is absent on Windows; guard with hasattr rather than
        # catching AttributeError so no exception is silently discarded.
        if hasattr(os, "getuid") and os.getuid() == 0:
            indicators.append("Running as root user (UID 0)")

        return indicators

    def matches(self, hook_input: dict[str, Any] | None) -> bool:
        """Return True only for SessionStart events running inside a container.

        Args:
            hook_input: Hook input data (must be a non-None dict with
                ``hook_event_name == "SessionStart"`` and an honest container
                marker present).

        Returns:
            True iff the event is SessionStart AND ``in_container()`` is True.
        """
        if hook_input is None:
            return False

        if not isinstance(hook_input, dict):
            return False

        event_name = hook_input.get(HookInputField.HOOK_EVENT_NAME)
        if event_name != _EVENT_SESSION_START:
            return False

        try:
            return in_container()
        except (OSError, RuntimeError) as exc:
            logger.debug("YOLO container check failed: %s", exc)
            return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Handle YOLO container detection.

        Builds an informational advisory message describing the container
        runtime (docker / podman / generic), optionally including detected
        indicators and workflow tips.

        Args:
            hook_input: Hook input data

        Returns:
            HookResult with ALLOW decision and informational context

        Raises:
            Never — all exceptions are caught and converted to an ALLOW
            (for expected OS/runtime errors) or DENY (for unexpected errors).
        """
        try:
            is_resume = self._is_resume_session(hook_input)

            runtime = detect_container_runtime() or _FALLBACK_RUNTIME_LABEL
            icon = _runtime_icon(runtime)

            context: list[str] = []

            if is_resume:
                context.append(f"{icon} Running in a {runtime} container (Claude Code CLI sandbox)")
            else:
                context.append(f"{icon} Running in a {runtime} container (Claude Code CLI sandbox)")

                if self.config.get(
                    _CFG_SHOW_DETAILED_INDICATORS, _DEFAULT_SHOW_DETAILED_INDICATORS
                ):
                    indicators = self._build_indicators(runtime)
                    if indicators:
                        context.append("Detected indicators:")
                        for indicator in indicators:
                            context.append(f"  • {indicator}")

                if self.config.get(_CFG_SHOW_WORKFLOW_TIPS, _DEFAULT_SHOW_WORKFLOW_TIPS):
                    context.append("")
                    context.append("Container workflow implications:")
                    context.append("  • Full development environment available (git, gh, npm, pip)")
                    context.append("  • Storage is ephemeral — commit and push work to persist")
                    context.append("  • Running as root — install packages freely (apt, npm, pip)")
                    context.append("  • Fast iteration enabled (YOLO mode, no permission prompts)")

            return HookResult(decision=Decision.ALLOW, reason=None, context=context)

        except (OSError, RuntimeError, AttributeError) as exc:
            logger.warning("YOLO container detection failed: %s", exc, exc_info=True)
            return HookResult(
                decision=Decision.ALLOW,
                reason=None,
                context=[f"⚠️  YOLO detection failed: {exc}"],
            )

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
                title="yolo container detection handler test",
                command='echo "test"',
                description=(
                    "Tests yolo container detection handler functionality "
                    "in a container environment"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes=(
                    "Context/utility handler — only fires when honest container "
                    "markers are present"
                ),
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
