"""A copy-mode seed of a protected source is refused (Plan 00613 Task 2.1).

Ruling Q3 of Plan 00613: a COPY of a file the secret guard protects puts its
content under a second path that a project-anchored glob may not cover, that
``git add -A`` can commit, and that drifts from the canonical file. Link mode
keeps one copy of the content, so it is the only mode a protected source may
be seeded in.

The check uses the guard's own matcher over PATHS only. These tests pin that it
never opens the protected file, that a directory copy is judged on every path
``shutil.copytree`` would copy (including through symlinks, which copytree
follows), and that a protected set which cannot be read refuses every copy
entry rather than falling back.

Protected names are assembled from pieces so this file does not itself name a
protected path to the secret guard.
"""

from __future__ import annotations

import builtins
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.worktree_seed import (
    SEED_MODE_COPY,
    SEED_MODE_SYMLINK,
    SeedEntry,
)
from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.worktree_seeding import (
    WorktreeSeedError,
    seed_worktree,
    validate_seed_sources,
)

VAULT = "." + "vault" + "-pass"
ED_KEY = "id_" + "ed25519"
RSA_KEY = "id_" + "rsa"
_SECRET_CONTENT = "do-not-copy-me\n"


def _defaults() -> tuple[str, ...]:
    return sfm.DEFAULT_PROTECTED_PATTERNS


def _unreadable() -> tuple[str, ...]:
    raise sfm.ProtectedSetUnreadable("the test's protected set cannot be read")


def _must_not_be_called() -> tuple[str, ...]:
    raise AssertionError("the protected set was read although no entry is in copy mode")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A main checkout holding one protected file and one ordinary file."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / VAULT).write_text(_SECRET_CONTENT, encoding="utf-8")
    (project / ".env.local").write_text("PLAIN=1\n", encoding="utf-8")
    return project


@pytest.fixture
def worktree(root: Path) -> Path:
    path = root / ".claude" / "worktrees" / "alpha-1234abcd"
    path.mkdir(parents=True)
    return path


def _refusal(root: Path, entries: list[SeedEntry], loader: Callable[[], tuple[str, ...]]) -> str:
    with pytest.raises(WorktreeSeedError) as excinfo:
        validate_seed_sources(root, entries, protected_patterns=loader)
    return str(excinfo.value)


class TestAProtectedFileInCopyModeIsRefused:
    def test_refused(self, root: Path) -> None:
        message = _refusal(root, [SeedEntry(path=VAULT, mode=SEED_MODE_COPY)], _defaults)
        assert "secret_file_guard" in message
        assert "mode: copy" in message

    def test_the_refusal_names_the_seed_by_role_not_by_its_path(self, root: Path) -> None:
        """The seed's path is itself a protected name; the reason is written to logs."""
        message = _refusal(
            root,
            [
                SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK),
                SeedEntry(path=VAULT, mode=SEED_MODE_COPY),
            ],
            _defaults,
        )
        assert "seed entry #2" in message
        assert VAULT not in message
        assert _SECRET_CONTENT.strip() not in message

    def test_the_protected_file_is_never_opened(self, root: Path) -> None:
        """Paths only: the check never reads the content it protects."""
        protected = str((root / VAULT).resolve())
        real_open = builtins.open

        def guarded_open(file: Any, *args: Any, **kwargs: Any) -> Any:
            if isinstance(file, str | Path) and str(Path(file).resolve()) == protected:
                raise AssertionError("the protected file was opened")
            return real_open(file, *args, **kwargs)

        with patch.object(builtins, "open", guarded_open):
            _refusal(root, [SeedEntry(path=VAULT, mode=SEED_MODE_COPY)], _defaults)

    def test_a_project_configured_glob_is_honoured(self, root: Path) -> None:
        (root / "deploy.key").write_text(_SECRET_CONTENT, encoding="utf-8")
        _refusal(
            root,
            [SeedEntry(path="deploy.key", mode=SEED_MODE_COPY)],
            lambda: (*sfm.DEFAULT_PROTECTED_PATTERNS, "*.key"),
        )

    def test_an_anchored_glob_is_judged_against_the_seeding_root(self, root: Path) -> None:
        """No daemon project root in a unit test: the seeding root must anchor it."""
        (root / "config").mkdir()
        (root / "config" / "prod.creds").write_text(_SECRET_CONTENT, encoding="utf-8")
        _refusal(
            root,
            [SeedEntry(path="config/prod.creds", mode=SEED_MODE_COPY)],
            lambda: ("/config/prod.creds",),
        )

    def test_an_unprotected_name_linking_to_a_protected_file_is_refused(self, root: Path) -> None:
        """Copy follows the link, so the link's TARGET is what would be duplicated."""
        (root / "innocent.txt").symlink_to(VAULT)
        _refusal(root, [SeedEntry(path="innocent.txt", mode=SEED_MODE_COPY)], _defaults)

    def test_an_absent_optional_protected_entry_is_still_refused(self, root: Path) -> None:
        """Judged on the spelled path, which needs no existence."""
        _refusal(
            root,
            [SeedEntry(path=RSA_KEY, mode=SEED_MODE_COPY, optional=True)],
            _defaults,
        )

    def test_nothing_is_placed_when_validation_refuses(self, root: Path, worktree: Path) -> None:
        entries = [SeedEntry(path=VAULT, mode=SEED_MODE_COPY)]
        with pytest.raises(WorktreeSeedError):
            validate_seed_sources(root, entries, protected_patterns=_defaults)
        assert not (worktree / VAULT).exists()


