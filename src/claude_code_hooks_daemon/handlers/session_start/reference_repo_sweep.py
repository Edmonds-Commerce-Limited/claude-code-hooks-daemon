"""ReferenceRepoSweepHandler - make governed reference clones fresh at session start.

The convention: read-only clones of upstream repositories live under
``untracked/repos/`` so an agent can consult real source. The failure this
handler exists to prevent is an agent reading one WITHOUT pulling, reasoning
from a weeks-old checkout, and producing conclusions indistinguishable from
correct ones.

This is the surface that does the network work, and the reason the PreToolUse
backstop never has to. ``Timeout.GIT_FETCH_SESSION`` and ``GIT_PULL_SESSION``
are 30s apiece against a 30s hook socket budget, so fetching inside PreToolUse
could consume the whole budget for ONE repo — and a project can govern several.
SessionStart already owns a network budget, so the fetching happens here and the
result is cached for everything downstream.

**The cache is written on EVERY run, including a completely clean one.** That
looks redundant and is not: the cache is what records that a check HAPPENED, so
a clean sweep that wrote nothing would leave every later read as NOT VERIFIED —
the backstop would enforce hardest precisely when the repos were perfect.

Advisory, never blocking. A session must not fail to start because a remote was
unreachable, so an offline machine degrades to a report built from the refs
already on disk.
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.reference_repos.cache import write_cache
from claude_code_hooks_daemon.reference_repos.discovery import discover_reference_repos
from claude_code_hooks_daemon.reference_repos.refresh import RefreshOutcome, refresh_repo
from claude_code_hooks_daemon.reference_repos.report import report_lines
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session

logger = logging.getLogger(__name__)

#: SessionStart carries several advisories. Naming a bounded sample plus the
#: total says the same thing without pushing the others out of view; the CLI
#: stays unbounded, because a report you asked for should show everything.
_MAX_LISTED: Final[int] = 10


class ReferenceRepoSweepHandler(SessionStartHandlerBase):
    """Fetch, safely fast-forward and record every governed reference repo."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.REFERENCE_REPO_SWEEP,
            priority=Priority.REFERENCE_REPO_SWEEP,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.GIT,
                HandlerTag.NON_TERMINAL,
                HandlerTag.WORKFLOW,
            ],
        )
        # Injected by the registry from the top-level ``reference_repos`` block
        # (the same DI idiom as plan_workflow). None means the block was never
        # resolved, which reads as OFF rather than as a crash at session start.
        self._reference_repos: Any = None
        self.project_root_reader: Callable[[], Path] = self._default_project_root
        self.refresher: Callable[..., RefreshOutcome] = refresh_repo

    @staticmethod
    def _default_project_root() -> Path:
        try:
            return ProjectContext.project_root()
        except RuntimeError:  # pragma: no cover - defensive, mirrors siblings
            logger.debug("ProjectContext not initialised; using cwd for the repo sweep")
            return Path.cwd()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Run on new sessions only, and only when the feature is configured on.

        A resume deliberately does NOT re-sweep: the readings written at startup
        still stand, and re-fetching every governed repo on each resume would
        spend the network budget to learn what is already cached.
        """
        config = self._reference_repos
        if config is None or not config.enabled:
            return False
        return not is_resume_session(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        config = self._reference_repos
        root = self.project_root_reader()

        repos = discover_reference_repos(
            [root / relative for relative in config.roots],
            exclude_globs=config.exclude,
            project_root=root,
        )

        states = [self.refresher(repo, allow_pull=config.auto_pull).state for repo in sorted(repos)]

        # Written unconditionally -- see the module docstring. An empty sweep
        # records "checked, governs nothing", which the reader must be able to
        # tell apart from "never checked".
        write_cache(root, states)

        # Silent when nothing needs attention. The renderer's one-line all-clear
        # is right for the CLI -- you asked, so it answers -- but SessionStart is
        # unsolicited, and an advisory that speaks when there is nothing to do
        # teaches the reader to skim past it on the day there is.
        if not any(state.needs_attention for state in states):
            return AdvisoryResult(decision=Decision.ALLOW, context=[])

        return AdvisoryResult(
            decision=Decision.ALLOW,
            context=report_lines(states, project_root=root, max_listed=_MAX_LISTED),
        )

    def get_claude_md(self) -> str | None:
        """Guidance for the generated ``<hooksdaemon>`` block."""
        return (
            "## reference_repo_sweep — reference clones are made fresh before you read them\n\n"
            "Reference repositories tracked under `untracked/repos/` (configurable via "
            "`reference_repos.roots`) are fetched at the start of every new session, and "
            "fast-forwarded when that is **provably** safe — a clean tree, no local commits, "
            "no divergence. Anything else is REPORTED and never touched, because a pull over "
            "uncommitted work costs someone their work, while staleness only costs a re-read.\n\n"
            "**A repo that cannot be checked never nags.** No remote, no upstream or a "
            "detached HEAD is stated once and then left alone, so a deliberately unreachable "
            "clone does not make every session open with a complaint nobody can action.\n\n"
            "The readings are cached for the session. If you see a repo reported as behind or "
            "on the wrong branch, run the `fix:` command printed beside it BEFORE relying on "
            "what that repo contains — its contents are not what you think they are."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="reference-repo sweep - session start freshness report",
                command='echo "session start"',
                description=(
                    "On a NEW session in a project with governed reference repos that are "
                    "behind or off their default branch, the SessionStart context names each "
                    "one and prints a runnable fix command. With every governed repo current, "
                    "the handler stays silent."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"reference repos|NOT VERIFIED"],
                safety_notes="Advisory handler - never blocks; never pulls a dirty repo",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session only)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
