"""BranchSweepHandler - the SessionStart branch summary (Plan 00558 Task 2.3).

Runs the branch inventory (``core/branch_inventory.py``) inside
``branches.sweep.budget_ms`` with its on-disk cache, and prints the short
summary from ``core/branch_sweep.py``: every branch whose commits no remote ref
holds on EVERY SessionStart source, and on a new session the dormant branches,
the merged-but-undeleted count and the open-work count against the cap. Silent
when there is nothing to say, outside a git repository, or when the inventory
cannot run. Advisory only; ``hooks-daemon branch-sweep`` is the full report.

Replaces ``branch_count_advisor``, whose config key is folded into this
handler's at config load (``constants.handlers.HANDLER_KEY_ALIASES``) so an existing
``enabled: false`` still silences it and its two options are read as the
fallback for one release (DESIGN.md section 1).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision, ownership
from claude_code_hooks_daemon.core.branch_creation import (
    LABELS_RELATIVE_PATH,
    creation_report,
    read_labels,
    render_creation_report,
    write_labels,
)
from claude_code_hooks_daemon.core.branch_inventory import BranchInventoryError, build_inventory
from claude_code_hooks_daemon.core.branch_park import BranchParkError, announce_ended_parks
from claude_code_hooks_daemon.core.branch_sweep import (
    deprecation_line,
    effective_behind_threshold,
    effective_wip_cap,
    report_json,
    session_summary,
)
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.ownership import OwnershipHint
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session

logger = logging.getLogger(__name__)

_ICON = "🌿"
_NOTICE_ICON = "⚠️"


class BranchSweepHandler(SessionStartHandlerBase):
    """Summarise branches that need attention: unpushed, merged, dormant, over the cap."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.BRANCH_SWEEP,
            priority=Priority.BRANCH_SWEEP,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.GIT,
                HandlerTag.NON_TERMINAL,
                HandlerTag.WORKFLOW,
            ],
        )
        # Injected by the registry from the top-level `branches:` block.
        self._branches: BranchesConfig = BranchesConfig()
        # The retired branch_count_advisor options, read for one release only
        # when the matching `branches.*` key is unset (DESIGN.md section 1).
        self._max_open_branches: int | None = None
        self._behind_main_threshold: int | None = None
        # Asked at each SessionStart for what an agent should hear about the
        # CLAUDE.md hooks-daemon block (stale on a home branch, no home branch
        # resolved). The daemon controller sets it to the injector's
        # `current_notices`, so the answer reflects the checkout as it is NOW.
        self.claude_md_notices: Callable[[], list[str]] | None = None

    def _legacy_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {}
        if self._max_open_branches is not None:
            options["max_open_branches"] = self._max_open_branches
        if self._behind_main_threshold is not None:
            options["behind_main_threshold"] = self._behind_main_threshold
        return options

    def _get_project_root(self) -> Path:
        try:
            return ProjectContext.project_root()
        except RuntimeError:
            logger.debug("ProjectContext not initialised; using cwd for the branch sweep")
            return Path.cwd()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Every source: a branch no remote holds is reported on resume and compact too."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Run the inventory within its budget and print the summary, or nothing."""
        context = [
            *self._ended_park_lines(),
            *self._branch_lines(hook_input),
            *self._claude_md_notice_lines(),
        ]
        return AdvisoryResult(decision=Decision.ALLOW, context=context)

    def _ended_park_lines(self) -> list[str]:
        """``Park cleared: ...`` for each park that ended since the last session; empty if none."""
        try:
            return announce_ended_parks(self._get_project_root())
        except BranchParkError as exc:
            log_and_continue(
                logger,
                exc,
                reason="the park-cleared line is advisory (not a repository, or git failed); "
                "the record stays and the next SessionStart says it",
                level=logging.DEBUG,
            )
            return []

    def _claude_md_notice_lines(self) -> list[str]:
        """The CLAUDE.md block notices, fresh for this SessionStart; empty when none or unreadable."""
        if self.claude_md_notices is None:
            return []
        try:
            notices = self.claude_md_notices()
        except Exception as exc:  # advisory must never break SessionStart
            log_and_continue(
                logger,
                exc,
                reason="the CLAUDE.md block notice is advisory; the branch summary still "
                "runs and the next SessionStart asks again",
            )
            return []
        if not notices:
            return []
        return [f"{_NOTICE_ICON}  CLAUDE.MD BLOCK:", *(f"  - {notice}" for notice in notices)]

    def _branch_lines(self, hook_input: dict[str, Any]) -> list[str]:
        """The branch summary lines, or none."""
        root = self._get_project_root()
        legacy = self._legacy_options()
        try:
            inventory = build_inventory(root, self._branches)
        except BranchInventoryError as exc:
            log_and_continue(
                logger,
                exc,
                reason="no inventory (not a repository, or git failed) means no summary; "
                "`hooks-daemon branch-sweep` reports the failure itself",
                level=logging.DEBUG,
            )
            return []
        cap = effective_wip_cap(self._branches, legacy)
        session_id = hook_input.get(HookInputField.SESSION_ID)

        def owned_hint() -> str | None:
            """The owned-branch hint, the first time this session asks for it."""
            return ownership.hint_once(OwnershipHint.BRANCH_OWNED, session_id)

        # The branch creation guard orders its deny list from this snapshot:
        # it cannot afford the inventory on the PreToolUse path.
        write_labels(
            root / LABELS_RELATIVE_PATH,
            report_json(inventory, cap=cap, config=self._branches)["branches"],
        )
        lines = session_summary(
            inventory,
            self._branches,
            cap=cap,
            new_session=not is_resume_session(hook_input),
            deprecation=deprecation_line(self._branches, legacy),
            behind_threshold=effective_behind_threshold(self._branches, legacy),
            owned_hint=owned_hint,
        )
        out = [f"{_ICON}  GIT BRANCHES:", *lines] if lines else []
        return [*out, *self._pool_lines(root, owned_hint)]

    def _pool_lines(self, root: Path, owned_hint: Callable[[], str | None]) -> list[str]:
        """Every full pool with its fix: the preflight report (``branch-preflight``)."""
        report = creation_report(
            root, self._branches, None, labels=read_labels(root / LABELS_RELATIVE_PATH)
        )
        if not report.blockers:
            return []
        preflight = daemon_cli_command_for_docs("branch-preflight")
        text = owned_hint()
        hint = [] if text is None else [text]
        return [
            f"{_ICON}  BRANCH POOLS (same report as `{preflight}`):",
            *render_creation_report(report),
            *hint,
        ]

    def get_claude_md(self) -> str | None:
        """The branch summary and the cap are a standing policy."""
        return (
            "## branch_sweep — branches that need attention\n\n"
            "At SessionStart the branch inventory is summarised: a branch whose commits no "
            "fetched remote-tracking ref holds is named on EVERY session start as "
            "`CONTAINED NOWHERE`, with the `git push -u` that secures it (the summary makes no "
            "network call, so a remote that holds it outside `refs/heads` is not seen; "
            "`branch-sweep` and `delete-branch` ask the remote once); on a new session it also names dormant "
            "branches, work branches more than `branches.sweep.behind_threshold` commits "
            "behind the default, the count of merged branches not yet deleted, and the "
            "open-work count "
            f"against `branches.wip.cap`. Run `{daemon_cli_command_for_docs('branch-sweep')}` for the full "
            "report (`--json` for the records, `--all` for exempt and protected branches) "
            f"and delete a done branch with the `{daemon_cli_command_for_docs('delete-branch')}` command it "
            "prints, never a raw force delete. Replaces `branch_count_advisor`: that key "
            "still disables this handler, and its `max_open_branches` / "
            "`behind_main_threshold` options are read for one release when "
            "`branches.wip.cap` / `branches.sweep.behind_threshold` are unset. The same summary "
            "carries a `CLAUDE.MD BLOCK` notice, recomputed at every SessionStart, when the "
            "`<hooksdaemon>` block is stale on a home branch under `branches.home_commit: "
            "false` or no home branch resolves to a local branch (set `branches.home`); this handler is "
            "the only carrier of that notice, so with it disabled nothing tells an agent. Advisory only."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance test: the summary is silent or names branches, never blocks."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="branch sweep - summarises branches needing attention",
                command='echo "test"',
                description=(
                    "On SessionStart the handler runs the branch inventory and, when a "
                    "branch is contained nowhere, merged but not deleted, dormant, or the "
                    "open-work count reaches the cap, prints a short summary pointing at "
                    "`hooks-daemon branch-sweep`. Silent otherwise. It never blocks."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[
                    r"CONTAINED NOWHERE|merged branch|Dormant|Behind|Open work|^$"
                ],
                safety_notes="Advisory only; reads branch refs, changes nothing",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
