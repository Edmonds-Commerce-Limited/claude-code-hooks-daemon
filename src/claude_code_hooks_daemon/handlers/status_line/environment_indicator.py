"""EnvironmentIndicatorHandler - desktop vs container icon in the status line.

Confirms at a glance whether the session runs at desktop (host) level or inside
a container. Reads the container runtime that :class:`ProjectContext` detected
ONCE at daemon startup — the status line re-renders on every Claude Code
refresh, so this handler does no per-render probing.
"""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, ProjectContext
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest
from claude_code_hooks_daemon.core.handler_bases import StatusLineHandlerBase

# ANSI colours — each environment renders in a distinct colour so the runtime
# is identifiable at a glance. Desktop is red (you are on the host); container
# runtimes use distinct, brand-relevant-where-possible, non-semantic colours:
# docker=blue (Docker brand), podman=magenta/purple (Podman brand), lxc=cyan
# (no strong brand colour — kept distinct), generic=grey. (Matches the inline
# ANSI-constant convention used by git_branch.py / model_context.py.)
_COLOR_RED = "\033[31m"
_COLOR_BLUE = "\033[34m"
# Bright magenta (90-series) — plain magenta (35) is too dark on a black
# terminal; the bright variant reads as a lighter purple/pink (Podman brand).
_COLOR_BRIGHT_MAGENTA = "\033[95m"
_COLOR_CYAN = "\033[36m"
_COLOR_GREY = "\033[37m"
_COLOR_RESET = "\033[0m"

# Runtime → (icon, label, colour). None (host) is handled separately as desktop.
_DESKTOP_ICON = "💻"
_DESKTOP_LABEL = "desktop"
_DESKTOP_COLOR = _COLOR_RED
_RUNTIME_DISPLAY: dict[str, tuple[str, str, str]] = {
    "docker": ("🐳", "docker", _COLOR_BLUE),
    "podman": ("📦", "podman", _COLOR_BRIGHT_MAGENTA),
    "generic": ("📦", "container", _COLOR_GREY),
    "lxc": ("🧊", "lxc", _COLOR_CYAN),
}
# Fallback for an unexpected non-empty runtime label (forward-compatible).
_UNKNOWN_RUNTIME_ICON = "📦"
_UNKNOWN_RUNTIME_COLOR = _COLOR_GREY


class EnvironmentIndicatorHandler(StatusLineHandlerBase):
    """Show 💻 (desktop/host) or a container icon (🐳 docker / 📦 podman / 🧊 lxc)."""

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

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Return the environment-indicator segment from the cached runtime."""
        runtime = ProjectContext.container_runtime()
        if runtime is None:
            icon, label, color = _DESKTOP_ICON, _DESKTOP_LABEL, _DESKTOP_COLOR
        else:
            icon, label, color = _RUNTIME_DISPLAY.get(
                runtime, (_UNKNOWN_RUNTIME_ICON, runtime, _UNKNOWN_RUNTIME_COLOR)
            )
        return AdvisoryResult(context=[f"| {color}{icon} {label}{_COLOR_RESET}"])

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
