"""GitUpstreamCheckerHandler - fetch + pull policy on session start (Plan 00178/00179).

On new sessions (not resumes) this handler runs an **additive** ``git fetch
--all`` (never ``--prune`` — Plan 00179: the session-start path never mutates
anything lossy automatically) and then does two independent things:

1. **Behind upstream** — when the current branch is behind its upstream, acts on
   a configurable ``mode``:
   - ``warn`` (default) — inject a strong advisory recommending ``git pull``.
   - ``agent-pull`` — inject a directive telling the agent to run ``git pull``
     itself as its first action.
   - ``auto-pull`` — the daemon runs ``git pull --ff-only`` (only on a clean,
     non-diverged tree) and reports the outcome; otherwise it degrades to a
     warning so the operator resolves the situation deliberately.

2. **Gone branches** — detects (non-destructively) local branches whose upstream
   was deleted on the remote, classifies each merged/not-merged, and advises the
   agent to clean up safely (``git branch -d`` for merged, ask the human for the
   rest) and optionally ``git fetch --prune`` the stale remote-tracking refs
   AFTER reviewing. The daemon never prunes or deletes a branch itself.

The git mechanism lives in :mod:`claude_code_hooks_daemon.utils.git_sync`; this
handler owns only policy. It is advisory (non-terminal) and stays silent when up
to date with no gone branches, not a git repo, detached, or without an upstream.
"""

import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    Priority,
)
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils import git_sync
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session

logger = logging.getLogger(__name__)

_MODE_WARN = "warn"
_MODE_AGENT_PULL = "agent-pull"
_MODE_AUTO_PULL = "auto-pull"
_VALID_MODES = frozenset({_MODE_WARN, _MODE_AGENT_PULL, _MODE_AUTO_PULL})
_DEFAULT_MODE = _MODE_WARN

_ICON = "⬇️"
_GONE_ICON = "🧹"
_MERGED_MARK = "✓"
_UNMERGED_MARK = "⚠"
_FAST_FORWARD_DETAIL = "fast-forwarded"


