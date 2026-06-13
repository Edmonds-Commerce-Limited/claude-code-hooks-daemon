"""EnvironmentIndicatorHandler - desktop vs container icon in the status line.

Confirms at a glance whether the session runs at desktop (host) level or inside
a container. Reads the container runtime that :class:`ProjectContext` detected
ONCE at daemon startup — the status line re-renders on every Claude Code
refresh, so this handler does no per-render probing.
"""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Handler, HookResult, ProjectContext
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest

# Runtime → (icon, label). None (host) is handled separately as desktop.
_DESKTOP_ICON = "💻"
_DESKTOP_LABEL = "desktop"
_RUNTIME_DISPLAY: dict[str, tuple[str, str]] = {
    "docker": ("🐳", "docker"),
    "podman": ("📦", "podman"),
    "generic": ("📦", "container"),
}
# Fallback for an unexpected non-empty runtime label (forward-compatible).
_UNKNOWN_RUNTIME_ICON = "📦"


class EnvironmentIndicatorHandler(Handler):
    """Show 💻 (desktop/host) or a container icon (🐳 docker / 📦 podman)."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.ENVIRONMENT_INDICATOR,
            priority=Priority.ENVIRONMENT_INDICATOR,
            terminal=False,
            tags=[
                HandlerTag.STATUSLINE,
                HandlerTag.ENVIRONMENT,
                HandlerTag.DISPLAY,
                HandlerTag.NON_TERMINAL,
            ],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status line events."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Return the environment-indicator segment from the cached runtime."""
        runtime = ProjectContext.container_runtime()
        if runtime is None:
            icon, label = _DESKTOP_ICON, _DESKTOP_LABEL
        else:
            icon, label = _RUNTIME_DISPLAY.get(runtime, (_UNKNOWN_RUNTIME_ICON, runtime))
        return HookResult(context=[f"| {icon} {label}"])

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import Decision, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="environment indicator handler test",
                command='echo "test"',
                description=(
                    "Verify the environment indicator shows a container icon "
                    "(🐳/📦) in a container or 💻 on a desktop host. Confirmed "
                    "active by the daemon loading without errors."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            )
        ]
