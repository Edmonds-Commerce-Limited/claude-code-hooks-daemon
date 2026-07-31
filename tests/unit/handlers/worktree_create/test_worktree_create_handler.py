"""Tests for WorktreeCreateHandler (Plan 00188).

The handler owns Claude Code's WorktreeCreate hook: it creates a git worktree at
a human-friendly semantic path and returns that absolute path. Claude Code parses
the hook's stdout as the created path, so the response must be the real path (a
directory that exists) and must NEVER be an empty ``{}`` (the original bug, which
Claude Code took literally as ``/<cwd>/{}``).

Tests run against a real temporary git repo — faithful to the production path.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.handlers.worktree_create.worktree_create_handler import (
    RECOMMENDED_WORKTREE_SYMLINK_FILES,
    WorktreeCreateHandler,
    WorktreeSeedError,
)


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


class TestEnvFileSeeding:
    """Worktrees SYMLINK opt-in git-ignored files from the repo top-level.

    Symlinking is OPT-IN (``symlink_files`` defaults to empty) and FAIL-FAST:
    every configured entry must resolve to a file at the repo root, else worktree
    creation raises before anything is created. A symlink (not a copy) keeps the
    main working copy as the single source of truth. Fixtures use dummy content
    only — never real secrets.
    """

    def _input(self, repo: Path, name: str = "Seed Env") -> dict:
        return {
            "hook_event_name": EventType.WORKTREE_CREATE.value,
            "cwd": str(repo),
            "name": name,
            "prompt_id": "pid-seed",
            "session_id": "sid-seed",
        }

    def test_unconfigured_is_noop_even_without_env_files(self, repo: Path) -> None:
        # Default (empty symlink_files): worktree is created, nothing is linked,
        # and NO error even though the repo has no env files. Opt-in safety.
        handler = WorktreeCreateHandler()
        result = handler.handle(self._input(repo))
        worktree = Path(result.worktree_path or "")

        assert worktree.is_dir()
        for fname in RECOMMENDED_WORKTREE_SYMLINK_FILES:
            assert not (worktree / fname).exists()

    def test_configured_files_symlinked_into_worktree(self, repo: Path) -> None:
        for fname in RECOMMENDED_WORKTREE_SYMLINK_FILES:
            (repo / fname).write_text(f"SEED={fname}\n", encoding="utf-8")

        handler = WorktreeCreateHandler()
        handler._symlink_files = list(RECOMMENDED_WORKTREE_SYMLINK_FILES)
        result = handler.handle(self._input(repo))
        worktree = Path(result.worktree_path or "")

        for fname in RECOMMENDED_WORKTREE_SYMLINK_FILES:
            link = worktree / fname
            assert link.is_symlink(), f"{fname} should be a symlink in the worktree"
            assert link.resolve() == (repo / fname).resolve()
            assert link.read_text(encoding="utf-8") == f"SEED={fname}\n"

    def test_symlink_reflects_source_edits_single_source_of_truth(self, repo: Path) -> None:
        fname = RECOMMENDED_WORKTREE_SYMLINK_FILES[0]
        (repo / fname).write_text("SEED=original\n", encoding="utf-8")

        handler = WorktreeCreateHandler()
        handler._symlink_files = [fname]
        result = handler.handle(self._input(repo))
        worktree = Path(result.worktree_path or "")

        # Editing the canonical file is seen through the worktree link — proving
        # it is a live symlink (single source of truth), not a copy.
        (repo / fname).write_text("SEED=updated-in-main\n", encoding="utf-8")
        assert (worktree / fname).read_text(encoding="utf-8") == "SEED=updated-in-main\n"

    def test_missing_configured_file_fails_fast_before_creation(self, repo: Path) -> None:
        # One configured file is absent → WorktreeSeedError, and NO worktree is
        # created (validation happens before git worktree add — no partial state).
        present = RECOMMENDED_WORKTREE_SYMLINK_FILES[0]
        (repo / present).write_text("SEED=present\n", encoding="utf-8")

        handler = WorktreeCreateHandler()
        handler._symlink_files = list(RECOMMENDED_WORKTREE_SYMLINK_FILES)

        with pytest.raises(WorktreeSeedError):
            handler.handle(self._input(repo))

        assert not (repo / ".claude" / "worktrees").exists()

    def test_no_reseed_on_idempotent_refire(self, repo: Path) -> None:
        fname = RECOMMENDED_WORKTREE_SYMLINK_FILES[0]
        (repo / fname).write_text("SEED=original\n", encoding="utf-8")

        handler = WorktreeCreateHandler()
        handler._symlink_files = [fname]
        first = handler.handle(self._input(repo))
        worktree = Path(first.worktree_path or "")

        # Remove the link inside the existing worktree.
        (worktree / fname).unlink()

        # A re-fired event reuses the existing worktree and does NOT re-seed —
        # seeding is fresh-creation only.
        handler.handle(self._input(repo))
        assert not (worktree / fname).exists()
        assert not (worktree / fname).is_symlink()

    def test_only_configured_entries_are_linked(self, repo: Path) -> None:
        (repo / "custom.env").write_text("SEED=custom\n", encoding="utf-8")
        (repo / ".env.local").write_text("SEED=not-configured\n", encoding="utf-8")

        handler = WorktreeCreateHandler()
        handler._symlink_files = ["custom.env"]
        result = handler.handle(self._input(repo))
        worktree = Path(result.worktree_path or "")

        assert (worktree / "custom.env").is_symlink()
        # A file present at the root but NOT configured is not linked.
        assert not (worktree / ".env.local").exists()

    def test_unsafe_configured_entry_raises(self, repo: Path, tmp_path: Path) -> None:
        outside = tmp_path / "outside-secret.env"
        outside.write_text("SEED=outside\n", encoding="utf-8")

        handler = WorktreeCreateHandler()
        handler._symlink_files = ["../outside-secret.env"]
        with pytest.raises(WorktreeSeedError):
            handler.handle(self._input(repo))
        assert not (repo / ".claude" / "worktrees").exists()

        handler._symlink_files = [str(outside)]  # absolute path
        with pytest.raises(WorktreeSeedError):
            handler.handle(self._input(repo))
        assert not (repo / ".claude" / "worktrees").exists()

    def test_directory_source_raises(self, repo: Path) -> None:
        # A directory source is a configuration error (Non-Goal: no directory
        # linking) — fail fast, not silent skip.
        (repo / "confdir").mkdir()
        (repo / "confdir" / "inner").write_text("SEED=inner\n", encoding="utf-8")

        handler = WorktreeCreateHandler()
        handler._symlink_files = ["confdir"]
        with pytest.raises(WorktreeSeedError):
            handler.handle(self._input(repo))
        assert not (repo / ".claude" / "worktrees").exists()

    def test_existing_destination_is_not_clobbered(self, tmp_path: Path) -> None:
        # A destination that already exists (e.g. a tracked file) must be left as
        # is — never replaced by a symlink.
        source_root = tmp_path / "main"
        source_root.mkdir()
        (source_root / ".env.local").write_text("SEED=canonical\n", encoding="utf-8")

        worktree = tmp_path / "wt"
        worktree.mkdir()
        (worktree / ".env.local").write_text("SEED=pre-existing\n", encoding="utf-8")

        handler = WorktreeCreateHandler()
        plan = [(source_root / ".env.local", Path(".env.local"))]
        handler._apply_symlinks(worktree, plan)

        dest = worktree / ".env.local"
        assert not dest.is_symlink()
        assert dest.read_text(encoding="utf-8") == "SEED=pre-existing\n"

    def test_link_is_relative_and_survives_tree_relocation(
        self, repo: Path, tmp_path: Path
    ) -> None:
        # The link target MUST be relative so it keeps resolving when the same
        # on-disk tree is viewed at a different absolute prefix (host <-> container
        # bind-mount). An absolute target would dangle across that remap.
        fname = RECOMMENDED_WORKTREE_SYMLINK_FILES[0]
        (repo / fname).write_text("SEED=canonical\n", encoding="utf-8")

        handler = WorktreeCreateHandler()
        handler._symlink_files = [fname]
        result = handler.handle(self._input(repo))
        worktree = Path(result.worktree_path or "")
        link = worktree / fname

        target = link.readlink()
        assert not target.is_absolute(), f"link target must be relative, got {target!r}"

        # Relocate the identical tree to a new prefix (preserving symlinks) and
        # confirm the link still resolves there — to the RELOCATED canonical file,
        # not back to the original prefix.
        relocated = tmp_path / "relocated"
        shutil.copytree(repo, relocated, symlinks=True)
        relocated_link = relocated / worktree.relative_to(repo) / fname
        assert relocated_link.read_text(encoding="utf-8") == "SEED=canonical\n"
        assert relocated_link.resolve() == (relocated / fname).resolve()

    def test_string_symlink_files_config_is_coerced_to_list(self, repo: Path) -> None:
        # A common YAML slip: `symlink_files: ".env.local"` (a string, not a list).
        # It must be coerced to a single-entry list, not iterated character by
        # character into a silent no-op.
        (repo / ".env.local").write_text("SEED=canonical\n", encoding="utf-8")

        handler = WorktreeCreateHandler()
        handler._symlink_files = ".env.local"  # type: ignore[assignment]
        result = handler.handle(self._input(repo))
        worktree = Path(result.worktree_path or "")

        assert (worktree / ".env.local").is_symlink()
        assert (worktree / ".env.local").read_text(encoding="utf-8") == "SEED=canonical\n"

    def test_symlink_syscall_failure_propagates(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A symlink syscall failure (source validated, but the call fails) must
        # propagate loudly — fail-fast, not swallowed.
        (repo / ".env.local").write_text("SEED=canonical\n", encoding="utf-8")

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise OSError("symlink not permitted")

        monkeypatch.setattr(Path, "symlink_to", _boom)

        handler = WorktreeCreateHandler()
        handler._symlink_files = [".env.local"]
        with pytest.raises(OSError, match="symlink not permitted"):
            handler.handle(self._input(repo))
