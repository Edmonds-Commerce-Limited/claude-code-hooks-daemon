"""BranchRejectAgentBinderHandler - bind a reviewer dispatch to the agent it started.

Plan 00620 Task 2.2. ``branch_reject_dispatch_gate`` records a review nonce's dispatch
at PreToolUse with the session and ``tool_use_id`` but no agent id, because only the
tool result knows which agent Claude Code started. This handler fills that agent id
from ``tool_response.agentId`` on the PostToolUse of the same call, through
``core.branch_reject.bind_agent``, which binds only an unbound record whose session
and ``tool_use_id`` match.

A background dispatch's result arrives at launch; a foreground one arrives after the
agent has stopped, so the SubagentStop recorder may run first. The recorder never
writes the agent id itself; a verdict chains only once this binding exists.

A silent sensor: it injects nothing and never blocks. A failure leaves the record
unbound, which is the closed state: no verdict chains to an unbound dispatch.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants import (
    SUBAGENT_DISPATCH_TOOL_NAMES,
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
)
from claude_code_hooks_daemon.core import BlockingResult, Decision, ProjectContext
from claude_code_hooks_daemon.core.branch_reject import (
    RejectStore,
    bind_agent,
    main_checkout,
    prompt_nonce,
)
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

logger = logging.getLogger(__name__)

_PROMPT_FIELD: Final[str] = "prompt"
_AGENT_ID_FIELD: Final[str] = "agentId"


def _text(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    return value if isinstance(value, str) else ""


def _nonce(hook_input: dict[str, Any]) -> str | None:
    tool_input = hook_input.get(HookInputField.TOOL_INPUT)
    if not isinstance(tool_input, dict):
        return None
    return prompt_nonce(_text(tool_input, _PROMPT_FIELD))


class BranchRejectAgentBinderHandler(PostToolUseHandlerBase):
    """Fill a review dispatch record's agent id from the Agent call's result."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.BRANCH_REJECT_AGENT_BINDER,
            priority=Priority.BRANCH_REJECT_AGENT_BINDER,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.NON_TERMINAL],
        )
        # The registry injects the project's own ``branches`` config here.
        self._branches: BranchesConfig = BranchesConfig()

    @staticmethod
    def _project_root() -> Path:
        return ProjectContext.project_root()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """An Agent/Task result with a ``tool_use_id`` whose prompt is a review prompt.

        Store-free, so a damaged store never touches an unrelated result.
        """
        if hook_input.get(HookInputField.TOOL_NAME) not in SUBAGENT_DISPATCH_TOOL_NAMES:
            return False
        if not _text(hook_input, HookInputField.TOOL_USE_ID):
            return False
        return _nonce(hook_input) is not None

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Bind the agent id when the record is unbound and the call matches; always allow."""
        nonce = _nonce(hook_input)
        raw = hook_input.get(HookInputField.TOOL_RESPONSE)
        agent_id = _text(raw, _AGENT_ID_FIELD) if isinstance(raw, dict) else ""
        if nonce is None or not agent_id:
            return BlockingResult(decision=Decision.ALLOW)
        try:
            store = RejectStore(
                main_checkout(self._project_root()) / self._branches.reject.state_dir
            )
            bind_agent(
                store,
                nonce,
                session_id=_text(hook_input, HookInputField.SESSION_ID),
                tool_use_id=_text(hook_input, HookInputField.TOOL_USE_ID),
                agent_id=agent_id,
            )
        except (OSError, RuntimeError) as exc:
            log_and_continue(
                logger,
                exc,
                reason="an unbound review dispatch chains no verdict, which is the closed state; the tool result itself is untouched",
                level=logging.WARNING,
            )
        return BlockingResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        """Silent sensor: nothing an agent acts on."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """One case: a reviewer dispatch's result is recorded silently."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="branch-reject agent binder - binds a reviewer dispatch silently",
                command="Dispatch the branch-reject reviewer with a request's prompt",
                description=(
                    "The result is allowed with no message. The binding is asserted by "
                    "tests/unit/handlers/post_tool_use/test_branch_reject_agent_binder.py."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Rewrites one dispatch record under the branch-reject state dir.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="PostToolUse event for an Agent call",
            )
        ]
