"""WorktreeCreate handler — daemon-owned semantic worktree creation (Plan 00188).

Claude Code's ``WorktreeCreate`` hook (fired for ``isolation: "worktree"`` agents
and ``--worktree`` sessions) fully delegates path choice to the hook: the input
carries no path, only a ``name`` field. The hook MUST create the worktree
directory and print its absolute path on stdout — a non-zero exit or a
non-directory path fails creation.

Before this handler the daemon shipped only a fail-open ``{}`` passthrough, which
Claude Code took literally as the path ``/<cwd>/{}`` — breaking every worktree
launch. This handler creates a real git worktree at a *human-friendly semantic*
path (``.claude/worktrees/<slug-of-name>-<shorthash>/``) and returns it, so the
worktree list reads e.g. ``refactor-auth-4f2a1c9b`` instead of Claude Code's
opaque ``wf_<hash>``.
"""

from __future__ import annotations

import subprocess  # nosec B404 — CalledProcessError typing only; run_git owns the spawn
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import AdvisoryResult
from claude_code_hooks_daemon.core.handler_bases import WorktreeCreateHandlerBase
from claude_code_hooks_daemon.core.worktree_naming import worktree_dir_name, worktree_path
from claude_code_hooks_daemon.utils.git_repo import run_git

# This handler is the only one on the WorktreeCreate event; priority is nominal.
_WORKTREE_CREATE_PRIORITY = 50

# Hook-input keys Claude Code sends (captured from a real WorktreeCreate payload).
_KEY_CWD = "cwd"
_KEY_NAME = "name"
_KEY_PROMPT_ID = "prompt_id"
_KEY_SESSION_ID = "session_id"


class WorktreeCreateHandler(WorktreeCreateHandlerBase):
    """Create a git worktree at a semantic path and return its absolute path."""

    def __init__(self) -> None:
        super().__init__(
            HandlerID.WORKTREE_CREATE,
            priority=_WORKTREE_CREATE_PRIORITY,
            terminal=True,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Handle every WorktreeCreate event (no matcher filtering)."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Create (or reuse) the worktree and return its absolute path."""
        cwd = str(hook_input.get(_KEY_CWD) or Path.cwd())
        name = hook_input.get(_KEY_NAME)
        prompt_id = hook_input.get(_KEY_PROMPT_ID)
        session_id = hook_input.get(_KEY_SESSION_ID)

        path = worktree_path(cwd, name, prompt_id, session_id)

        # Idempotent: a re-fired event for the same agent reuses the worktree.
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            branch = worktree_dir_name(name, prompt_id, session_id)
            self._git_worktree_add(cwd, path, branch)

        return AdvisoryResult(worktree_path=str(path))

    @staticmethod
    def _git_worktree_add(cwd: str, path: Path, branch: str) -> None:
        """Run ``git worktree add -b <branch> <path>`` from ``cwd``.

        Fails LOUDLY (raises) rather than returning an empty response — an
        unusable path would re-introduce the original ``/<cwd>/{}`` breakage.
        :func:`run_git` never raises, so the ``returncode`` is checked
        explicitly and translated into the same ``CalledProcessError`` a
        ``check=True`` spawn would have raised.
        """
        result = run_git(
            Path(cwd), "worktree", "add", "-b", branch, str(path), timeout=Timeout.GIT_WORKTREE
        )
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, result.args, result.stdout, result.stderr
            )

    def get_claude_md(self) -> str | None:
        """Guidance injected into the project CLAUDE.md."""
        return (
            "## worktree_create — semantic worktree naming\n\n"
            'When Claude Code creates a worktree (an `isolation: "worktree"` agent '
            "or `--worktree` session), the daemon creates it at a human-friendly "
            "path `.claude/worktrees/<slug-of-name>-<shorthash>/` and echoes that "
            "path. Name an agent semantically (the Agent tool's `name:`) to get a "
            "readable worktree directory (e.g. `refactor-auth-4f2a1c9b`) instead of "
            "an opaque `wf_<hash>`. The short hash suffix keeps identically-named "
            "agents from colliding."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """VERIFIED_BY_LOAD: WorktreeCreate fires only when Claude Code spawns a
        worktree (untriggerable by a tool call), so it is verified by daemon load
        + unit tests against a real git repo + a live worktree-agent dogfood.
        """
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="worktree_create returns a real path (not '{}')",
                command='echo "worktree create verified by unit tests + live dogfood"',
                description=(
                    "WorktreeCreate creates a git worktree at "
                    ".claude/worktrees/<slug>-<hash>/ and returns its absolute path; "
                    "never an empty {} (which Claude Code would take as /<cwd>/{})."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Untriggerable by tool call; verified by daemon load + unit tests.",
                test_type=TestType.CONTEXT,
                requires_event="WorktreeCreate event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