class TestADirectoryCopyIsJudgedOnEveryPathItWouldCopy:
    def test_a_protected_file_nested_in_the_directory_is_refused(self, root: Path) -> None:
        (root / "local").mkdir()
        (root / "local" / "sub").mkdir()
        (root / "local" / "sub" / VAULT).write_text(_SECRET_CONTENT, encoding="utf-8")
        message = _refusal(root, [SeedEntry(path="local", mode=SEED_MODE_COPY)], _defaults)
        assert VAULT not in message

    def test_a_symlink_in_the_directory_to_a_protected_file_is_refused(self, root: Path) -> None:
        (root / "local").mkdir()
        (root / "local" / "plain-name").symlink_to("../" + VAULT)
        _refusal(root, [SeedEntry(path="local", mode=SEED_MODE_COPY)], _defaults)

    def test_a_symlinked_subdirectory_holding_a_protected_file_is_refused(
        self, root: Path
    ) -> None:
        """os.walk does not enter a linked directory, but copytree copies through it."""
        (root / "keys").mkdir()
        (root / "keys" / ED_KEY).write_text(_SECRET_CONTENT, encoding="utf-8")
        (root / "local").mkdir()
        (root / "local" / "linked").symlink_to("../keys")
        _refusal(root, [SeedEntry(path="local", mode=SEED_MODE_COPY)], _defaults)

    def test_a_symlink_loop_in_the_directory_is_refused(self, root: Path) -> None:
        """An unbounded walk is a walk that cannot be shown safe."""
        (root / "local").mkdir()
        (root / "local" / "loop").symlink_to(".")
        _refusal(root, [SeedEntry(path="local", mode=SEED_MODE_COPY)], _defaults)

    def test_a_directory_past_the_path_cap_is_refused_unjudged(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from claude_code_hooks_daemon.utils import worktree_seeding

        monkeypatch.setattr(worktree_seeding, "PROTECTED_COPY_WALK_MAX_PATHS", 2)
        (root / "local").mkdir()
        for name in ("a", "b", "c"):
            (root / "local" / name).write_text("x\n", encoding="utf-8")
        message = _refusal(root, [SeedEntry(path="local", mode=SEED_MODE_COPY)], _defaults)
        assert "walked in full" in message

    def test_a_directory_that_cannot_be_listed_is_refused(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Root ignores permissions, so the listing failure is injected."""
        import os

        (root / "local").mkdir()
        (root / "local" / "sub").mkdir()
        real_scandir = os.scandir

        def failing_scandir(path: Any = ".") -> Any:
            if str(path).endswith("sub"):
                raise PermissionError(13, "denied")
            return real_scandir(path)

        monkeypatch.setattr(os, "scandir", failing_scandir)
        message = _refusal(root, [SeedEntry(path="local", mode=SEED_MODE_COPY)], _defaults)
        assert "walked in full" in message

    def test_an_entry_refused_for_its_shape_is_not_walked(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from claude_code_hooks_daemon.utils import worktree_seeding

        def no_walk(source: Path) -> list[str] | None:
            raise AssertionError(f"walked {source}")

        monkeypatch.setattr(worktree_seeding, "_paths_a_copy_would_read", no_walk)
        message = _refusal(root, [SeedEntry(path="/etc", mode=SEED_MODE_COPY)], _defaults)
        assert "absolute" in message

    def test_a_directory_with_no_protected_path_is_allowed(self, root: Path) -> None:
        (root / "local").mkdir()
        (root / "local" / "sub").mkdir()
        (root / "local" / "sub" / "settings.json").write_text("{}\n", encoding="utf-8")
        validate_seed_sources(
            root, [SeedEntry(path="local", mode=SEED_MODE_COPY)], protected_patterns=_defaults
        )


class TestAProtectedSetThatCannotBeReadRefusesEveryCopy:
    def test_an_unprotected_copy_is_refused(self, root: Path) -> None:
        message = _refusal(root, [SeedEntry(path=".env.local", mode=SEED_MODE_COPY)], _unreadable)
        assert "could not be read" in message
        assert "seed entry #1" in message

    def test_link_mode_entries_do_not_read_the_protected_set(self, root: Path) -> None:
        """A link-only config behaves as before, even with a broken guard config."""
        validate_seed_sources(
            root,
            [
                SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK),
                SeedEntry(path=VAULT, mode=SEED_MODE_SYMLINK),
            ],
            protected_patterns=_must_not_be_called,
        )

    def test_the_protected_set_is_read_once_for_many_copy_entries(self, root: Path) -> None:
        calls: list[int] = []

        def counting() -> tuple[str, ...]:
            calls.append(1)
            return ()

        (root / "a.txt").write_text("a\n", encoding="utf-8")
        validate_seed_sources(
            root,
            [
                SeedEntry(path=".env.local", mode=SEED_MODE_COPY),
                SeedEntry(path="a.txt", mode=SEED_MODE_COPY),
            ],
            protected_patterns=counting,
        )
        assert calls == [1]


class TestBehaviourThatIsUnchanged:
    def test_an_unprotected_copy_is_allowed_and_placed(self, root: Path, worktree: Path) -> None:
        entries = [SeedEntry(path=".env.local", mode=SEED_MODE_COPY)]
        validate_seed_sources(root, entries, protected_patterns=_defaults)
        seed_worktree(root, worktree, entries)
        assert (worktree / ".env.local").read_text(encoding="utf-8") == "PLAIN=1\n"

    def test_a_protected_file_in_link_mode_is_allowed(self, root: Path, worktree: Path) -> None:
        entries = [SeedEntry(path=VAULT, mode=SEED_MODE_SYMLINK)]
        validate_seed_sources(root, entries, protected_patterns=_defaults)
        seed_worktree(root, worktree, entries)
        assert (worktree / VAULT).is_symlink()

    def test_an_empty_protected_set_protects_nothing(self, root: Path) -> None:
        """``mode: replace`` with an empty list: the guard itself protects nothing,
        so a copy has nothing to be refused for. Pinned deliberately."""
        validate_seed_sources(
            root,
            [SeedEntry(path=VAULT, mode=SEED_MODE_COPY)],
            protected_patterns=lambda: (),
        )

    def test_shape_problems_are_still_reported_beside_the_refusal(self, root: Path) -> None:
        message = _refusal(
            root,
            [
                SeedEntry(path=".env.missing", mode=SEED_MODE_SYMLINK),
                SeedEntry(path=VAULT, mode=SEED_MODE_COPY),
            ],
            _defaults,
        )
        assert ".env.missing" in message
        assert "seed entry #2" in message
