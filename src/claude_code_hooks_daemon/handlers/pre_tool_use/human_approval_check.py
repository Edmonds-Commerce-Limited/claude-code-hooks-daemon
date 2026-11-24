"""HumanApprovalCheckHandler - a coordinator seat's destructive act needs a human (Plan 00634).

A session holding a teamchat seat as coordinator may push, delete a branch,
ref or worktree, make a path world-writable, or merge into main only when the
command cites a questions-room line a declared human of the team sent::

    git push origin feature  # human-approval team=<team> id=<$event-id>

The cite is a trailing shell comment on the LAST line, so the shell ignores
it and the command runs unchanged once approved. A peer's line never counts.

Arming (``utils.human_approval.is_armed``): never for a session with no team
seat. With ``coordinator_seats_only`` (Q5, proposed, owner ruling pending)
only a coordinator seat, or one whose role cannot be read, is armed on the
main thread. A sub-agent is judged as its seat (Plan 00634 P2: a sub-agent
can push for the coordinator), but only when a held seat is DECLARED
coordinator; nothing is assumed for a sub-agent. Anything that fails BEFORE arming is silent: a seatless
session must see no change. Anything that fails AFTER arming is the mode's
refusal: ``block`` denies, ``advise`` allows with the refusal as context.

The detectors are the sibling handlers' public module functions. The handler
classes themselves are deliberately not imported: discovery registers every
handler class found in a module's namespace, so importing one would register
it twice.

The verifier (``DEFAULT_VERIFIER``) runs ``teamchat verify <id> --room
questions`` per the fedora-desktop issue 369 contract as its peer relayed it,
unchecked against a live teamchat here; anything off that contract refuses.
The binding options (``require_question``, ``max_line_age_seconds``,
``single_use_cites``) are owner question O4 and default OFF. Advise mode is
annotation only: it allows every refusal.
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
from claude_code_hooks_daemon.utils.command_position import command_position_segments
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.git_commit_parsing import GitInvocation, git_invocations
from claude_code_hooks_daemon.utils.git_sync import default_branch
from claude_code_hooks_daemon.utils.human_approval import (
    DEFAULT_VERIFIER,
    ActClass,
    ApprovalCite,
    ApprovalRecords,
    BindingPolicy,
    CiteLedger,
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

#: Porcelain push and the plumbing that pushes the same way.
_PUSH_SUBCOMMANDS: Final[frozenset[str]] = frozenset({"push", "send-pack", "http-push"})
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

#: The single-use ledger, under the daemon's untracked state directory.
LEDGER_FILE_NAME: Final[str] = "human-approval-used-cites.json"
#: Largest ``max_line_age_seconds`` accepted (30 days).
MAX_LINE_AGE_LIMIT_SECONDS: Final[int] = 30 * 86400

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
        "A peer agent's line never counts. A sub-agent of a coordinator seat\n"
        "is judged as the seat and cites the same way."
    ),
)


class _SeatResolver(Protocol):
    def resolve(self, signals: SessionSignals) -> SeatContext: ...


#: Subcommands that move the CHECKED-OUT branch onto other history.
_BRANCH_MOVERS: Final[frozenset[str]] = frozenset({"merge", "reset", "rebase", "cherry-pick", "am"})
#: Flags that end or abandon an operation in progress rather than move a branch.
_NON_MOVING_FLAGS: Final[frozenset[str]] = frozenset(
    {"--abort", "--quit", "--skip", "--show-current-patch", "--edit-todo"}
)
_SWITCHERS: Final[frozenset[str]] = frozenset({"checkout", "switch"})
_NEW_BRANCH_FLAGS: Final[frozenset[str]] = frozenset(
    {"-b", "-B", "-c", "-C", "--orphan", "--create"}
)
_DETACH_FLAGS: Final[frozenset[str]] = frozenset({"--detach", "-d"})
_BRANCH_FORCE_FLAGS: Final[frozenset[str]] = frozenset({"-f", "--force", "-m", "-M", "-C"})
_PULL_REFSPEC_POSITIONALS: Final[int] = 2
_HEADS: Final[str] = "refs/heads/"
#: Names taken as the default branch when it cannot be read (fail closed).
_FALLBACK_DEFAULTS: Final[frozenset[str]] = frozenset({"main", "master"})
#: `gh api` merging on GitHub: a pull request merge, or the repository merges endpoint.
_GH_API_MERGE: Final[re.Pattern[str]] = re.compile(
    r"\bgh\b.*\bapi\b.*(?:\bpulls/[^/\s]+/merge\b|\bmerges\b)"
)
#: The checked-out branch at the start of the command, read lazily.
_START: Final[str] = "\0start"


def _positionals(arguments: tuple[str, ...]) -> list[str]:
    return [word for word in arguments if not word.startswith("-")]


def _is_unreadable(word: str) -> bool:
    return word == "-" or "$" in word or "`" in word


def _switched_to(subcommand: str, arguments: tuple[str, ...]) -> str | None:
    """The branch a checkout/switch leaves checked out; None when unreadable.

    ``_START`` when it switches no branch (``git checkout -- path``).
    """
    if subcommand == "checkout" and "--" in arguments:
        return _START
    words = list(arguments)
    for index, word in enumerate(words):
        if word in _NEW_BRANCH_FLAGS:
            new = words[index + 1] if index + 1 < len(words) else ""
            return None if not new or _is_unreadable(new) else new
        if word in _DETACH_FLAGS:
            return None
    positionals = [word for word in words if not word.startswith("-") or word == "-"]
    if not positionals:
        return _START
    return None if _is_unreadable(positionals[0]) else positionals[0]


def _names_default_ref(ref: str, defaults: frozenset[str]) -> bool:
    ref = ref.removeprefix("+")
    return ref in defaults or (ref.startswith(_HEADS) and ref[len(_HEADS) :] in defaults)


def _moves_named_main_ref(
    subcommand: str, arguments: tuple[str, ...], defaults: frozenset[str]
) -> bool:
    """A command that rewrites the default branch's ref by NAME, from any checkout."""
    positionals = _positionals(arguments)
    if subcommand == "fetch":
        return any(
            _names_default_ref(spec.split(":", 1)[1], defaults)
            for spec in positionals
            if ":" in spec
        )
    if subcommand == "update-ref":
        if "-d" in arguments:
            return False
        if "--stdin" in arguments:
            return True
        return bool(positionals) and _names_default_ref(positionals[0], defaults)
    if subcommand == "branch" and any(flag in arguments for flag in _BRANCH_FORCE_FLAGS):
        return any(word in defaults for word in positionals)
    return False


