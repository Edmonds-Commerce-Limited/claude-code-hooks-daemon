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
import os
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

# Recommended value for the ``symlink_files`` option (Plan 00191). Symlinking is
# OPT-IN: the option defaults to empty so a project that does not configure it is
# never affected, and — because the process fails fast (see below) — a repo that
# simply lacks these files is never broken. A project that wants worktrees to
# behave like the main checkout sets ``symlink_files: [.env.local,
# .env.test.local]`` (these git-ignored files live only in the developer's
# checkout, so a worktree would otherwise lack them). A symlink (not a copy) keeps
# the main working copy as the single source of truth.
RECOMMENDED_WORKTREE_SYMLINK_FILES: tuple[str, ...] = (".env.local", ".env.test.local")

# Parent-directory reference — an entry containing this component is rejected so a
# symlink can never be written outside the worktree root.
_PARENT_REF = ".."


class WorktreeSeedError(RuntimeError):
    """A configured ``symlink_files`` entry could not be honoured.

    Raised (fail-fast, loud) when an explicitly-configured path is unsafe, is
    absent at the repo root, or is not a regular file — aborting worktree
    creation rather than silently producing a worktree missing its expected
    files. Symlinking is opt-in, so this only ever fires for paths the project
    deliberately listed.
    """


class WorktreeCreateHandler(Handler):
    """Create a git worktree at a semantic path and return its absolute path."""

    def __init__(self) -> None:
        super().__init__(
            HandlerID.WORKTREE_CREATE,
            priority=_WORKTREE_CREATE_PRIORITY,
            terminal=True,
        )
        # Files symlinked into a fresh worktree. OPT-IN: empty by default; the
        # registry overrides it from the ``symlink_files`` handler option
        # (Plan 00191) via setattr. Every configured entry MUST resolve to a file
        # at the repo root or worktree creation fails loudly (see _plan_symlinks).
        self._symlink_files: list[str] = []

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
            # Validate configured symlink sources BEFORE creating anything, so a
            # missing/unsafe entry fails fast and loud with no partial worktree
            # left behind (_plan_symlinks raises WorktreeSeedError).
            plan = self._plan_symlinks(cwd)
            path.parent.mkdir(parents=True, exist_ok=True)
            branch = worktree_dir_name(name, prompt_id, session_id)
            self._git_worktree_add(cwd, path, branch)
            self._apply_symlinks(path, plan)

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

    def _plan_symlinks(self, cwd: str) -> list[tuple[Path, Path]]:
        """Validate the configured entries and return ``(src, rel)`` pairs to link.

        Symlinking is opt-in and STRICT: every configured entry must be safe (no
        absolute path, no ``..``), present at the repo top-level, and a regular
        file. Any violation raises :class:`WorktreeSeedError` — fail-fast and
        loud, BEFORE the worktree is created, so a misconfiguration never yields a
        worktree silently missing its expected files. An empty/unconfigured option
        returns an empty plan (no-op).
        """
        entries = self._normalised_symlink_files()
        if not entries:
            return []

        source_root = self._repo_toplevel(cwd)
        plan: list[tuple[Path, Path]] = []
        for entry in entries:
            rel = Path(entry)
            # Reject absolute paths and parent-traversal so the symlink is never
            # written outside the worktree root.
            if rel.is_absolute() or _PARENT_REF in rel.parts:
                raise WorktreeSeedError(
                    f"worktree_create: unsafe symlink_files entry {entry!r} "
                    "(absolute path or parent-directory traversal)"
                )

            src = source_root / rel
            # Only individual files are linked (see the plan's Non-Goals): a
            # directory or a missing source is a configuration error, not a
            # silent skip.
            if not src.is_file():
                raise WorktreeSeedError(
                    f"worktree_create: symlink_files entry {entry!r} is not a file at "
                    f"repo root {source_root} — create it or remove it from symlink_files"
                )
            plan.append((src, rel))
        return plan

    def _apply_symlinks(self, worktree: Path, plan: list[tuple[Path, Path]]) -> None:
        """Create the planned symlinks inside a freshly-created ``worktree``.

        Sources were validated by :meth:`_plan_symlinks`. A destination that
        already exists is left untouched (never clobbered); it is not an error.
        A symlink syscall failure propagates (fail-fast) rather than being
        swallowed.
        """
        for src, rel in plan:
            dest = worktree / rel
            # Never clobber a destination that already exists (e.g. a tracked file
            # the checkout provided, or a link from a prior run).
            if dest.is_symlink() or dest.exists():
                continue

            dest.parent.mkdir(parents=True, exist_ok=True)
            # RELATIVE target so the link keeps resolving when the identical
            # on-disk tree is viewed at a different absolute prefix — e.g. a
            # container bind-mount (``/workspace``) versus the host path. An
            # absolute target would dangle across that host<->container view
            # divergence, which this project explicitly supports.
            dest.symlink_to(os.path.relpath(src, dest.parent))

    def _normalised_symlink_files(self) -> list[str]:
        """Return the configured entries, tolerating a bare-string ``symlink_files``.

        The registry applies the option verbatim via ``setattr`` with no
        validation, so a common YAML slip — ``symlink_files: ".env.local"`` (a
        string instead of a list) — would otherwise be iterated character by
        character and silently link nothing. Coerce a string to a single-entry
        list (do what the author meant); reject any other non-list value with a
        warning rather than failing silently.
        """
        raw: object = self._symlink_files
        if isinstance(raw, str):
            return [raw]
        if isinstance(raw, (list, tuple)):
            return [str(item) for item in raw]
        logger.warning(
            "worktree_create: symlink_files must be a list of paths, got %s; skipping",
            type(raw).__name__,
        )
        return []

    @staticmethod
    def _repo_toplevel(cwd: str) -> Path:
        """Return the git top-level for ``cwd`` (the symlink target root).

        Env files live at the repo root, while ``cwd`` may be a subdirectory of
        it. Raises :class:`WorktreeSeedError` (fail-fast) if the top-level cannot
        be resolved — this is only ever called once ``symlink_files`` is
        configured, so an unresolvable root is a real, loud error.
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
            raise WorktreeSeedError(
                f"worktree_create: symlink_files is configured but the git top-level "
                f"for {cwd!r} could not be resolved: {exc}"
            ) from exc

        top = result.stdout.strip()
        if not top:
            raise WorktreeSeedError(
                f"worktree_create: git rev-parse --show-toplevel returned no path for {cwd!r}"
            )
        return Path(top)

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
            "On **fresh** creation the daemon can also **symlink** git-ignored "
            "local files from the repo top-level into the new worktree so it "
            "behaves like the main checkout. This is **opt-in**: set "
            "`symlink_files` under "
            "`handlers.worktree_create.worktree_create.options` (recommended: "
            "`.env.local`, `.env.test.local`). A symlink (not a copy) keeps the "
            "main working copy as the single source of truth — editing the "
            "canonical file is reflected in every worktree — and note the "
            "corollary: an edit made to the file **inside** a worktree writes "
            "through to the main checkout. The process is **fail-fast**: every "
            "configured entry must resolve to a file at the repo root, else "
            "worktree creation fails loudly (create the file or remove it from "
            "`symlink_files`). It never clobbers an existing destination and never "
            "runs on a re-fire."
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
