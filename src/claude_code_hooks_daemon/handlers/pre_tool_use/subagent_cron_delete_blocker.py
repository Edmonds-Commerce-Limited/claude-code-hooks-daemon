"""SubagentCronDeleteBlockerHandler - a subagent deletes no session cron.

Plan 00423 Task 3.2, for issue #40. The reported incident is the whole
specification: a finished subagent re-woke on failsafe ticks and, on its last
wake, deleted the project's single failsafe recovery cron on its own initiative
to stop the nudges. The coordinator's session carried on live with no recovery
coverage, and nothing announced the loss — a deleted cron is silent, and the
next rate limit is where it is discovered.

**The rule is wider than "the failsafe cron", because the payload cannot be
narrower.** ``session_crons`` is delivered to ``Stop``
(``contracts/claude-code-hooks/Stop.json``), not to ``PreToolUse``, so at the
moment a ``CronDelete`` is judged this handler holds an opaque id and nothing
that maps it to a schedule or a prompt. A handler claiming to protect one named
cron would be guessing at which one it had. "A subagent deletes no cron" is the
rule this event can actually support, and it costs nothing real: a session cron
belongs to the coordinator's session, which is the session that created it.

**The scope key carries the role test, so this module never reads
``agent_id``.** ``scope=SUB`` means the chain admits the event only when
``agent_id`` is present and the event is not synthetic; reaching ``handle`` at
all therefore already establishes that a subagent made the call. Re-deriving it
here would be a second copy of a safety rule that has one home, and two copies
of a safety rule drift apart in exactly the direction nobody notices — the one
where the guard stops firing.

**DELETION only.** A subagent CREATING a cron is noisy rather than harmful, and
``persistent_cron_assertor``/``cron_stop_enforcer`` already own reconciliation.
``CronList`` is a read. Neither is this handler's business.
"""

from __future__ import annotations

from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter

#: Public so the test suite asserts against the real name rather than a second
#: copy of the string. Confirmed present in this project's own verdict log as a
#: real ``PreToolUse`` tool name, not inferred from the tool's existence.
CRON_DELETE_TOOL: Final[str] = ToolName.CRON_DELETE

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.SUBAGENT_CRON_DELETE,
    blocked="`CronDelete` called from inside a subagent",
    why="A session cron belongs to the coordinator's session, which is the session that loses coverage when it goes",
    fix="Report the cron id and your reasoning to the coordinator and let it decide",
    verbose=(
        "WHY BLOCKED:\n"
        "Session crons belong to the COORDINATOR's session — the session that\n"
        "created them, and the one left uncovered when they go. The failsafe\n"
        "recovery cron is the case that matters: deleting it strands a still-live\n"
        "coordinator with no recovery path, and the loss is SILENT until the next\n"
        "rate limit or API stall, when nothing resumes it.\n\n"
        "This is deliberately wider than 'the failsafe cron'. `session_crons` is\n"
        "delivered to `Stop`, not to `PreToolUse`, so at this moment the daemon\n"
        "holds an opaque cron id and cannot tell WHICH cron you are deleting. A\n"
        "narrower rule would be guessing at that, so the rule is the one this\n"
        "event can actually support.\n\n"
        "DO INSTEAD:\n"
        "  - Name the cron id, and why you believe it should go, in your report\n"
        "    to the coordinator. Deciding is its call, not yours.\n"
        "  - If failsafe ticks are waking you with nothing to do, say THAT — the\n"
        "    tick is the thing to fix, not the safety net.\n\n"
        "The coordinator's own `CronDelete` is unaffected: this rule applies only\n"
        "inside a subagent."
    ),
)