def _moves_checked_out_branch(subcommand: str, arguments: tuple[str, ...]) -> bool:
    if subcommand == "pull":
        return len(_positionals(arguments)) >= _PULL_REFSPEC_POSITIONALS
    if subcommand not in _BRANCH_MOVERS:
        return False
    # `--continue` still lands the operation on the branch, so it counts.
    return not any(word in _NON_MOVING_FLAGS for word in arguments)


def moves_main(command: str, cwd: Path) -> bool:
    """Whether ``command`` moves the default branch onto other history.

    Two kinds. A command that names the default branch's ref (``fetch .
    x:main``, ``update-ref refs/heads/main``, ``branch -f main``) moves it
    from any checkout. A merge, reset, rebase, cherry-pick, ``am`` or
    refspec pull moves the CHECKED-OUT branch, so it is judged against the
    branch the command has switched to by then: the default branch counts,
    an unreadable switch (``checkout -``, ``$B``, ``--detach``) counts (fail
    closed), and with no switch the starting checkout is read via
    :func:`merge_lands_on_main`, whose unreadable answer also counts.
    """
    read = default_branch(cwd)
    defaults = frozenset({read}) if read else _FALLBACK_DEFAULTS
    branch: str | None = _START
    for run in git_invocations(command):
        if run.subcommand in _SWITCHERS:
            switched = _switched_to(run.subcommand, run.arguments)
            if switched != _START:
                branch = switched
            continue
        if _moves_named_main_ref(run.subcommand, run.arguments, defaults):
            return True
        if not _moves_checked_out_branch(run.subcommand, run.arguments):
            continue
        if branch is None or branch in defaults:
            return True
        if branch == _START:
            target = next(iter(_positionals(run.arguments)), "")
            if target not in defaults and merge_lands_on_main(cwd, target) is not False:
                return True
    return False


