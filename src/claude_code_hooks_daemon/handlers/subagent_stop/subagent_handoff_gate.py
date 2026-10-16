"""SubagentHandoffGateHandler - an over-budget subagent leaves a handoff before it stops (Plan 00471 L2).

The SubagentStop companion of ``subagent_context_budget``. Once an agent has hit
the hard band, that handler records it in the agent's state document along with
the handoff path it named; when the agent stops, this gate checks the handoff
exists (the named path, or the file the agent actually wrote under the handoff
globs) and blocks the stop until it does. That is what makes the hard band a
handoff rather than a kill.

It must never strand an agent either: after ``MAX_STOP_BLOCKS`` blocks it
allows, because by then the worktree state is the handoff. An agent that never
reached the hard band (hard mode is shipped off) always stops freely.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import BlockingResult, Decision, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import SubagentStopHandlerBase
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.daemon.synthetic_traffic import is_synthetic_event
from claude_code_hooks_daemon.handlers.pre_tool_use.subagent_context_budget import (
    STATE_HANDOFF_PATH,
    STATE_HANDOFF_WRITTEN,
    STATE_HARD_ENGAGED,
    STATE_KIND,
)
from claude_code_hooks_daemon.utils.spend_ledger import read_state, state_path, write_state

#: Stops blocked before the gate gives way; the worktree is then the handoff.
MAX_STOP_BLOCKS: Final[int] = 3

_STATE_STOP_BLOCKS: Final[str] = "stop_blocks"

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.SUBAGENT_HANDOFF_MISSING,
    blocked="a subagent stop over the hard context budget with no handoff file written",
    why="A coordinator can only continue the work from a handoff; without one the next agent starts blind",
    fix="Write the handoff file the message names, then stop",
    verbose=(
        "WHY BLOCKED:\n"
        "This subagent reached its hard context budget, so its work continues in a\n"
        "fresh agent. That agent starts from your handoff file, and there is none.\n\n"
        "DO INSTEAD:\n"
        "  1. Write the handoff (what is done, what is left, where the state is).\n"
        "  2. git add and git commit your work in progress.\n"
        "  3. Stop.\n\n"
        f"After {MAX_STOP_BLOCKS} blocked stops the gate gives way: your worktree is\n"
        "then the handoff."
    ),
)


class SubagentHandoffGateHandler(SubagentStopHandlerBase):
    """Block an over-hard-budget subagent's stop until its handoff file exists."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SUBAGENT_HANDOFF_GATE,
            priority=Priority.SUBAGENT_HANDOFF_GATE,
            terminal=False,
            scope=HandlerScope.SUB,
            shares_options_with="subagent_context_budget",
            tags=[HandlerTag.WORKFLOW, HandlerTag.BLOCKING],
        )
        self._untracked_override: Path | None = None

    def _untracked_dir(self) -> Path:
        return self._untracked_override or ProjectContext.daemon_untracked_dir()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A real subagent stop that names its agent."""
        if is_synthetic_event(hook_input):
            return False
        return bool(hook_input.get(HookInputField.AGENT_ID))

    def get_rules(self) -> list[Rule]:
        """The rule behind the blocked stop."""
        return [_RULE]

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """DENY the stop when the hard band engaged and no handoff exists, at most three times."""
        state_file = state_path(
            self._untracked_dir(),
            str(hook_input.get(HookInputField.SESSION_ID) or ""),
            STATE_KIND,
            str(hook_input.get(HookInputField.AGENT_ID) or ""),
        )
        state = read_state(state_file)
        if state.get(STATE_HARD_ENGAGED) is not True:
            return BlockingResult(decision=Decision.ALLOW)
        expected = state.get(STATE_HANDOFF_PATH)
        written = state.get(STATE_HANDOFF_WRITTEN)
        candidates = [
            Path(value) for value in (written, expected) if isinstance(value, str) and value
        ]
        if any(candidate.is_file() for candidate in candidates):
            return BlockingResult(decision=Decision.ALLOW)
        blocks = state.get(_STATE_STOP_BLOCKS)
        blocks = blocks if isinstance(blocks, int) and not isinstance(blocks, bool) else 0
        if blocks >= MAX_STOP_BLOCKS:
            return BlockingResult(decision=Decision.ALLOW)
        state[_STATE_STOP_BLOCKS] = blocks + 1
        write_state(state_file, state)
        target = expected if isinstance(expected, str) and expected else "the handoff path"
        return BlockingResult(
            decision=Decision.DENY,
            reason=(
                "HANDOFF MISSING: this subagent reached its hard context budget and is "
                f"stopping without a handoff. Write it to {target} (what is done, what is "
                "left, where the state is), commit your work in progress, then stop. "
                f"Block {blocks + 1} of {MAX_STOP_BLOCKS}; after that the stop is allowed and "
                "your worktree is the handoff."
            ),
        ).under_rule(_RULE)

    def get_claude_md(self) -> str | None:
        """Covered by ``subagent_context_budget``'s section, which names the handoff route."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """The block and its near miss, declared harness-undrivable: both need a real over-budget agent."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="subagent handoff gate - an over-budget stop needs a handoff",
                command="Stop a subagent that hit hard_tokens without writing its handoff",
                description=(
                    "The stop is blocked naming the handoff path, at most three times. Unit "
                    "tests in tests/unit/handlers/subagent_stop/test_subagent_handoff_gate.py "
                    "cover the matrix."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"HANDOFF MISSING"],
                safety_notes="Allows after three blocks, so no agent is ever stranded.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=(
                    "It needs a subagent whose real transcript is past hard_tokens, which "
                    "ships off; the harness fabricates neither the agent nor its transcript."
                ),
            ),
            AcceptanceTest(
                title="subagent handoff gate - an over-budget stop after its handoff is allowed",
                command=(
                    "Stop a subagent that hit hard_tokens after writing the handoff file "
                    "its deny message named"
                ),
                description=(
                    "The handoff exists on disk, so the stop proceeds with no block; the "
                    "coordinator continues from that file."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="The near miss of the deny case: only the handoff file differs.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=(
                    "It needs a subagent whose real transcript is past hard_tokens, which "
                    "ships off; the harness fabricates neither the agent nor its transcript."
                ),
            ),
        ]
