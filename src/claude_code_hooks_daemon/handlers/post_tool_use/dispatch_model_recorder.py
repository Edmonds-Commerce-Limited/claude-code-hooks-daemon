"""DispatchModelRecorderHandler - join the model a dispatch ran on to its tier row (Plan 00472 T1).

``agent_dispatch_recorder`` writes each dispatch's PreToolUse row: how its model
was chosen and the family that predicts. Only PostToolUse knows what Claude
Code actually started: ``tool_response.resolvedModel``, on both ``completed``
and ``async_launched`` responses, and ``modelsUsed`` when the model was swapped
mid-run. This handler merges them onto the row by ``tool_use_id``, so
``hooks-daemon tiers`` can set the prediction against the outcome. A response
with no PreToolUse row is kept and marked unjoined rather than dropped.

A silent sensor: it injects nothing and never blocks.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import (
    SUBAGENT_DISPATCH_TOOL_NAMES,
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
)
from claude_code_hooks_daemon.core import BlockingResult, Decision, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.spend_ledger import merge_dispatch_row

logger = logging.getLogger(__name__)


def _text(response: dict[str, Any], key: str) -> str:
    value = response.get(key)
    return value if isinstance(value, str) else ""


class DispatchModelRecorderHandler(PostToolUseHandlerBase):
    """Merge ``resolvedModel``, ``modelsUsed`` and ``agentId`` onto the dispatch's tier row."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.DISPATCH_MODEL_RECORDER,
            priority=Priority.DISPATCH_MODEL_RECORDER,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.NON_TERMINAL],
        )

    @staticmethod
    def _untracked_dir() -> Path:
        return ProjectContext.daemon_untracked_dir()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """An Agent/Task result that carries its ``tool_use_id``."""
        if hook_input.get(HookInputField.TOOL_NAME) not in SUBAGENT_DISPATCH_TOOL_NAMES:
            return False
        tool_use_id = hook_input.get(HookInputField.TOOL_USE_ID)
        return isinstance(tool_use_id, str) and bool(tool_use_id)

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Merge the resolved model onto the row; always allow."""
        raw = hook_input.get(HookInputField.TOOL_RESPONSE)
        response: dict[str, Any] = raw if isinstance(raw, dict) else {}
        models_used = response.get("modelsUsed")
        try:
            merge_dispatch_row(
                self._untracked_dir(),
                str(hook_input.get(HookInputField.SESSION_ID) or ""),
                str(hook_input[HookInputField.TOOL_USE_ID]),
                {
                    "resolved_model": _text(response, "resolvedModel"),
                    "models_used": (
                        [model for model in models_used if isinstance(model, str)]
                        if isinstance(models_used, list)
                        else []
                    ),
                    "agent_id": _text(response, "agentId"),
                    "status": _text(response, "status"),
                },
            )
        except (OSError, RuntimeError) as exc:
            log_and_continue(
                logger,
                exc,
                reason="an unrecorded resolved model leaves the dispatch's tier row with its prediction only; the tool result itself is untouched",
                level=logging.WARNING,
            )
        return BlockingResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        """Silent sensor: nothing an agent acts on."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """One case: a dispatch's result is recorded silently."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="dispatch model recorder - records the resolved model silently",
                command="Dispatch an Agent and let it return",
                description=(
                    "The result is allowed with no message. The merged row is asserted by "
                    "tests/unit/handlers/post_tool_use/test_dispatch_model_recorder.py."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Writes one small file under the daemon untracked dir.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="PostToolUse event for an Agent call",
            )
        ]