def classify_acts(command: str, cwd: Path) -> frozenset[ActClass]:
    """The act classes ``command`` runs. Text it only prints names none.

    A merge into main is ``gh pr merge`` (always: it lands on the pull
    request's base whatever the local checkout), a ``gh api`` merge, or
    anything :func:`moves_main` reports. A merge this reading names but
    cannot place in any git run still counts unless the checkout is a
    definite no (fail closed).
    """
    runs = git_invocations(command)
    acts: set[ActClass] = set()
    if any(run.subcommand in _PUSH_SUBCOMMANDS for run in runs):
        acts.add(ActClass.PUSH)
    if names_a_deletion(command):
        acts.add(ActClass.DELETE)
    if sets_world_writable(command):
        acts.add(ActClass.PERMISSION)
    if _merges_into_main(command, cwd, runs):
        acts.add(ActClass.MERGE_MAIN)
    return frozenset(acts)


def _merges_into_main(command: str, cwd: Path, runs: list[GitInvocation]) -> bool:
    if is_pr_merge(command):
        return True
    if any(_GH_API_MERGE.search(segment) for segment in command_position_segments(command)):
        return True
    if moves_main(command, cwd):
        return True
    target = merge_target(command)
    if target is None or any(run.subcommand in ("merge", "pull") for run in runs):
        return False
    return merge_lands_on_main(cwd, target) is not False


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


def _ledger_path() -> Path:
    from claude_code_hooks_daemon.core.project_context import ProjectContext

    return ProjectContext.daemon_untracked_dir() / LEDGER_FILE_NAME


def _is_age(value: object) -> bool:
    return type(value) is int and 0 < value <= MAX_LINE_AGE_LIMIT_SECONDS


class HumanApprovalCheckHandler(PreToolUseHandlerBase):
    """Deny a coordinator seat's destructive act that cites no human approval."""

    _mode: str | None = MODE_ADVISE
    _coordinator_seats_only: bool | None = True
    _require_question: bool | None = False
    _max_line_age_seconds: int | None = None
    _single_use_cites: bool | None = False

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
        self._ledger: CiteLedger = CiteLedger(_ledger_path)

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
        for key in ("require_question", "single_use_cites"):
            if key in options and not isinstance(options[key], bool):
                problems[key] = f"{key} must be true or false"
        age = options.get("max_line_age_seconds")
        if age is not None and not _is_age(age):
            problems["max_line_age_seconds"] = (
                f"max_line_age_seconds must be null or an integer 1 to {MAX_LINE_AGE_LIMIT_SECONDS}"
            )
        return problems

    def _policy(self) -> BindingPolicy:
        age = self._max_line_age_seconds
        return BindingPolicy(
            require_question=self._require_question is True,
            max_line_age_seconds=age if _is_age(age) else None,
            single_use=self._single_use_cites is True,
        )

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

        A session with no teamchat runtime never probes. The seat is resolved
        (TTL-cached) BEFORE the command is classified, so the two failure
        sides stay apart: a failure before arming is silent, because a
        seatless session must see no change; a failure while classifying for
        an armed seat counts as the act, so the mode's refusal judges it.
        """
        if self.is_dormant() or hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return False
        try:
            signals = SessionSignals.from_hook_input(hook_input)
            if not signals.runtime:
                return False
            armed = is_armed(
                hook_input,
                self._seat_resolver().resolve(signals),
                coordinator_seats_only=self._coordinator_seats_only is not False,
                include_subagents=True,
            )
        except Exception as exc:
            log_and_continue(
                logger,
                exc,
                reason="a failure before arming leaves the check silent; a seatless session must see no change",
            )
            return False
        if not armed:
            return False
        try:
            return bool(classify_acts(get_bash_command(hook_input) or "", self._cwd(hook_input)))
        except Exception as exc:
            log_and_continue(
                logger,
                exc,
                reason="a failure classifying an armed seat's command counts as the act (fail closed)",
            )
            return True

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
            policy=self._policy(),
            ledger=self._ledger,
            include_subagents=True,
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
            "line never counts. A sub-agent of a declared coordinator seat is judged as "
            "the seat and cites the same way. The cite is checked with `teamchat verify "
            "<id> --room questions`. `mode: advise` only reports (it allows every "
            "refusal); `mode: block` denies. A session with no team seat is never affected."
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
