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
  module never uses ``agent_id`` for the role test (a second copy of a safety
  rule is how it drifts apart). It reads ``agent_id`` for exactly one other
  purpose, below: as the KEY of the worktree binding.
* A sub-agent whose cwd is the main working tree and which has no binding -- it
  was given no worktree to stay inside.
* A target outside R altogether, or in another repository: ``project_containment``
  owns the repository boundary.

**Membership is git's own fact, not a string prefix.** Worktrees nest (a linked
worktree at ``untracked/worktrees/X`` sits INSIDE the main tree's directory), so
a prefix test would attribute X's files to the main tree. See
:mod:`claude_code_hooks_daemon.utils.git_checkouts`: the nearest ``.git`` marker
above the symlink-resolved path names the innermost checkout, and two checkouts
are the same repository when they share a common dir. No subprocess runs, and
therefore there is no worktree list to cache -- the cost is a few ``stat`` calls.

**The first-write binding (ledger 00474 N282).** No payload field names the
worktree an in-process teammate was assigned, and its ``cwd`` is the session's
shared directory, so it follows wherever the coordinator last stood. Judging
by ``cwd`` alone therefore denies a teammate writing in its own worktree while
the coordinator is in a sibling, and judges nothing while the coordinator is in
the main tree. So the handler binds each ``agent_id`` to the LINKED worktree of
its first write and judges later writes against that binding:

* No binding, and the cwd rule above does not deny the write, and the target is
  in a linked worktree of the cwd's repository: bind ``agent_id`` to it. A
  first write the cwd rule DENIES binds nothing (a retry from another cwd must
  not launder a crossing), and a write into the main working tree binds nothing.
* Bound to W: a write into W is allowed whatever the cwd says; a write into any
  other checkout of the same repository (another worktree, or the main tree) is
  denied, even when the cwd is the main tree. A target outside the repository is
  not this guard's concern.
* No ``agent_id``, or no binding: the cwd rule, unchanged.

The binding is trust on first use: an agent whose first write is the wrong one is
bound wrong. It is held in memory on the handler instance, capped at
:data:`MAX_BINDINGS` least-recently-used entries, behind a lock (handlers may be
called concurrently). A daemon restart forgets every binding and the guard falls
back to the cwd rule until each agent writes again.

**Fails open.** Git metadata that cannot be read or parsed means the guard
cannot tell; it allows and says so in the debug log. A safety guard that
failed closed on an unreadable ``.git`` would block unrelated calls.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
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
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.git_checkouts import (
    Checkout,
    CheckoutUndecidableError,
    enclosing_checkout,
)

logger = logging.getLogger(__name__)

#: Most agent_id -> worktree bindings held at once; the least recently used is
#: evicted, so a long-lived daemon cannot grow the map without bound.
MAX_BINDINGS: Final[int] = 256

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
        self._lock = threading.Lock()
        self._bindings: OrderedDict[str, Checkout] = OrderedDict()
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

    def binding_count(self) -> int:
        """How many agents currently hold a worktree binding."""
        with self._lock:
            return len(self._bindings)

    def _bound(self, agent_id: str) -> Checkout | None:
        """The worktree ``agent_id`` is bound to, refreshing its recency. Lock held."""
        home = self._bindings.get(agent_id)
        if home is not None:
            self._bindings.move_to_end(agent_id)
        return home

    def _bind(self, agent_id: str, home: Checkout) -> None:
        """Bind ``agent_id`` to ``home``, evicting the least recently used. Lock held."""
        self._bindings[agent_id] = home
        self._bindings.move_to_end(agent_id)
        while len(self._bindings) > MAX_BINDINGS:
            self._bindings.popitem(last=False)

    def _crossing(self, hook_input: dict[str, Any]) -> tuple[Checkout, Checkout, bool] | None:
        """``(own, target, bound)`` when the call writes outside its own worktree.

        ``bound`` is True when ``own`` came from the agent's first-write binding
        rather than the payload cwd. ``None`` when there is no crossing.

        Side effect: a call that is not a crossing, from an agent with an
        ``agent_id`` and no binding yet, whose target is in a linked worktree,
        binds the agent to that worktree.

        Raises:
            CheckoutUndecidableError: A git marker on the cwd or target side
                cannot be read; the callers allow and log it.
        """
        target = self._target(hook_input)
        if target is None:
            return None
        cwd = hook_input.get(HookInputField.CWD)
        if not isinstance(cwd, str) or not cwd:
            logger.debug("subagent_worktree_write_guard: no cwd in hook input; allowing")
            return None
        there = enclosing_checkout(Path(cwd) / target)
        agent_id = hook_input.get(HookInputField.AGENT_ID)
        key = agent_id if isinstance(agent_id, str) and agent_id else None
        with self._lock:
            home = self._bound(key) if key is not None else None
            if home is not None:
                if there is None or there.common_dir != home.common_dir or there.root == home.root:
                    return None
                return home, there, True
            own = enclosing_checkout(cwd)
            if own is None:
                logger.debug(
                    "subagent_worktree_write_guard: cwd %s is not inside a git checkout; allowing",
                    cwd,
                )
                return None
            if there is None or there.common_dir != own.common_dir:
                return None
            if own.linked and there.root != own.root:
                return own, there, False
            if key is not None and there.linked:
                self._bind(key, there)
            return None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when a subagent's write targets a checkout other than its own.

        Fails open: git metadata that cannot be read means the guard cannot
        tell, so it allows and says why in the debug log.
        """
        try:
            return self._crossing(hook_input) is not None
        except CheckoutUndecidableError as exc:
            log_and_continue(
                logger,
                exc,
                reason=(
                    "subagent_worktree_write_guard: checkout undecidable, allowing; the guard "
                    "only denies cross-checkout writes it can prove (fail-open by design)"
                ),
                level=logging.DEBUG,
            )
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
        own, there, bound = crossing
        origin = (
            "\n(Your worktree was bound from your agent's first write in this session.)"
            if bound
            else ""
        )
        message = (
            f"{RuleFormatter().verbose(_RULE)}\n\n"
            f"YOUR WORKTREE: {_describe(own)}{origin}\n"
            f"WRITE TARGET IN:  {_describe(there)}\n"
            f"WRITE TARGET: {self._target(hook_input)}"
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
            "**Only those three tools are judged.** A file written through Bash (`>`, `>>`, "
            "`tee`, a heredoc, `cp`, `mv`) into another checkout reaches disk unexamined by "
            "this guard, so a Bash write that drew no complaint is NOT a write that passed "
            "it. The rule binds you either way.\n\n"
            "**If you are a subagent**: change files only inside your own worktree. If the "
            "change belongs on another branch or in the main tree, say so in your report to "
            "the coordinator and let it apply it.\n\n"
            "**Your worktree is the one you first write into.** The guard binds your "
            "`agent_id` to the linked worktree of your first `Write`/`Edit`/`NotebookEdit` "
            "(the `agent_id` is only a map key for that binding, never a role test) and "
            "judges every later write against it, whatever the shared working directory "
            "says. So make your first write inside your own worktree. The binding lives in "
            "the daemon's memory; a daemon restart forgets it and the working directory "
            "decides again.\n\n"
            "Not judged: the coordinator (main thread), a subagent with no binding whose "
            "cwd is the main working tree, and paths outside the repository "
            "(`project_containment` owns that boundary). Worktrees nested inside the main "
            "tree are attributed to themselves, not to the main tree."
        )