class SubagentCronDeleteBlockerHandler(PreToolUseHandlerBase):
    """Deny ``CronDelete`` inside a subagent; the coordinator is unaffected.

    Terminal: a deny here is the final word on this tool call, and no other
    handler has anything to add about it.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SUBAGENT_CRON_DELETE_BLOCKER,
            priority=Priority.SUBAGENT_CRON_DELETE_BLOCKER,
            terminal=True,
            # The whole role test. See the module docstring: the handler must
            # not re-derive main-vs-sub for itself.
            scope=HandlerScope.SUB,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING, HandlerTag.WORKFLOW],
        )

    def get_default_enabled(self) -> bool:
        """Opt-OUT handler — ON by default.

        A safety control a project must remember to switch on is one that is
        off in every project that has not had the incident yet. It is also
        silent by construction for any project that never runs subagents.
        Must stay consistent with the config template.
        """
        return True

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True for a ``CronDelete`` call and nothing else.

        The event is already known to be a subagent's — the chain's scope gate
        admitted it — so tool name is the only remaining question.
        """
        return hook_input.get(HookInputField.TOOL_NAME) == CRON_DELETE_TOOL

    def get_rules(self) -> list[Rule]:
        """The single Rule backing this handler's deny."""
        return [_RULE]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Refuse, naming the harm and the route back to the coordinator.

        Always VERBOSE, with no disclosure ladder. A ladder exists so a rule
        that fires repeatedly in one session goes terse after the first — but
        this one fires at most a handful of times in a subagent's whole life,
        and each fire is a different subagent that has read nothing. Going
        terse here would save nothing and cost the one explanation that stops
        the agent looking for another route.
        """
        return GatingResult.deny(RuleFormatter().verbose(_RULE))

    def get_acceptance_tests(self) -> list[Any]:
        """One case, declared as harness-undrivable rather than dressed up.

        The playbook harness marks every probe with ``SYNTHETIC_SOURCE_FIELD``
        (``daemon/playbook_harness.build_event``), and the scope gate refuses a
        synthetic event for any scope other than ``ALL`` — that exclusion is
        deliberate and is what keeps a scoped handler from reddening the whole
        acceptance suite. The consequence is that a probe asserting this DENY
        would observe an ALLOW for ever, and pass or fail for a reason that has
        nothing to do with the handler. Saying so is the honest option; the
        alternative is a probe that is green because it is vacuous, which is
        the failure shape this project keeps rediscovering.

        The behaviour is covered by unit tests over ``matches``/``handle`` and
        by ``tests/unit/core/test_chain_handler_scope.py`` over the admission
        half.
        """
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="subagent cron delete blocker - a subagent's CronDelete is denied",
                command="CronDelete a session cron from inside a subagent",
                description=(
                    "Inside a subagent, CronDelete is refused; the reason names the "
                    "coordinator as the route and the recovery coverage as the harm. "
                    "The coordinator's own CronDelete is untouched."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"coordinator", r"recovery"],
                safety_notes=(
                    "Denies only inside a subagent, and only CronDelete — CronCreate "
                    "and CronList are never matched."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=(
                    "The harness marks every probe synthetic, and a scoped handler "
                    "declines a synthetic event by construction — so this probe would "
                    "observe ALLOW no matter what the handler does. Fabricating a "
                    "subagent event is the thing the harness cannot do."
                ),
            ),
            AcceptanceTest(
                title="subagent cron delete blocker - a subagent's CronCreate is untouched",
                command="CronCreate a session cron from inside a subagent",
                description=(
                    "The near-miss. Only DELETION is destructive — a subagent creating "
                    "a cron is noisy at worst, and reconciliation is already owned by "
                    "persistent_cron_assertor and cron_stop_enforcer. CronList is a "
                    "read. Neither is matched."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Negative case: a handler that denied every Cron* tool would be "
                    "stopping a subagent from doing things that harm nothing, and the "
                    "first person to hit it would switch it off."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=(
                    "Same reason as the DENY sibling: the probe would be synthetic, and "
                    "a scoped handler declines a synthetic event before matches() runs. "
                    "This case would therefore ALLOW for the wrong reason — the scope "
                    "gate rather than the tool name — and prove nothing."
                ),
            ),
        ]

    def get_claude_md(self) -> str | None:
        """Resident guidance for the active-handler block.

        Resident rather than fire-time (criterion T4 in
        ``CLAUDE/HANDLER_DEVELOPMENT.md``): the standing rule a subagent needs
        is "escalate, do not delete", and it is worth knowing BEFORE the
        deletion is attempted — a subagent that learns it from a deny has
        already decided the cron should go.
        """
        return (
            "## subagent_cron_delete_blocker — a subagent deletes no session cron\n\n"
            "`CronDelete` is DENIED inside a subagent. Session crons belong to the "
            "coordinator's session; the failsafe recovery cron is the case that "
            "matters, because deleting it strands a still-live coordinator with no "
            "recovery path and the loss is silent until the next stall.\n\n"
            "**It is deliberately wider than 'the failsafe cron'.** `session_crons` "
            "reaches `Stop`, not `PreToolUse`, so at deletion time the daemon holds an "
            "opaque cron id and cannot tell which cron is meant. A narrower rule would "
            "be guessing.\n\n"
            "**If you are a subagent and a cron looks wrong**: name the id and your "
            "reasoning in your report to the coordinator. If failsafe ticks are waking "
            "you with nothing to do, the tick is what to fix — say so — not the safety "
            "net.\n\n"
            "`CronCreate` and `CronList` are never matched, and the coordinator's own "
            "`CronDelete` is unaffected."
        )