class GitUpstreamCheckerHandler(SessionStartHandlerBase):
    """Full-fetch + configurable pull policy when a branch is behind upstream."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.GIT_UPSTREAM_CHECKER,
            priority=Priority.GIT_UPSTREAM_CHECKER,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.GIT,
                HandlerTag.NON_TERMINAL,
                HandlerTag.WORKFLOW,
            ],
        )
        # Config options land here via the registry's ``setattr(instance,
        # f"_{key}", value)`` injection (matching git_branch's ``_auto_fetch``).
        self._mode: str = _DEFAULT_MODE
        self._auto_fetch: bool = True

    # ------------------------------------------------------------------
    # Session / repo helpers
    # ------------------------------------------------------------------

    def _get_project_root(self) -> Path:
        try:
            return ProjectContext.project_root()
        except RuntimeError:
            logger.debug("ProjectContext not initialised; using cwd for upstream check")
            return Path.cwd()

    def _resolve_mode(self) -> str:
        mode = getattr(self, "_mode", _DEFAULT_MODE)
        if mode not in _VALID_MODES:
            logger.warning(
                "Unknown git_upstream_checker mode %r; falling back to '%s'", mode, _DEFAULT_MODE
            )
            return _DEFAULT_MODE
        return mode

    # ------------------------------------------------------------------
    # Handler protocol
    # ------------------------------------------------------------------

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Run on new sessions only (skip resumes to avoid re-fetch churn)."""
        return not is_resume_session(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        root = self._get_project_root()

        gones: list[git_sync.GoneBranch] = []
        if self._auto_fetch:
            # Additive fetch (never prunes) so ahead/behind is measured against
            # fresh remote refs. Fail-silent: offline still reports staleness
            # from existing refs. Gone-branch detection is a network dry-run
            # probe, so it too is gated behind auto_fetch.
            git_sync.fetch_all(root)
            gones = git_sync.gone_branches(root)

        status = git_sync.upstream_status(root)

        context: list[str] = []
        if status is not None and status.behind > 0:
            context = self._behind_context(root, status)

        if gones:
            gone_ctx = self._gone_branch_context(gones)
            context = [*context, "", *gone_ctx] if context else gone_ctx

        # Silent when up to date with no gone branches (or not a repo / detached).
        return AdvisoryResult(decision=Decision.ALLOW, context=context)

    def _behind_context(self, root: Path, status: git_sync.UpstreamStatus) -> list[str]:
        """Dispatch the behind-upstream advisory according to the configured mode.

        A rewritten upstream pre-empts every mode. Ahead/behind counts cannot
        tell that state apart from ordinary divergence, but the right advice is
        opposite, and this handler is usually the only thing that speaks up on a
        fresh session — so getting it wrong here is the most consequential
        sentence it can emit.
        """
        if status.ahead > 0 and git_sync.upstream_was_rewritten(root):
            return self._rewrite_context(status)
        mode = self._resolve_mode()
        if mode == _MODE_AUTO_PULL:
            return self._auto_pull(root, status)
        if mode == _MODE_AGENT_PULL:
            return self._agent_pull_context(status)
        return self._warn_context(status)

    # ------------------------------------------------------------------
    # Message builders
    # ------------------------------------------------------------------

    def _behind_lines(self, status: git_sync.UpstreamStatus) -> list[str]:
        """Shared "you are behind" summary (adds a divergence note when ahead)."""
        lines = [
            f"{_ICON}  GIT: branch '{status.branch}' is {status.behind} commit(s) "
            f"behind {status.upstream}."
        ]
        if status.ahead > 0:
            lines.append(
                f"   Local history has also moved on ({status.ahead} commit(s) ahead) — "
                "the branches have diverged."
            )
        return lines

    def _rewrite_context(self, status: git_sync.UpstreamStatus) -> list[str]:
        """Advice for a divergence whose two sides hold IDENTICAL content.

        Deliberately says nothing about pulling, in any wording. An agent that
        reads "pull" in any form here will reach for it, and after a rewrite
        that single command re-merges every pre-rewrite commit and republishes
        whatever the rewrite was run to remove.
        """
        lines = self._behind_lines(status)
        lines.extend(
            [
                "",
                f"   ⚠️  DO NOT MERGE. {status.upstream} appears to have been "
                "REWRITTEN: your local commits have patch-IDENTICAL twins "
                "upstream under different shas. The content is already there, "
                "so there is nothing to merge.",
                f"   Merging would drag {status.ahead} pre-rewrite commit(s) back "
                "in and republish whatever the rewrite removed. (A rewrite keeps "
                "untouched early history, so a shared merge base proves nothing "
                "here.)",
                "",
                "   Realign instead. This discards local commits, so a human "
                "should run it deliberately:",
                "",
                "     git fetch origin",
                f"     git reset --hard {status.upstream}",
                "     git fetch --tags --force",
                "",
                "   It changes no files: the trees already match. The tag fetch "
                "matters too — a rewrite moves every tag to a new sha.",
            ]
        )
        return lines

    def _warn_context(self, status: git_sync.UpstreamStatus) -> list[str]:
        lines = self._behind_lines(status)
        lines.append("")
        if status.ahead > 0:
            lines.append(
                "A `git pull` is strongly recommended, but history has diverged: review "
                "before merging, or use `git pull --rebase` once you understand the changes."
            )
        else:
            lines.append(
                "A `git pull` is strongly recommended to catch up with the remote "
                "before you continue."
            )
        return lines

    def _agent_pull_context(self, status: git_sync.UpstreamStatus) -> list[str]:
        lines = self._behind_lines(status)
        lines.append("")
        lines.append(
            f"ACTION REQUIRED (mode: {_MODE_AGENT_PULL}): run `git pull` now as your first "
            "action, before any other work."
        )
        if status.ahead > 0:
            lines.append(
                "History has diverged — resolve conflicts (or `git pull --rebase`) carefully, "
                "then verify the daemon still restarts before continuing."
            )
        else:
            lines.append("Then continue with the task.")
        return lines

    def _auto_pull(self, root: Path, status: git_sync.UpstreamStatus) -> list[str]:
        """Deterministically fast-forward when safe; otherwise degrade to a warning."""
        if not git_sync.working_tree_clean(root):
            lines = self._behind_lines(status)
            lines.append("")
            lines.append(
                f"auto-pull skipped: the working tree has uncommitted changes. Commit or "
                f"stash them, then run `git pull`. (mode: {_MODE_AUTO_PULL})"
            )
            return lines

        if status.ahead > 0:
            lines = self._behind_lines(status)
            lines.append("")
            lines.append(
                "auto-pull skipped: history has diverged, so a fast-forward-only pull is not "
                "possible. Run `git pull` (merge) or `git pull --rebase` manually. "
                f"(mode: {_MODE_AUTO_PULL})"
            )
            return lines

        result = git_sync.pull_ff_only(root)
        if result.ok:
            lines = [
                f"{_ICON}  GIT: auto-pulled {status.behind} commit(s) from {status.upstream} "
                f"(fast-forward). (mode: {_MODE_AUTO_PULL})"
            ]
            if result.detail and result.detail != _FAST_FORWARD_DETAIL:
                lines.append(f"   {result.detail}")
            return lines

        lines = self._behind_lines(status)
        lines.append("")
        lines.append(
            f"auto-pull attempted `git pull --ff-only` but it did not succeed: {result.detail}"
        )
        lines.append(f"Run `git pull` manually to resolve. (mode: {_MODE_AUTO_PULL})")
        return lines

    def _gone_branch_context(self, gones: list[git_sync.GoneBranch]) -> list[str]:
        """Advise on local branches whose upstream was deleted — never auto-delete.

        The daemon has NOT pruned or deleted anything. It classifies each gone
        branch merged (safe to remove) vs not-merged (needs human confirmation)
        and hands the agent an explicit, checked cleanup path.
        """
        lines = [
            f"{_GONE_ICON}  GIT: {len(gones)} local branch(es) track a remote branch that was "
            "DELETED on the remote. Nothing was pruned or deleted automatically.",
            "",
        ]
        for gone in gones:
            if gone.merged:
                lines.append(
                    f"  {_MERGED_MARK} {gone.name} (was {gone.upstream}) — merged into the "
                    f"default branch; safe to remove: `git branch -d {gone.name}`"
                )
            else:
                lines.append(
                    f"  {_UNMERGED_MARK} {gone.name} (was {gone.upstream}) — has commit(s) NOT "
                    "on the default branch; deleting it loses that work. Do NOT delete without "
                    "confirming with the human first."
                )
        lines += [
            "",
            "After double-checking the above you MAY tidy up: run `git fetch --prune` (or "
            "`git remote prune origin`) to drop the stale remote-tracking refs — that is safe, "
            "it only touches `origin/*` cache refs. Then `git branch -d <name>` each merged "
            f"({_MERGED_MARK}) branch; for any {_UNMERGED_MARK} branch, ask the human before "
            "removing it. Never use `git branch -D` (force-delete) to bypass the safety check.",
        ]
        return lines

    # ------------------------------------------------------------------
    # Guidance / acceptance
    # ------------------------------------------------------------------

    def get_claude_md(self) -> str | None:
        return (
            "## git_upstream_checker — additive fetch + pull/cleanup advice on session start\n\n"
            "On each new session the daemon runs an **additive** `git fetch --all` (never "
            "`--prune` — it never removes anything automatically) and then:\n\n"
            "**If your branch is behind its upstream**, acts on the configured `mode`:\n"
            "- `warn` (default): strongly advises you to run `git pull`.\n"
            "- `agent-pull`: instructs you to run `git pull` as your first action.\n"
            "- `auto-pull`: the daemon runs `git pull --ff-only` for you on a clean, "
            "non-diverged tree; if it cannot fast-forward (dirty tree or diverged history) "
            "it degrades to a warning and you pull manually.\n\n"
            "**If the upstream was REWRITTEN**, every mode above is overridden and NO pull "
            "is advised in any wording. The signal is a divergence whose two sides share no "
            "commit shas yet resolve to the SAME tree: identical content, so there is nothing "
            "to merge and each local commit is a pre-rewrite duplicate. Pulling would merge "
            "the entire pre-rewrite history back in and republish whatever the rewrite (a "
            "`filter-repo` secret-strip, say) was run to remove. The advisory instead asks a "
            "human to realign the branch onto its upstream and to re-fetch tags with "
            "`--force`, since a rewrite moves every tag to a new sha. Do NOT work around "
            "this by pulling — if you believe the divergence is genuine, check the trees "
            "yourself before merging.\n\n"
            "**If local branches track a remote branch that was deleted**, it lists them "
            "(marked merged = safe vs not-merged = has unique commits) and asks you to clean "
            "up AFTER checking: `git branch -d <name>` for merged branches, ask the human for "
            "the rest, and optionally `git fetch --prune` the stale remote-tracking refs. The "
            "daemon never prunes or deletes a branch itself; never use `git branch -D`.\n\n"
            "It is silent when up to date with no gone branches, not in a git repo, on a "
            "detached HEAD, or without an upstream. Configure via "
            "`handlers.session_start.git_upstream_checker.options.mode`."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="git upstream checker - fetches and advises pull when behind",
                command='echo "test"',
                description=(
                    "On a new session the handler runs an additive git fetch --all --no-prune "
                    "and, when the branch is behind upstream, advises (or performs, per mode) a "
                    "git pull."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"git pull|behind|auto-pulled"],
                safety_notes="Advisory in warn/agent-pull; auto-pull only fast-forwards a clean tree",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session only)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
