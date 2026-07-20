"""GitUpstreamCheckerHandler - fetch + pull policy on session start (Plan 00178).

On new sessions (not resumes) this handler runs a full ``git fetch --all
--prune`` and, when the current branch is **behind** its upstream, acts
according to a configurable ``mode``:

- ``warn`` (default) — inject a strong advisory recommending ``git pull``.
- ``agent-pull`` — inject a directive telling the agent to run ``git pull``
  itself as its first action.
- ``auto-pull`` — the daemon runs ``git pull --ff-only`` (only on a clean,
  non-diverged tree) and reports the outcome; otherwise it degrades to a warning
  so the operator resolves the situation deliberately.

The git mechanism lives in :mod:`claude_code_hooks_daemon.utils.git_sync`; this
handler owns only policy. It is advisory (non-terminal) and stays silent when up
to date, not a git repo, detached, or the branch has no upstream.
"""

import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils import git_sync

logger = logging.getLogger(__name__)

_MODE_WARN = "warn"
_MODE_AGENT_PULL = "agent-pull"
_MODE_AUTO_PULL = "auto-pull"
_VALID_MODES = frozenset({_MODE_WARN, _MODE_AGENT_PULL, _MODE_AUTO_PULL})
_DEFAULT_MODE = _MODE_WARN

_ICON = "⬇️"
_RESUME_TRANSCRIPT_MIN_BYTES = 100
_FAST_FORWARD_DETAIL = "fast-forwarded"


class GitUpstreamCheckerHandler(Handler):
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

    def _is_resume_session(self, hook_input: dict[str, Any]) -> bool:
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        if not transcript_path:
            return False
        try:
            path = Path(transcript_path)
            return path.exists() and path.stat().st_size > _RESUME_TRANSCRIPT_MIN_BYTES
        except (OSError, ValueError):
            return False

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
        return not self._is_resume_session(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        root = self._get_project_root()

        if self._auto_fetch:
            # Full fetch so ahead/behind is measured against fresh remote refs.
            # Fail-silent: offline still reports staleness from existing refs.
            git_sync.fetch_all_prune(root)

        status = git_sync.upstream_status(root)
        if status is None or status.behind == 0:
            # Silent when up to date / not a repo / detached / no upstream.
            return HookResult(decision=Decision.ALLOW, context=[])

        mode = self._resolve_mode()
        if mode == _MODE_AUTO_PULL:
            context = self._auto_pull(root, status)
        elif mode == _MODE_AGENT_PULL:
            context = self._agent_pull_context(status)
        else:
            context = self._warn_context(status)

        return HookResult(decision=Decision.ALLOW, context=context)

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

    # ------------------------------------------------------------------
    # Guidance / acceptance
    # ------------------------------------------------------------------

    def get_claude_md(self) -> str | None:
        return (
            "## git_upstream_checker — full fetch + pull policy on session start\n\n"
            "On each new session the daemon runs a full `git fetch --all --prune` and, if "
            "your branch is behind its upstream, acts on the configured `mode`:\n\n"
            "- `warn` (default): strongly advises you to run `git pull`.\n"
            "- `agent-pull`: instructs you to run `git pull` as your first action.\n"
            "- `auto-pull`: the daemon runs `git pull --ff-only` for you on a clean, "
            "non-diverged tree; if it cannot fast-forward (dirty tree or diverged history) "
            "it degrades to a warning and you pull manually.\n\n"
            "It is silent when up to date, not in a git repo, on a detached HEAD, or when the "
            "branch has no upstream. Configure via "
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
                    "On a new session the handler runs a full git fetch --all --prune and, when "
                    "the branch is behind upstream, advises (or performs, per mode) a git pull."
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
