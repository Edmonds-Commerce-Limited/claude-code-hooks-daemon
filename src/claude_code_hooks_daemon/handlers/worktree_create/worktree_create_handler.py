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
import subprocess  # nosec B404 — CalledProcessError typing only; run_git owns the spawn
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import AdvisoryResult
from claude_code_hooks_daemon.core.handler_bases import WorktreeCreateHandlerBase
from claude_code_hooks_daemon.core.worktree_naming import worktree_dir_name, worktree_path
from claude_code_hooks_daemon.core.worktree_seed import (
    SEED_MODE_COPY,
    SEED_MODE_SYMLINK,
    SeedEntry,
    parse_seed_config,
)
from claude_code_hooks_daemon.utils.git_repo import GitRepo, run_git
from claude_code_hooks_daemon.utils.worktree_seeding import seed_worktree, validate_seed_sources

logger = logging.getLogger(__name__)

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
        # The registry applies handler options by ``setattr`` AFTER __init__, so
        # this holds raw YAML the daemon does not control and cannot be parsed
        # here — a narrower annotation would be a lie about what can arrive.
        # ``_resolved_seed`` memoises the validated form on first use.
        self._seed: Any = None
        self._resolved_seed: list[SeedEntry] | None = None

    def _seed_entries(self) -> list[SeedEntry]:
        """Return the validated seed entries, parsing the option once."""
        resolved = self._resolved_seed
        if resolved is None:
            resolved = parse_seed_config(self._seed)
            self._resolved_seed = resolved
        return resolved

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Handle every WorktreeCreate event (no matcher filtering)."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Create (or reuse) the worktree and return its absolute path."""
        cwd = str(hook_input.get(_KEY_CWD) or Path.cwd())
        name = hook_input.get(_KEY_NAME)
        prompt_id = hook_input.get(_KEY_PROMPT_ID)
        session_id = hook_input.get(_KEY_SESSION_ID)

        root = self._repo_root(cwd)
        path = worktree_path(root, name, prompt_id, session_id)

        # Idempotent: a re-fired event for the same agent reuses the worktree,
        # and deliberately does NOT re-seed — whatever the agent has done to
        # those files inside its worktree is its own.
        #
        # This checks the DIRECTORY, not git's worktree registry, so a stale
        # directory that is not a registered worktree is accepted and echoed
        # back as valid. Tightening it means reconciling against
        # ``git worktree list``, which is out of scope here (Plan 00267 T1.4).
        if not path.exists():
            entries = self._seed_entries()
            # BEFORE creation: an unusable entry must abandon the whole
            # operation rather than leave a worktree missing files its agent
            # cannot know are absent. Both calls no-op on an empty list.
            validate_seed_sources(Path(root), entries)

            path.parent.mkdir(parents=True, exist_ok=True)
            branch = worktree_dir_name(name, prompt_id, session_id)
            self._git_worktree_add(cwd, path, branch)

            seed_worktree(Path(root), path, entries)

        return AdvisoryResult(worktree_path=str(path))

    @staticmethod
    def _repo_root(cwd: str) -> str:
        """Return the repository root ``cwd`` sits in, else ``cwd`` unchanged.

        The worktree belongs to the REPOSITORY, not to whatever directory the
        session happened to be standing in. Anchoring to a raw ``cwd`` scatters
        worktrees into ``<subdir>/.claude/worktrees/`` — a session in ``src/``
        and one in ``docs/guides/`` of the same repo would not even share a
        worktrees directory (Plan 00267 Phase 1).

        Falling back to ``cwd`` when the root cannot be resolved is deliberate:
        that is precisely the pre-existing behaviour, so an environment where
        resolution fails is no worse off than before, and only the resolvable
        case changes. A genuinely non-repo ``cwd`` still fails loudly, because
        ``git worktree add`` refuses it either way.
        """
        repo = GitRepo.resolve_for(Path(cwd))
        if repo is None:
            logger.warning(
                "Could not resolve a git repository root for %s — anchoring the "
                "worktree to it directly, as before.",
                cwd,
            )
            return cwd
        return str(repo.root)

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
        """Guidance injected into the project CLAUDE.md.

        Guidance is collected from ACTIVE handlers, so this runs with the
        project's options already applied. The seeding section is therefore
        emitted only where seeding is configured: the write-through hazard is a
        real footgun for a project that uses it, and pure resident noise for one
        that does not.
        """
        return (
            "## worktree_create — semantic worktree naming\n\n"
            'When Claude Code creates a worktree (an `isolation: "worktree"` agent '
            "or `--worktree` session), the daemon creates it at a human-friendly "
            "path `.claude/worktrees/<slug-of-name>-<shorthash>/` and echoes that "
            "path. Name an agent semantically (the Agent tool's `name:`) to get a "
            "readable worktree directory (e.g. `refactor-auth-4f2a1c9b`) instead of "
            "an opaque `wf_<hash>`. The short hash suffix keeps identically-named "
            "agents from colliding." + self._seeding_guidance()
        )

    def _seeding_guidance(self) -> str:
        """Return the seeding section, or nothing when seeding is unconfigured."""
        entries = self._seed_entries()
        if not entries:
            return ""

        linked = [entry.path for entry in entries if entry.mode == SEED_MODE_SYMLINK]
        copied = [entry.path for entry in entries if entry.mode == SEED_MODE_COPY]

        lines = [
            "\n\n**A fresh worktree is a clean checkout**, so this project's "
            "git-ignored local files would be absent from it — an agent would "
            "silently run against a different configuration from the session that "
            "spawned it. The daemon seeds them on creation, and HOW it does so "
            "decides whether your edits inside a worktree are isolated:",
        ]

        if linked:
            lines.append(
                f"\n\n- **`{SEED_MODE_SYMLINK}` mode — shared, NOT isolated**: "
                + ", ".join(f"`{path}`" for path in linked)
                + ". These point at the main checkout, so editing one from inside "
                "a worktree changes the file every other session is using. Read "
                "them freely; treat writing to one as writing to the main "
                "checkout, because it is."
            )

        if copied:
            lines.append(
                f"\n\n- **`{SEED_MODE_COPY}` mode — copied, isolated, may go stale**: "
                + ", ".join(f"`{path}`" for path in copied)
                + ". Yours to edit — nothing flows back. The tradeoff is the other "
                "direction: a later change to the canonical file does not reach a "
                "worktree already created."
            )

        lines.append(
            "\n\nSeeding happens ONCE, at creation; a re-fired event never "
            "re-seeds over an agent's own edits. A configured path that has since "
            "disappeared ABORTS creation rather than handing you a quietly "
            "under-seeded worktree — run `bin/hooks-daemon check-worktree-seed` to "
            "see which entries are stale and which local files are not yet covered."
        )
        return "".join(lines)

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
