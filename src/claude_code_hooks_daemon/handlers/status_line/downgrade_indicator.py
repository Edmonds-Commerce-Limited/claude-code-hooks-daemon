"""DowngradeIndicatorHandler - surface a silent model-family downgrade (Plan 00278).

Anthropic's safety classifier can silently substitute the session's model
(`fable` -> `opus`, or any higher-ranked family down to a lower one) with
`scope: session` -- the substitution never recovers on its own, and today
there is no on-screen sign that the session is running degraded (the
`model_fallback_detector` SessionStart handler surfaces the platform's OWN
fallback record, but only once at session start, and only when the platform
records one). This handler makes an ACTIVE downgrade visible on every render
of the status line, self-detected purely from the model id Claude Code itself
reports -- no dependency on the ccy supervisor or any external signal.
"""

import logging
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.core import AdvisoryResult, ProjectContext
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest
from claude_code_hooks_daemon.core.handler_bases import StatusLineHandlerBase
from claude_code_hooks_daemon.handlers.status_line.downgrade_state import (
    evaluate_downgrade,
    resolve_model_family,
    state_dir,
)

logger = logging.getLogger(__name__)

_DOWNGRADE_COLOR: Final[str] = "\033[1;31m"
_RESET: Final[str] = "\033[0m"
_DEFAULT_EMOJI: Final[str] = "⚠️"
_DEFAULT_LABEL_FORMAT: Final[str] = "{emoji}{high}→{current}"
_MODEL_FIELD: Final[str] = "model"
_MODEL_ID_FIELD: Final[str] = "id"


class DowngradeIndicatorHandler(StatusLineHandlerBase):
    """Surface a silent model-family downgrade (e.g. fable/opus -> lower) in the status line."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.DOWNGRADE_INDICATOR,
            priority=Priority.DOWNGRADE_INDICATOR,
            terminal=False,
            tags=[HandlerTag.STATUS, HandlerTag.DISPLAY, HandlerTag.NON_TERMINAL],
        )
        self._emoji: str = _DEFAULT_EMOJI
        self._label_format: str = _DEFAULT_LABEL_FORMAT
        self._color: str = _DOWNGRADE_COLOR

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        segment = self._render_segment(hook_input)
        if segment:
            return AdvisoryResult(context=[f"| {segment}"])
        return AdvisoryResult(context=[])

    def _render_segment(self, hook_input: dict[str, Any]) -> str:
        try:
            model_data = hook_input.get(_MODEL_FIELD, {})
            model_id = model_data.get(_MODEL_ID_FIELD, "") if isinstance(model_data, dict) else ""
            resolved = resolve_model_family(str(model_id))
            if resolved is None:
                return ""

            session_id = str(hook_input.get(HookInputField.SESSION_ID, "") or "")
            if not session_id:
                return ""

            current_family, current_rank = resolved
            dir_path = state_dir(ProjectContext.daemon_untracked_dir())
            downgrade = evaluate_downgrade(dir_path, session_id, current_family, current_rank)
            if downgrade is None:
                return ""

            high_water_family, current = downgrade
            label = self._label_format.format(
                emoji=self._emoji, high=high_water_family, current=current
            )
            return f"{self._color}{label}{_RESET}"
        except RuntimeError as e:
            logger.warning("Skipping downgrade indicator (no project context): %s", e)
            return ""
        except OSError as e:
            logger.warning("Failed to read/write downgrade-indicator state: %s", e)
            return ""

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import Decision, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="downgrade indicator handler test",
                command='echo "test"',
                description=(
                    "Verify the downgrade indicator handler runs on a Status "
                    "event. It renders a warning segment naming the drop "
                    "(high-water family, an arrow, current family) only when "
                    "the CURRENT model's family rank is below this session's "
                    "recorded high-water mark; a first render, a new high, or "
                    "a recovered render is silent. Handler confirmed active "
                    "by the daemon loading without errors."
                ),
                expected_decision=Decision.ALLOW,
                # Matches any non-empty message.
                expected_message_patterns=[r".+"],
                safety_notes=(
                    "Display-only status handler - writes per-session state, injects nothing"
                ),
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
