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

import logging
import subprocess  # nosec B404 — only ever runs the trusted system ``git`` binary
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.core.worktree_naming import worktree_dir_name, worktree_path

logger = logging.getLogger(__name__)

# This handler is the only one on the WorktreeCreate event; priority is nominal.
_WORKTREE_CREATE_PRIORITY = 50

# Hook-input keys Claude Code sends (captured from a real WorktreeCreate payload).
_KEY_CWD = "cwd"
_KEY_NAME = "name"
_KEY_PROMPT_ID = "prompt_id"
_KEY_SESSION_ID = "session_id"

# Git-ignored local files SYMLINKED from the main working copy into a fresh
# worktree (Plan 00190). These live only in the developer's checkout — never
# committed — so a worktree checkout would otherwise lack them and the agent
# would run against a config missing its local overrides/secrets. A symlink (not
# a copy) keeps the main working copy as the single source of truth: editing the
# canonical file is reflected in every worktree, and there is never a stale
# duplicate to reconcile. Overridable per project via the ``symlink_files``
# handler option. The parent-traversal / absolute-path guard in ``_seed_files``
# keeps a misconfigured entry from escaping the worktree.
DEFAULT_WORKTREE_SYMLINK_FILES: tuple[str, ...] = (".env.local", ".env.test.local")

# Parent-directory reference — an entry containing this component is rejected so a
# symlink can never be written outside the worktree root.
_PARENT_REF = ".."


class WorktreeCreateHandler(Handler):
    """Create a git worktree at a semantic path and return its absolute path."""

    def __init__(self) -> None:
        super().__init__(
            HandlerID.WORKTREE_CREATE,
            priority=_WORKTREE_CREATE_PRIORITY,
            terminal=True,
        )
        # Files symlinked into a fresh worktree; the registry overrides this from
        # the ``symlink_files`` handler option (Plan 00190) via setattr, else the
        # default.
        self._symlink_files: list[str] = list(DEFAULT_WORKTREE_SYMLINK_FILES)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Handle every WorktreeCreate event (no matcher filtering)."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Create (or reuse) the worktree and return its absolute path."""
        cwd = str(hook_input.get(_KEY_CWD) or Path.cwd())
        name = hook_input.get(_KEY_NAME)
        prompt_id = hook_input.get(_KEY_PROMPT_ID)
        session_id = hook_input.get(_KEY_SESSION_ID)

        path = worktree_path(cwd, name, prompt_id, session_id)

        # Idempotent: a re-fired event for the same agent reuses the worktree.
        # Seeding runs only on FRESH creation; an existing worktree's links are
        # left exactly as they are.
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            branch = worktree_dir_name(name, prompt_id, session_id)
            self._git_worktree_add(cwd, path, branch)
            self._seed_files(cwd, path)

        return HookResult(worktree_path=str(path))

    @staticmethod
    def _git_worktree_add(cwd: str, path: Path, branch: str) -> None:
        """Run ``git worktree add -b <branch> <path>`` from ``cwd``.

        SECURITY: fixed argv, no shell, trusted ``git`` binary only. Fails LOUDLY
        (raises) rather than returning an empty response — an unusable path would
        re-introduce the original ``/<cwd>/{}`` breakage.
        """
        subprocess.run(  # nosec B603 B607 — fixed argv, no shell, trusted binary
            ["git", "-C", cwd, "worktree", "add", "-b", branch, str(path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=Timeout.GIT_WORKTREE,
        )

    def _seed_files(self, cwd: str, worktree: Path) -> None:
        """Symlink configured git-ignored local files into a fresh worktree.

        Files live only in the main working copy (they are git-ignored), so a
        worktree checkout lacks them. Each configured entry is resolved relative
        to the repository top-level and a symlink at the same relative location in
        the worktree is pointed back at it. A symlink (not a copy) keeps the main
        working copy as the single source of truth — no stale duplicate to
        reconcile.

        Best-effort by design: a missing source is skipped, an already-present
        destination is left untouched (never clobbered), and a symlink failure is
        logged (never silently swallowed) but does NOT break worktree creation —
        an unusable env file is far less harmful than a failed worktree launch.
        """
        if not self._symlink_files:
            return

        source_root = self._repo_toplevel(cwd)
        if source_root is None:
            return

        for entry in self._symlink_files:
            rel = Path(entry)
            # Reject absolute paths and parent-traversal so a symlink can never be
            # written outside the worktree root.
            if rel.is_absolute() or _PARENT_REF in rel.parts:
                logger.warning("worktree_create: ignoring unsafe symlink_files entry %r", entry)
                continue

            src = source_root / rel
            if not src.exists():
                continue

            dest = worktree / rel
            # Never clobber a destination that already exists (e.g. a tracked
            # file the checkout provided, or a link from a prior run).
            if dest.is_symlink() or dest.exists():
                continue

            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                # Absolute target so the link resolves regardless of the
                # worktree's own location under the repo.
                dest.symlink_to(src)
            except OSError as exc:
                logger.warning(
                    "worktree_create: failed to symlink %r into worktree: %s", entry, exc
                )

    @staticmethod
    def _repo_toplevel(cwd: str) -> Path | None:
        """Return the git top-level for ``cwd``, or None if it cannot be resolved.

        The main working copy's root is the symlink target root: env files live at
        the repo root, while ``cwd`` may be a subdirectory of it.
        """
        try:
            result = subprocess.run(  # nosec B603 B607 — fixed argv, no shell, trusted binary
                ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                check=True,
                capture_output=True,
                text=True,
                timeout=Timeout.GIT_WORKTREE,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("worktree_create: could not resolve repo top-level for seeding: %s", exc)
            return None

        top = result.stdout.strip()
        return Path(top) if top else None

    def get_claude_md(self) -> str | None:
        """Guidance injected into the project CLAUDE.md."""
        return (
            "## worktree_create — semantic worktree naming + env-file symlinking\n\n"
            'When Claude Code creates a worktree (an `isolation: "worktree"` agent '
            "or `--worktree` session), the daemon creates it at a human-friendly "
            "path `.claude/worktrees/<slug-of-name>-<shorthash>/` and echoes that "
            "path. Name an agent semantically (the Agent tool's `name:`) to get a "
            "readable worktree directory (e.g. `refactor-auth-4f2a1c9b`) instead of "
            "an opaque `wf_<hash>`. The short hash suffix keeps identically-named "
            "agents from colliding.\n\n"
            "On **fresh** creation the daemon also **symlinks** git-ignored local "
            "files from the repo top-level into the new worktree so it behaves like "
            "the main checkout — by default `.env.local` and `.env.test.local`. A "
            "symlink (not a copy) keeps the main working copy as the single source "
            "of truth: editing the canonical file is reflected in every worktree, "
            "with no stale duplicate. Configure the list via the `symlink_files` "
            "option under `handlers.worktree_create.worktree_create.options`. It is "
            "best-effort (a symlink failure is logged, never fatal), never clobbers "
            "an existing destination, and never runs on a re-fire."
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
