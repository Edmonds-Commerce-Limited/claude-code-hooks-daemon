"""HumanApprovalCheckHandler - a coordinator seat's destructive act needs a human (Plan 00634).

A session holding a teamchat seat as coordinator may push, delete a branch,
ref or worktree, make a path world-writable, or merge into main only when the
command cites a questions-room line a declared human of the team sent::

    git push origin feature  # human-approval team=<team> id=<$event-id>

The cite is a trailing shell comment on the LAST line, so the shell ignores
it and the command runs unchanged once approved. A peer's line never counts.

Arming (``utils.human_approval.is_armed``): never for a session with no team
seat, never for a sub-agent. With ``coordinator_seats_only`` (Q5, proposed,
owner ruling pending) only a coordinator seat, or one whose role cannot be
read, is armed. Anything that fails BEFORE arming is silent: a seatless
session must see no change. Anything that fails AFTER arming is the mode's
refusal: ``block`` denies, ``advise`` allows with the refusal as context.

The detectors are the sibling handlers' public module functions. The handler
classes themselves are deliberately not imported: discovery registers every
handler class found in a module's namespace, so importing one would register
it twice.

The shipped verifier (``DEFAULT_VERIFIER``) refuses every cite until the
teamchat questions-room ``verify`` contract is confirmed (fedora-desktop issue
369), so under ``block`` every armed act is denied until then.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Protocol

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
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.handlers.pre_tool_use.dangerous_permissions import (
    sets_world_writable,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import names_a_deletion
from claude_code_hooks_daemon.handlers.pre_tool_use.merge_to_main_approval import (
    is_pr_merge,
    merge_lands_on_main,
    merge_target,
)
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.git_commit_parsing import git_invocations
from claude_code_hooks_daemon.utils.human_approval import (
    DEFAULT_VERIFIER,
    ActClass,
    ApprovalCite,
    ApprovalRecords,
    Verifier,
    check_approval,
    is_armed,
    parse_cite,
)
from claude_code_hooks_daemon.utils.teamchat_seat import (
    SeatContext,
    SeatContextResolver,
    SessionSignals,
)

if TYPE_CHECKING:
    from claude_code_hooks_daemon.config.models import TeamSeatConfig

logger = logging.getLogger(__name__)

MODE_OFF: Final[str] = "off"
MODE_ADVISE: Final[str] = "advise"
MODE_BLOCK: Final[str] = "block"
_MODES: Final[frozenset[str]] = frozenset({MODE_OFF, MODE_ADVISE, MODE_BLOCK})

_PUSH: Final[str] = "push"
_CITE_TEAM: Final[str] = "team"
_CITE_ID: Final[str] = "id"

#: ``# human-approval <fields>`` closing the last line, after whitespace.
_CITE_COMMENT: Final[re.Pattern[str]] = re.compile(
    r"(?:^|\s)#\s*human-approval((?:[ \t]+\S+)+)[ \t]*$"
)

#: How each act is named in a refusal. Fixed text: nothing from the command.
_ACT_NAMES: Final[Mapping[ActClass, str]] = {
    ActClass.PUSH: "push",
    ActClass.DELETE: "branch, ref or worktree delete",
    ActClass.PERMISSION: "world-writable chmod",
    ActClass.MERGE_MAIN: "merge into main",
}

_HANDLER_ERROR: Final[str] = (
    "the human-approval check could not judge this command, so it is treated as unapproved"
)

#: Every refusal shares this route; the reason line in front of it varies.
_ROUTE: Final[str] = (
    "Ask in the team's questions room, then append the human's line as a trailing "
    "comment on the command's last line: `# human-approval team=<team> id=<$event-id>`."
)

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.HUMAN_APPROVAL_MISSING,
    blocked=(
        "a coordinator team seat's push, delete, world-writable chmod or merge into main "
        "with no cited questions-room line a declared human sent"
    ),
    why=(
        "A coordinator acts for the team; these acts are the ones a human of the team "
        "must approve, and a peer agent's say-so is not a human's"
    ),
    fix=_ROUTE,
    verbose=(
        "WHY BLOCKED:\n"
        "This session holds a teamchat seat as coordinator (or its role cannot be\n"
        "read), and the command pushes, deletes a branch, ref or worktree, makes a\n"
        "path world-writable, or merges into main. Those need a human's approval.\n\n"
        "DO INSTEAD:\n"
        "  1. Ask in the team's questions room.\n"
        "  2. Append the human's line as a trailing comment on the command's last\n"
        "     line: `# human-approval team=<team> id=<$event-id>`.\n"
        "A peer agent's line never counts, and a sub-agent cannot carry one."
    ),
)


class _SeatResolver(Protocol):
    def resolve(self, signals: SessionSignals) -> SeatContext: ...


def classify_acts(command: str, cwd: Path) -> frozenset[ActClass]:
    """The act classes ``command`` runs. Text it only prints names none.

    An unreadable current branch with a merge named counts as a merge into
    main (fail closed); ``gh pr merge`` always does, because it lands on the
    pull request's base on GitHub whatever the local checkout.
    """
    acts: set[ActClass] = set()
    if any(run.subcommand == _PUSH for run in git_invocations(command)):
        acts.add(ActClass.PUSH)
    if names_a_deletion(command):
        acts.add(ActClass.DELETE)
    if sets_world_writable(command):
        acts.add(ActClass.PERMISSION)
    if is_pr_merge(command):
        acts.add(ActClass.MERGE_MAIN)
    else:
        target = merge_target(command)
        if target is not None and merge_lands_on_main(cwd, target) is not False:
            acts.add(ActClass.MERGE_MAIN)
    return frozenset(acts)


def cite_from_command(command: str) -> ApprovalCite | None:
    """The cite a trailing ``# human-approval team=<T> id=<$id>`` comment carries.

    Only on the last line, with exactly one ``team`` and one ``id`` field and
    nothing else; anything else is no cite.
    """
    lines = command.rstrip().splitlines()
    if not lines:
        return None
    found = _CITE_COMMENT.search(lines[-1])
    if found is None:
        return None
    fields: dict[str, str] = {}
    for token in found.group(1).split():
        key, sep, value = token.partition("=")
        if not sep or key not in (_CITE_TEAM, _CITE_ID) or key in fields:
            return None
        fields[key] = value
    if set(fields) != {_CITE_TEAM, _CITE_ID}:
        return None
    return parse_cite(fields[_CITE_TEAM], fields[_CITE_ID])


#: Verified approvals, in daemon memory only, shared by every instance.
_RECORDS: Final[ApprovalRecords] = ApprovalRecords()


class HumanApprovalCheckHandler(PreToolUseHandlerBase):
    """Deny a coordinator seat's destructive act that cites no human approval."""

    _mode: str | None = MODE_ADVISE
    _coordinator_seats_only: bool | None = True

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.HUMAN_APPROVAL_CHECK,
            priority=Priority.HUMAN_APPROVAL_CHECK,
            terminal=True,
            tags=[HandlerTag.WORKFLOW, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        # Injected by the registry from the `team_seat:` block.
        self._team_seat: TeamSeatConfig | None = None
        self._resolver: _SeatResolver | None = None
        self._verifier: Verifier = DEFAULT_VERIFIER
        self._records: ApprovalRecords = _RECORDS

    @staticmethod
    def validate_options(options: Mapping[str, Any]) -> dict[str, str]:
        """Refuse a malformed option; the handler then runs on its default for it."""
        problems: dict[str, str] = {}
        if "mode" in options and options["mode"] not in _MODES:
            problems["mode"] = f"mode must be one of {', '.join(sorted(_MODES))}"
        if "coordinator_seats_only" in options and not isinstance(
            options["coordinator_seats_only"], bool
        ):
            problems["coordinator_seats_only"] = "coordinator_seats_only must be true or false"
        return problems

    def is_dormant(self) -> bool:
        """Whether config leaves this handler unable to fire."""
        return self._mode == MODE_OFF

    def _seat_resolver(self) -> _SeatResolver:
        if self._resolver is None:
            from claude_code_hooks_daemon.config.models import TeamSeatConfig

            config = self._team_seat if self._team_seat is not None else TeamSeatConfig()
            self._resolver = SeatContextResolver.from_config(config)
        return self._resolver

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """An armed seat running a push, delete, world-writable chmod or merge into main.

        Cheapest first, and the seat probe last: a session with no teamchat
        runtime, or a command naming no act, never probes. Any failure here
        is silent, because nothing is armed yet.
        """
        if self.is_dormant() or hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return False
        try:
            signals = SessionSignals.from_hook_input(hook_input)
            if not signals.runtime:
                return False
            if not classify_acts(get_bash_command(hook_input) or "", self._cwd(hook_input)):
                return False
            context = self._seat_resolver().resolve(signals)
            return is_armed(
                hook_input,
                context,
                coordinator_seats_only=self._coordinator_seats_only is not False,
            )
        except Exception as exc:
            log_and_continue(
                logger,
                exc,
                reason="a failure before arming leaves the check silent; a seatless session must see no change",
            )
            return False

    @staticmethod
    def _cwd(hook_input: Mapping[str, Any]) -> Path:
        return Path(str(hook_input.get(HookInputField.CWD) or "."))

    def get_rules(self) -> list[Rule]:
        """The rule behind the deny."""
        return [_RULE]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Pass a human-approved act; otherwise the mode's refusal. Never raises."""
        try:
            return self._judge(hook_input)
        except Exception as exc:
            log_and_continue(
                logger,
                exc,
                reason="a failure after arming is the mode's refusal; the exception text is never shown",
            )
            return self._refuse(f"Human approval check: {_HANDLER_ERROR}. {_ROUTE}")

    def _judge(self, hook_input: dict[str, Any]) -> GatingResult:
        command = get_bash_command(hook_input) or ""
        acts = classify_acts(command, self._cwd(hook_input))
        if not acts:
            return GatingResult(decision=Decision.ALLOW)
        signals = SessionSignals.from_hook_input(hook_input)
        verdict = check_approval(
            hook_input,
            self._seat_resolver().resolve(signals),
            signals,
            acts=acts,
            cite=cite_from_command(command),
            verifier=self._verifier,
            records=self._records,
        )
        if verdict.passed:
            return GatingResult(decision=Decision.ALLOW)
        named = ", ".join(_ACT_NAMES[act] for act in sorted(acts))
        return self._refuse(f"Human approval missing for: {named}. {verdict.reason}. {_ROUTE}")

    def _refuse(self, text: str) -> GatingResult:
        if self._mode == MODE_BLOCK:
            return GatingResult(decision=Decision.DENY, reason=text).under_rule(_RULE)
        return GatingResult(decision=Decision.ALLOW, context=[text])

    def get_claude_md(self) -> str | None:
        """Resident guidance: how a coordinator seat cites a human's approval."""
        return (
            "## human_approval_check — a coordinator seat cites a human's approval\n\n"
            "In a session holding a teamchat seat as coordinator, a `git push`, a branch, "
            "ref or worktree delete, a world-writable `chmod` or a merge into main needs "
            "a questions-room line a declared human of the team sent. Ask there, then "
            "append the line as a trailing comment on the command's LAST line: "
            "`git push origin x  # human-approval team=<team> id=<$event-id>`. A peer's "
            "line never counts and a sub-agent cannot carry an approval. `mode: advise` "
            "only reports; `mode: block` denies. Until the teamchat `verify` contract is "
            "confirmed (fedora-desktop issue 369) no cite can pass, so `block` denies "
            "every such act. A session with no team seat is never affected."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Harness-undrivable: arming needs a live teamchat seat."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        unseated = (
            "Arming needs a live teamchat runtime and a coordinator seat; the harness "
            "session holds no team seat, so the check stays silent there."
        )
        return [
            AcceptanceTest(
                title="human approval check - an uncited push from a coordinator seat is refused",
                command="git push origin feature",
                description=(
                    "Under mode: block a coordinator seat's push with no cite is denied. "
                    "Unit tests in tests/unit/handlers/pre_tool_use/"
                    "test_human_approval_check.py cover the matrix."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"R-HUMAN-APPROVAL-MISSING", r"human-approval"],
                safety_notes="Never runs the push: the command is denied before it starts.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=unseated,
            ),
            AcceptanceTest(
                title="human approval check - a command naming no act is untouched",
                command="git status",
                description="A command naming no act, in any session, passes with no advisory.",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Read-only command.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=unseated,
            ),
        ]
