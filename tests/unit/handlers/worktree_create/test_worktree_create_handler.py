"""Tests for WorktreeCreateHandler (Plan 00188).

The handler owns Claude Code's WorktreeCreate hook: it creates a git worktree at
a human-friendly semantic path and returns that absolute path. Claude Code parses
the hook's stdout as the created path, so the response must be the real path (a
directory that exists) and must NEVER be an empty ``{}`` (the original bug, which
Claude Code took literally as ``/<cwd>/{}``).

Tests run against a real temporary git repo — faithful to the production path.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.core.worktree_seed import (
    SEED_MODE_COPY,
    SEED_MODE_SYMLINK,
    SeedEntry,
)
from claude_code_hooks_daemon.handlers.worktree_create.worktree_create_handler import (
    WorktreeCreateHandler,
)
from claude_code_hooks_daemon.utils.worktree_seeding import WorktreeSeedError


def _init_repo(root: Path) -> None:
    """Create a git repo with one commit so worktrees can branch from HEAD."""
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t.t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    (root / "README.md").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "init"], check=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    return root


class TestInitialisation:
    def test_registers_for_worktree_create_event(self) -> None:
        handler = WorktreeCreateHandler()
        assert handler.config_key == "worktree_create"

    def test_matches_all_worktree_create_events(self) -> None:
        handler = WorktreeCreateHandler()
        assert handler.matches({"hook_event_name": EventType.WORKTREE_CREATE.value}) is True


class TestHandle:
    def _input(self, repo: Path, name: str = "Refactor Auth") -> dict:
        return {
            "hook_event_name": EventType.WORKTREE_CREATE.value,
            "cwd": str(repo),
            "name": name,
            "prompt_id": "pid-123",
            "session_id": "sid-456",
        }

    def test_creates_worktree_directory(self, repo: Path) -> None:
        handler = WorktreeCreateHandler()
        result = handler.handle(self._input(repo))
        assert result.worktree_path is not None
        assert Path(result.worktree_path).is_dir()

    def test_path_is_semantic_and_absolute(self, repo: Path) -> None:
        handler = WorktreeCreateHandler()
        result = handler.handle(self._input(repo))
        path = Path(result.worktree_path or "")
        assert path.is_absolute()
        assert path.name.startswith("refactor-auth-")
        assert str(path).startswith(f"{repo}/.claude/worktrees/")

    def test_registers_a_real_git_worktree(self, repo: Path) -> None:
        handler = WorktreeCreateHandler()
        result = handler.handle(self._input(repo))
        listing = subprocess.run(
            ["git", "-C", str(repo), "worktree", "list"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert result.worktree_path in listing

    def test_response_json_is_worktree_path_not_braces(self, repo: Path) -> None:
        handler = WorktreeCreateHandler()
        result = handler.handle(self._input(repo))
        payload = result.to_json(EventType.WORKTREE_CREATE.value)
        assert payload == {"worktreePath": result.worktree_path}
        assert payload != {}
        assert "{}" not in str(payload["worktreePath"])

    def test_idempotent_on_refire(self, repo: Path) -> None:
        handler = WorktreeCreateHandler()
        first = handler.handle(self._input(repo))
        second = handler.handle(self._input(repo))
        assert first.worktree_path == second.worktree_path
        assert Path(second.worktree_path or "").is_dir()

    def test_returns_hook_result(self, repo: Path) -> None:
        handler = WorktreeCreateHandler()
        assert isinstance(handler.handle(self._input(repo)), HookResult)

    def test_unnamed_agent_falls_back_to_worktree_slug(self, repo: Path) -> None:
        handler = WorktreeCreateHandler()
        payload = self._input(repo, name="")
        result = handler.handle(payload)
        assert Path(result.worktree_path or "").name.startswith("worktree-")


class TestRepoRootResolution:
    """Plan 00267 Phase 1: anchor the worktree to the REPO ROOT, not to cwd.

    The handler took ``hook_input["cwd"]`` verbatim and never asked git where
    the repository root was. A session whose cwd is a subdirectory therefore
    got its worktrees under that subdirectory — ``<subdir>/.claude/worktrees/``
    — scattering them anywhere a session happened to be standing instead of
    collecting them at one predictable place per repo.

    Resolution failure deliberately falls back to the raw cwd: that is exactly
    today's behaviour, so a repo where the root cannot be resolved is no worse
    off than before, and only the resolvable case changes.
    """

    def _input(self, cwd: Path, name: str = "Refactor Auth") -> dict:
        return {
            "hook_event_name": EventType.WORKTREE_CREATE.value,
            "cwd": str(cwd),
            "name": name,
            "prompt_id": "pid-123",
            "session_id": "sid-456",
        }

    def test_subdirectory_cwd_anchors_worktree_at_repo_root(self, repo: Path) -> None:
        subdir = repo / "src" / "deep"
        subdir.mkdir(parents=True)

        handler = WorktreeCreateHandler()
        result = handler.handle(self._input(subdir))

        path = Path(result.worktree_path or "")
        assert str(path).startswith(f"{repo}/.claude/worktrees/")
        assert "deep" not in str(path.parent), f"worktree nested under the cwd: {path}"

    def test_subdirectory_cwd_registers_the_worktree_with_the_repo(self, repo: Path) -> None:
        subdir = repo / "src"
        subdir.mkdir()

        handler = WorktreeCreateHandler()
        result = handler.handle(self._input(subdir))

        listing = subprocess.run(
            ["git", "-C", str(repo), "worktree", "list"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert result.worktree_path in listing

    def test_repo_root_cwd_is_unchanged(self, repo: Path) -> None:
        """Regression guard: the already-correct case must not move."""
        handler = WorktreeCreateHandler()
        result = handler.handle(self._input(repo))
        assert str(Path(result.worktree_path or "")).startswith(f"{repo}/.claude/worktrees/")

    def test_two_subdirectories_share_one_worktrees_directory(self, repo: Path) -> None:
        """The point of anchoring: placement stops depending on where you stood."""
        first = repo / "src"
        second = repo / "docs" / "guides"
        first.mkdir()
        second.mkdir(parents=True)

        handler = WorktreeCreateHandler()
        a = handler.handle(self._input(first, name="alpha"))
        b = handler.handle(self._input(second, name="beta"))

        assert Path(a.worktree_path or "").parent == Path(b.worktree_path or "").parent

    def test_non_repo_cwd_still_fails_loudly(self, tmp_path: Path) -> None:
        """Unresolvable root falls back to cwd, so git still refuses — loudly."""
        outside = tmp_path / "not-a-repo"
        outside.mkdir()

        handler = WorktreeCreateHandler()
        with pytest.raises(subprocess.CalledProcessError):
            handler.handle(self._input(outside))


class TestSeedOptionPlumbing:
    """Plan 00267 Phase 2: the ``seed`` option is parsed LAZILY.

    The registry applies handler options by ``setattr`` *after* ``__init__``,
    so a constructor that parsed its options would always parse the default and
    never the project's configuration. These tests pin that the parse happens
    on first use and is memoised thereafter.
    """

    def test_unconfigured_handler_has_no_seed_entries(self) -> None:
        assert WorktreeCreateHandler()._seed_entries() == []

    def test_option_applied_after_init_is_honoured(self) -> None:
        handler = WorktreeCreateHandler()
        # Exactly how the registry delivers it: setattr onto the private name.
        handler._seed = {"entries": [".env.local"]}

        assert handler._seed_entries() == [SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK)]

    def test_per_entry_mode_survives_the_plumbing(self) -> None:
        handler = WorktreeCreateHandler()
        handler._seed = {
            "default_mode": SEED_MODE_SYMLINK,
            "entries": [".env.local", {"path": ".secrets", "mode": SEED_MODE_COPY}],
        }

        assert handler._seed_entries() == [
            SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK),
            SeedEntry(path=".secrets", mode=SEED_MODE_COPY),
        ]

    def test_parse_is_memoised(self) -> None:
        handler = WorktreeCreateHandler()
        handler._seed = {"entries": [".env.local"]}
        first = handler._seed_entries()

        # A later mutation is NOT re-read: the option is parsed once per
        # handler instance, matching the house lazy-memo idiom.
        handler._seed = {"entries": [".other"]}
        assert handler._seed_entries() is first

    def test_malformed_option_degrades_rather_than_raising(self) -> None:
        handler = WorktreeCreateHandler()
        handler._seed = ".env.local"  # the bare-string mistake
        assert handler._seed_entries() == []


class TestSeedingOnCreate:
    """Plan 00267 Phase 3: seeding is wired into creation, and fails before it."""

    def _input(self, cwd: Path, name: str = "Refactor Auth") -> dict:
        return {
            "hook_event_name": EventType.WORKTREE_CREATE.value,
            "cwd": str(cwd),
            "name": name,
            "prompt_id": "pid-123",
            "session_id": "sid-456",
        }

    def test_configured_entries_are_seeded_into_a_fresh_worktree(self, repo: Path) -> None:
        (repo / ".env.local").write_text("SECRET=canonical\n", encoding="utf-8")

        handler = WorktreeCreateHandler()
        handler._seed = {"entries": [".env.local"]}
        result = handler.handle(self._input(repo))

        seeded = Path(result.worktree_path or "") / ".env.local"
        assert seeded.is_symlink()
        assert seeded.read_text(encoding="utf-8") == "SECRET=canonical\n"

    def test_copy_mode_is_honoured_end_to_end(self, repo: Path) -> None:
        (repo / ".env.local").write_text("SECRET=canonical\n", encoding="utf-8")

        handler = WorktreeCreateHandler()
        handler._seed = {"entries": [{"path": ".env.local", "mode": SEED_MODE_COPY}]}
        result = handler.handle(self._input(repo))

        seeded = Path(result.worktree_path or "") / ".env.local"
        assert not seeded.is_symlink()
        assert seeded.read_text(encoding="utf-8") == "SECRET=canonical\n"

    def test_unconfigured_creation_seeds_nothing_and_still_works(self, repo: Path) -> None:
        handler = WorktreeCreateHandler()
        result = handler.handle(self._input(repo))
        assert Path(result.worktree_path or "").is_dir()

    def test_an_unusable_entry_aborts_before_the_worktree_is_created(self, repo: Path) -> None:
        """No partial state: the directory must not exist after the failure."""
        handler = WorktreeCreateHandler()
        handler._seed = {"entries": [".env.missing"]}

        with pytest.raises(WorktreeSeedError, match=r"\.env\.missing"):
            handler.handle(self._input(repo))

        worktrees = repo / ".claude" / "worktrees"
        assert not worktrees.exists() or not any(worktrees.iterdir())

    def test_refire_does_not_reseed_over_the_agents_own_edits(self, repo: Path) -> None:
        (repo / ".env.local").write_text("SECRET=canonical\n", encoding="utf-8")

        handler = WorktreeCreateHandler()
        handler._seed = {"entries": [{"path": ".env.local", "mode": SEED_MODE_COPY}]}
        first = handler.handle(self._input(repo))

        seeded = Path(first.worktree_path or "") / ".env.local"
        seeded.write_text("SECRET=agent-edited\n", encoding="utf-8")

        handler.handle(self._input(repo))

        assert seeded.read_text(encoding="utf-8") == "SECRET=agent-edited\n"


class TestSeedingGuidance:
    """Plan 00267 Phase 6: the resident guidance tracks the live config.

    Guidance is collected from ACTIVE handlers, so it is built after options
    are applied. That makes the seeding hazard statable only where it is real:
    a project with no seed entries pays no resident context for a footgun it
    cannot hit, and a project with them is told before it hits one.
    """

    def test_naming_guidance_is_always_present(self) -> None:
        guidance = WorktreeCreateHandler().get_claude_md() or ""

        assert "worktree_create" in guidance
        assert "semantic" in guidance.lower()

    def test_unconfigured_handler_says_nothing_about_seeding(self) -> None:
        guidance = WorktreeCreateHandler().get_claude_md() or ""

        assert "seed" not in guidance.lower()

    def test_symlink_write_through_hazard_is_stated_when_configured(self) -> None:
        handler = WorktreeCreateHandler()
        handler._seed = {"entries": [".env.local"]}

        guidance = handler.get_claude_md() or ""

        assert ".env.local" in guidance
        # The hazard an agent can actually trip: an edit inside the worktree is
        # NOT isolated, it lands in the main checkout.
        assert "symlink" in guidance.lower()
        assert "main checkout" in guidance.lower()

    def test_copy_drift_hazard_is_stated_when_a_copy_entry_is_configured(self) -> None:
        handler = WorktreeCreateHandler()
        handler._seed = {"entries": [{"path": ".secrets", "mode": SEED_MODE_COPY}]}

        guidance = handler.get_claude_md() or ""

        assert ".secrets" in guidance
        assert "copy" in guidance.lower()

    def test_guidance_names_the_reporting_command(self) -> None:
        handler = WorktreeCreateHandler()
        handler._seed = {"entries": [".env.local"]}

        assert "check-worktree-seed" in (handler.get_claude_md() or "")
