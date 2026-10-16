"""AgentDispatchRecorderHandler - remember which definition type a NAMED agent was.

A sub-agent's tool events carry ``agent_type``, but for an agent dispatched
with ``name`` the value is that name, not its ``subagent_type`` (Plan 00518
Task 0.1). A guard that keys on the definition type -- the full-QA blocker's
``exempt_agent_types`` -- needs the translation, and the only moment the pair is
visible is the dispatch call itself. This handler records it, silently, and
never decides anything.

It also writes every dispatch's tier row, named or not (Plan 00472 T1): the
classifier's source, predicted family and role, keyed by ``tool_use_id`` in the
shared spend ledger, where ``dispatch_model_recorder`` later joins the model
that actually ran.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import (
    SUBAGENT_DISPATCH_TOOL_NAMES,
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
)
from claude_code_hooks_daemon.core import Decision, GatingResult, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.utils.agent_dispatch_registry import record_dispatch
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.dispatch_tier import (
    classify,
    dispatch_facts,
    effective_definition_model,
    spawner_model,
    tier_reason,
)
from claude_code_hooks_daemon.utils.spend_ledger import append_event, write_dispatch_row

logger = logging.getLogger(__name__)

_NAME_FIELD = "name"
_SUBAGENT_TYPE_FIELD = "subagent_type"
_PROMPT_FIELD = "prompt"
_DESCRIPTION_FIELD = "description"
_MAIN_SPAWNER = "main"


def _text(tool_input: dict[str, Any], field: str) -> str:
    value = tool_input.get(field)
    return value if isinstance(value, str) else ""


#: A whole line ``budget: 400k`` in the dispatch prompt (Plan 00471 Q4). Only a
#: NAMED dispatch reaches this handler, so an unnamed one's line is ignored.
_BUDGET_LINE = re.compile(r"(?im)^\s*budget:\s*(\d{1,4})\s*k\s*$")
_TOKENS_PER_K = 1000


class AgentDispatchRecorderHandler(PreToolUseHandlerBase):
    """Record ``name -> subagent_type`` for a NAMED dispatch, and every dispatch's tier row.

    Always allows. A record that cannot be written is logged and the dispatch
    proceeds: the consumer fails closed on a missing record for a name it
    cannot otherwise place, so a lost record costs an exemption, never safety.
    A lost tier row costs one line of the tier report.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.AGENT_DISPATCH_RECORDER,
            priority=Priority.AGENT_DISPATCH_RECORDER,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.NON_TERMINAL],
        )

    @staticmethod
    def _untracked_dir() -> Path:
        return ProjectContext.daemon_untracked_dir()

    @staticmethod
    def _project_root() -> Path:
        return ProjectContext.project_root()

    @staticmethod
    def _session_id(hook_input: dict[str, Any]) -> str:
        session_id = hook_input.get(HookInputField.SESSION_ID)
        return session_id if isinstance(session_id, str) else ""

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True for any dispatch in a session that has an id."""
        if hook_input.get(HookInputField.TOOL_NAME) not in SUBAGENT_DISPATCH_TOOL_NAMES:
            return False
        if not self._session_id(hook_input):
            return False
        return isinstance(hook_input.get(HookInputField.TOOL_INPUT), dict)

    @staticmethod
    def budget_override(prompt: object) -> int | None:
        """The tokens a ``budget: <N>k`` line in the prompt asks for (Plan 00471 Q4)."""
        if not isinstance(prompt, str):
            return None
        match = _BUDGET_LINE.search(prompt)
        return int(match.group(1)) * _TOKENS_PER_K if match else None

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Write the name record (named only), the tier row and any budget event; always allow."""
        tool_input = hook_input[HookInputField.TOOL_INPUT]
        if _text(tool_input, _NAME_FIELD):
            self._record_name(hook_input, tool_input)
        self._record_tier(hook_input, tool_input)
        return GatingResult(decision=Decision.ALLOW)

    def _record_name(self, hook_input: dict[str, Any], tool_input: dict[str, Any]) -> None:
        subagent_type = tool_input.get(_SUBAGENT_TYPE_FIELD)
        budget = self.budget_override(tool_input.get(_PROMPT_FIELD))
        try:
            untracked = self._untracked_dir()
            record_dispatch(
                untracked,
                self._session_id(hook_input),
                tool_input[_NAME_FIELD],
                subagent_type if isinstance(subagent_type, str) else None,
                budget_tokens=budget,
            )
            if budget is not None:
                append_event(
                    untracked,
                    self._session_id(hook_input),
                    {
                        "kind": "budget-override",
                        "name": tool_input[_NAME_FIELD],
                        "requested_tokens": budget,
                    },
                )
        except (OSError, RuntimeError) as exc:
            log_and_continue(
                logger,
                exc,
                reason="a dispatch record that cannot be written costs only the exemption of that named agent; the dispatch itself must never be blocked",
                level=logging.WARNING,
            )

    def _record_tier(self, hook_input: dict[str, Any], tool_input: dict[str, Any]) -> None:
        """The dispatch's tier row (Plan 00472 T1), keyed by its ``tool_use_id``."""
        tool_use_id = hook_input.get(HookInputField.TOOL_USE_ID)
        if not isinstance(tool_use_id, str) or not tool_use_id:
            return
        try:
            untracked = self._untracked_dir()
            main_model = spawner_model(hook_input, untracked)
            facts = dispatch_facts(
                tool_input, project_root=self._project_root(), main_model=main_model
            )
            name = _text(tool_input, _NAME_FIELD)
            tier = classify(facts, name=name, description=_text(tool_input, _DESCRIPTION_FIELD))
            agent_id = hook_input.get(HookInputField.AGENT_ID)
            write_dispatch_row(
                untracked,
                self._session_id(hook_input),
                tool_use_id,
                {
                    "spawner": (
                        agent_id if isinstance(agent_id, str) and agent_id else _MAIN_SPAWNER
                    ),
                    "spawner_model": main_model,
                    "subagent_type": facts.subagent_type,
                    "name": name,
                    "model_param": facts.model_param,
                    "definition_model": effective_definition_model(facts),
                    "source": tier.source.value,
                    "predicted_family": tier.predicted_family or "",
                    "role": tier.role.value,
                    "tier_reason": tier_reason(_text(tool_input, _PROMPT_FIELD)),
                },
            )
        except (OSError, RuntimeError) as exc:
            log_and_continue(
                logger,
                exc,
                reason="a tier row that cannot be classified or written costs one line of the tier report; the dispatch itself must never be blocked",
                level=logging.WARNING,
            )

    def get_claude_md(self) -> str | None:
        """Silent sensor: nothing an agent acts on, so no resident guidance."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """One probe: a named dispatch is allowed and says nothing."""
        from claude_code_hooks_daemon.constants.tools import ToolName
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        probe = ToolPayload(
            tool_name=ToolName.AGENT,
            tool_input={
                "name": "acceptance-probe",
                "subagent_type": "qa-runner",
                "description": "probe",
                "prompt": "do nothing",
            },
        )
        return [
            AcceptanceTest(
                title="a named agent dispatch is recorded silently",
                command=probe.as_instruction(),
                description=(
                    "The handler records name -> subagent_type and always allows. The record "
                    "itself is asserted by tests/unit/handlers/pre_tool_use/"
                    "test_agent_dispatch_recorder.py; the harness checks only the decision."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Writes one small file under the daemon untracked dir.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=True,
                tool_payload=probe,
            )
        ]
