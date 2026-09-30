"""SubagentWorktreeWriteGuardHandler - a subagent writes only in its own worktree.

Ledger 00474 N264. Dispatching an agent to land ``worktree-n466-n253``, its
clean-tree check failed: three files in that worktree held 253 added lines, all
written in one second, by a sub-agent that was working in a SIBLING worktree on
the same guard. They were an unapproved change and, committed by the next
landing agent, would have reached ``main`` under the wrong branch's name.
Nothing in the daemon stopped a sub-agent writing outside the worktree it was
dispatched into.

**The rule**: a ``Write``/``Edit``/``NotebookEdit`` made by a sub-agent whose
working directory is inside a LINKED worktree of repository R is denied when
its target sits in a DIFFERENT checkout of R -- another linked worktree, or
R's main working tree.

**What it deliberately does not judge**:

* The main thread. The coordinator merges and edits across worktrees
  legitimately. The role test is the ``scope=SUB`` gate in the chain; this
  module never reads ``agent_id`` (a second copy of a safety rule is how it
  drifts apart).
* A sub-agent whose cwd is the main working tree -- it was given no worktree to
  stay inside.
* A target outside R altogether, or in another repository: ``project_containment``
  owns the repository boundary.

**Membership is git's own fact, not a string prefix.** Worktrees nest (a linked
worktree at ``untracked/worktrees/X`` sits INSIDE the main tree's directory), so
a prefix test would attribute X's files to the main tree. See
:mod:`claude_code_hooks_daemon.utils.git_checkouts`: the nearest ``.git`` marker
above the symlink-resolved path names the innermost checkout, and two checkouts
are the same repository when they share a common dir. No subprocess runs, and
therefore there is no worktree list to cache -- the cost is a few ``stat`` calls.

**Fails open.** Git metadata that cannot be read or parsed means the guard
cannot tell; it allows and says so in the debug log. A safety guard that
failed closed on an unreadable ``.git`` would block unrelated calls.
"""

from __future__ import annotations

import logging
from pathlib import Path
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
from claude_code_hooks_daemon.utils.git_checkouts import (
    Checkout,
    CheckoutUndecidableError,
    enclosing_checkout,
)

logger = logging.getLogger(__name__)

#: Tool -> the tool_input key naming the file it writes.
_TARGET_KEYS: Final[dict[str, str]] = {
    ToolName.WRITE: "file_path",
    ToolName.EDIT: "file_path",
    ToolName.NOTEBOOK_EDIT: "notebook_path",
}

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.SUBAGENT_CROSS_WORKTREE_WRITE,
    blocked="a subagent's Write/Edit/NotebookEdit into another checkout of its repository",
    why="Edits land uncommitted in a branch nobody on this task owns, and a later commit there carries them under the wrong branch's name",
    fix="Write only inside your own worktree; report any cross-branch need to the coordinator",
    verbose=(
        "WHY BLOCKED:\n"
        "You were given one git worktree to work in. Another worktree of the same\n"
        "repository (or the main working tree) belongs to a different branch and\n"
        "usually a different agent. An edit that lands there is invisible to that\n"
        "branch's owner, survives as an uncommitted change, and is committed by\n"
        "whoever lands that branch next -- under the wrong branch's name and\n"
        "without review. This has happened: 253 added lines from a sibling agent's\n"
        "work appeared in another branch's worktree.\n\n"
        "DO INSTEAD:\n"
        "  - Make the change in YOUR OWN worktree, on YOUR branch.\n"
        "  - If the change really belongs on another branch, or in the main\n"
        "    working tree, say so in your report to the coordinator and let it\n"
        "    decide and apply it. Cross-branch edits are the coordinator's call.\n\n"
        "The coordinator's own edits are unaffected: this rule applies only inside\n"
        "a subagent."
    ),
)


def _describe(checkout: Checkout) -> str:
    return (
        f"{checkout.root} (linked worktree)"
        if checkout.linked
        else (f"{checkout.root} (main working tree)")
    )


class SubagentWorktreeWriteGuardHandler(PreToolUseHandlerBase):
    """Deny a subagent's write into a checkout other than the one it works in.

    Terminal: a deny here is the final word on this tool call.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SUBAGENT_WORKTREE_WRITE_GUARD,
            priority=Priority.SUBAGENT_WORKTREE_WRITE_GUARD,
            terminal=True,
            # The whole role test; see the module docstring.
            scope=HandlerScope.SUB,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING, HandlerTag.WORKFLOW],
        )

    def get_default_enabled(self) -> bool:
        """Opt-OUT handler -- ON by default.

        Silent by construction for a project that never runs subagents in
        linked worktrees. Must stay consistent with the config template.
        """
        return True

    @staticmethod
    def _target(hook_input: dict[str, Any]) -> str | None:
        key = _TARGET_KEYS.get(str(hook_input.get(HookInputField.TOOL_NAME, "")))
        if key is None:
            return None
        tool_input = hook_input.get(HookInputField.TOOL_INPUT)
        if not isinstance(tool_input, dict):
            return None
        named = tool_input.get(key)
        return named if isinstance(named, str) and named else None

    @staticmethod
    def _crossing(hook_input: dict[str, Any]) -> tuple[Checkout, Checkout] | None:
        """``(own, target)`` when the call writes outside its own linked worktree.

        ``None`` when there is no crossing.

        Raises:
            CheckoutUndecidableError: A git marker on the cwd or target side
                cannot be read; the callers allow and log it.
        """
        target = SubagentWorktreeWriteGuardHandler._target(hook_input)
        if target is None:
            return None
        cwd = hook_input.get(HookInputField.CWD)
        if not isinstance(cwd, str) or not cwd:
            logger.debug("subagent_worktree_write_guard: no cwd in hook input; allowing")
            return None
        own = enclosing_checkout(cwd)
        if own is None:
            logger.debug(
                "subagent_worktree_write_guard: cwd %s is not inside a git checkout; allowing",
                cwd,
            )
            return None
        if not own.linked:
            return None
        there = enclosing_checkout(Path(cwd) / target)
        if there is None:
            return None
        if there.common_dir != own.common_dir or there.root == own.root:
            return None
        return own, there

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when a subagent's write targets a checkout other than its own.

        Fails open: git metadata that cannot be read means the guard cannot
        tell, so it allows and says why in the debug log.
        """
        try:
            return self._crossing(hook_input) is not None
        except CheckoutUndecidableError as exc:
            logger.debug("subagent_worktree_write_guard: undecidable, allowing: %s", exc)
            return False

    def get_rules(self) -> list[Rule]:
        """The single Rule backing this handler's deny."""
        return [_RULE]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Refuse, naming both checkouts and the route back to the coordinator.

        Always VERBOSE: each fire is a different subagent that has read nothing,
        and the explanation is what stops it looking for another route.
        """
        try:
            crossing = self._crossing(hook_input)
        except CheckoutUndecidableError as exc:
            logger.debug("subagent_worktree_write_guard: undecidable, allowing: %s", exc)
            return GatingResult(decision=Decision.ALLOW)
        if crossing is None:
            return GatingResult(decision=Decision.ALLOW)
        own, there = crossing
        message = (
            f"{RuleFormatter().verbose(_RULE)}\n\n"
            f"YOUR WORKTREE: {_describe(own)}\n"
            f"WRITE TARGET IN:  {_describe(there)}"
        )
        return GatingResult.deny(message)

    def get_acceptance_tests(self) -> list[Any]:
        """One case, declared as harness-undrivable rather than dressed up.

        The playbook harness marks every probe synthetic and the scope gate
        refuses a synthetic event for any scope other than ``ALL``, so a probe
        asserting this DENY would observe ALLOW for ever. The behaviour is
        covered by unit tests over real ``git worktree`` checkouts and by
        ``tests/unit/core/test_chain_handler_scope.py`` over the admission half.
        """
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="subagent worktree write guard - a write into a sibling worktree is denied",
                command="Write a file into another linked worktree of the repository from a subagent",
                description=(
                    "Inside a subagent whose cwd is a linked worktree, a Write/Edit/"
                    "NotebookEdit into a different linked worktree, or into the main "
                    "working tree, is refused; the reason names both checkouts and the "
                    "coordinator as the route. The coordinator's own writes, and a "
                    "subagent's writes in its own worktree, are untouched."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"coordinator", r"YOUR WORKTREE"],
                safety_notes=(
                    "Denies only inside a subagent working in a linked worktree, and only "
                    "a write whose target is in another checkout of the same repository."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=(
                    "The harness marks every probe synthetic, and a scoped handler "
                    "declines a synthetic event by construction -- so this probe would "
                    "observe ALLOW no matter what the handler does. It also needs a real "
                    "linked worktree as the cwd, which the harness cannot fabricate."
                ),
            ),
            AcceptanceTest(
                title="subagent worktree write guard - a write in its own worktree is untouched",
                command="Write a file inside the subagent's own linked worktree",
                description=(
                    "The near-miss. A subagent writing inside the worktree it was given is "
                    "the whole point of the worktree and must never be refused."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Negative case: a guard that refused a subagent's own worktree would "
                    "stop all work in it, and the first person to hit it would switch it off."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=(
                    "Same reason as the DENY sibling: the probe would be synthetic, and a "
                    "scoped handler declines a synthetic event before matches() runs, so "
                    "this would ALLOW for the wrong reason and prove nothing."
                ),
            ),
        ]

    def get_claude_md(self) -> str | None:
        """Resident guidance for the active-handler block.

        Resident rather than fire-time (criterion T4 in
        ``CLAUDE/HANDLER_DEVELOPMENT.md``): the standing rule is worth knowing
        BEFORE the first write, because a subagent that learns it from a deny
        has already planned its edit around the other worktree.
        """
        return (
            "## subagent_worktree_write_guard — a subagent writes only in its own worktree\n\n"
            "`Write`, `Edit` and `NotebookEdit` are DENIED inside a subagent whose working "
            "directory is a linked git worktree when the target is in a DIFFERENT checkout "
            "of the same repository: a sibling worktree, or the main working tree. Edits "
            "there surface uncommitted in a branch nobody on your task owns, and the next "
            "agent to land that branch commits them under the wrong name.\n\n"
            "**If you are a subagent**: change files only inside your own worktree. If the "
            "change belongs on another branch or in the main tree, say so in your report to "
            "the coordinator and let it apply it.\n\n"
            "Not judged: the coordinator (main thread), a subagent whose cwd is the main "
            "working tree, and paths outside the repository (`project_containment` owns "
            "that boundary). Worktrees nested inside the main tree are attributed to "
            "themselves, not to the main tree."
        )
