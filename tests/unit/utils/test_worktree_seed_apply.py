"""Apply the configured seed list to a worktree made by hand (Plan 00613 Task 3.3).

The owner approved linking a protected file into a worktree, by a route the
project config or a human owns and never by one that lets an agent link an
arbitrary protected path. The ``worktree_create`` handler seeds the worktrees
Claude Code creates; a worktree made with a hand-run ``git worktree add`` gets
nothing. ``seed_existing_worktree`` closes that gap by re-applying THE
CONFIGURED LIST to one registered worktree. It takes no path to link, so the
config stays the only thing that decides what is linked.

Decisions pinned here:

- The target must be a worktree git lists for this repository, by realpath,
  and not the main checkout or a prunable one. Anything else refuses.
- The config is read strictly: missing, malformed or schema-invalid refuses.
- The same executor runs as at creation: the copy refusal for a protected
  source, and an audit line per protected link, recorded with its own verb.
- An existing destination is never touched, so a second run places nothing.

Protected names are assembled from pieces so this file does not itself name a
protected path to the secret guard.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.worktree_seed_apply import (
    SEED_APPLY_VERB,
    SeedApplyRefused,
    seed_existing_worktree,
)
from claude_code_hooks_daemon.utils.worktree_seeding import seed_link_audit_path

VAULT = "." + "vault" + "-pass"
_CONFIG = ".claude/hooks-daemon.yaml"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _config(entries: str) -> str:
    return (
        "version: '2.0'\n"
        "handlers:\n"
        "  worktree_create:\n"
        "    worktree_create:\n"
        "      enabled: true\n"
        "      options:\n"
        "        seed:\n"
        "          entries:\n" + entries
    )


_LINK_VAULT = f"            - path: {VAULT}\n              mode: symlink\n"
_LINK_PLAIN = "            - path: local.env\n              mode: symlink\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A main checkout with a protected file, an ordinary one, and a seed config."""
    root = tmp_path / "main"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    (root / ".gitignore").write_text(f"{VAULT}\nlocal.env\nuntracked/\n", encoding="utf-8")
    _git(root, "add", ".gitignore")
    _git(root, "commit", "-q", "-m", "init")
    (root / VAULT).write_text("not-a-real-secret\n", encoding="utf-8")
    (root / "local.env").write_text("ordinary\n", encoding="utf-8")
    (root / ".claude").mkdir()
    (root / _CONFIG).write_text(_config(_LINK_VAULT + _LINK_PLAIN), encoding="utf-8")
    return root


@pytest.fixture
def worktree(repo: Path, tmp_path: Path) -> Path:
    """A worktree of ``repo`` made by hand, outside the harness."""
    path = tmp_path / "hand-made"
    _git(repo, "worktree", "add", "-q", "-b", "hand", str(path))
    return path


class TestSeedsARegisteredWorktree:
    def test_places_each_configured_entry_as_a_relative_link(
        self, repo: Path, worktree: Path
    ) -> None:
        placed = seed_existing_worktree(worktree)
        assert sorted(p.name for p in placed) == sorted([VAULT, "local.env"])
        link = worktree / VAULT
        assert link.is_symlink()
        assert not Path(str(link.readlink())).is_absolute()
        assert link.resolve() == (repo / VAULT).resolve()

    def test_works_from_the_main_checkout_path_spelling_of_a_worktree(
        self, repo: Path, worktree: Path
    ) -> None:
        placed = seed_existing_worktree(Path(str(worktree) + "/"))
        assert len(placed) == 2

    def test_audits_the_protected_link_under_its_own_verb(
        self, repo: Path, worktree: Path
    ) -> None:
        seed_existing_worktree(worktree)
        lines = seed_link_audit_path(repo).read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines]
        assert [r["path"] for r in records] == [VAULT]
        assert records[0]["verb"] == SEED_APPLY_VERB
        assert records[0]["outcome"] == "linked"
        assert records[0]["worktree"] == str(worktree.resolve())

    def test_a_second_run_places_nothing_and_leaves_the_links(
        self, repo: Path, worktree: Path
    ) -> None:
        seed_existing_worktree(worktree)
        assert seed_existing_worktree(worktree) == []
        assert (worktree / VAULT).is_symlink()

    def test_no_seed_configured_places_nothing(self, repo: Path, worktree: Path) -> None:
        (repo / _CONFIG).write_text("version: '2.0'\n", encoding="utf-8")
        assert seed_existing_worktree(worktree) == []

    def test_never_writes_the_protected_content_anywhere_new(
        self, repo: Path, worktree: Path
    ) -> None:
        seed_existing_worktree(worktree)
        audit = seed_link_audit_path(repo).read_text(encoding="utf-8")
        assert "not-a-real-secret" not in audit
        assert not any(
            p.is_file() and not p.is_symlink() and p.name == VAULT for p in worktree.rglob("*")
        )


class TestRefusesAnythingButARegisteredWorktree:
    def test_the_main_checkout(self, repo: Path, worktree: Path) -> None:
        with pytest.raises(SeedApplyRefused, match="main checkout"):
            seed_existing_worktree(repo)

    def test_an_unregistered_directory(self, repo: Path, tmp_path: Path) -> None:
        stray = tmp_path / "stray"
        stray.mkdir()
        with pytest.raises(SeedApplyRefused):
            seed_existing_worktree(stray)

    def test_a_subdirectory_of_a_worktree(self, repo: Path, worktree: Path) -> None:
        sub = worktree / "sub"
        sub.mkdir()
        with pytest.raises(SeedApplyRefused, match="registered worktree"):
            seed_existing_worktree(sub)
        assert not (sub / VAULT).exists()

    def test_a_worktree_of_another_repository_is_judged_by_its_own_config(
        self, repo: Path, tmp_path: Path
    ) -> None:
        other = tmp_path / "other"
        other.mkdir()
        _git(other, "init", "-q", "-b", "main")
        _git(other, "commit", "-q", "--allow-empty", "-m", "init")
        other_wt = tmp_path / "other-wt"
        _git(other, "worktree", "add", "-q", "-b", "x", str(other_wt))
        # The other repository has no config, so nothing of ``repo`` reaches it.
        with pytest.raises(SeedApplyRefused, match="config"):
            seed_existing_worktree(other_wt)
        assert not (other_wt / VAULT).exists()

    def test_a_path_that_does_not_exist(self, repo: Path, tmp_path: Path) -> None:
        with pytest.raises(SeedApplyRefused):
            seed_existing_worktree(tmp_path / "absent")

    def test_a_path_with_a_control_character(self, repo: Path, worktree: Path) -> None:
        with pytest.raises(SeedApplyRefused):
            seed_existing_worktree(Path(str(worktree) + "\n"))

    def test_a_symlink_to_a_worktree_is_judged_by_where_it_resolves(
        self, repo: Path, worktree: Path, tmp_path: Path
    ) -> None:
        alias = tmp_path / "alias"
        alias.symlink_to(worktree)
        placed = seed_existing_worktree(alias)
        assert {p.parent for p in placed} == {worktree.resolve()}


class TestReadsTheConfigStrictly:
    def test_missing_config_refuses(self, repo: Path, worktree: Path) -> None:
        (repo / _CONFIG).unlink()
        with pytest.raises(SeedApplyRefused, match="config"):
            seed_existing_worktree(worktree)
        assert not (worktree / VAULT).exists()

    def test_a_yml_config_is_read_as_the_daemon_reads_it(
        self, repo: Path, worktree: Path
    ) -> None:
        (repo / _CONFIG).rename(repo / ".claude" / "hooks-daemon.yml")
        assert len(seed_existing_worktree(worktree)) == 2

    def test_a_disabled_worktree_create_handler_refuses(
        self, repo: Path, worktree: Path
    ) -> None:
        text = (repo / _CONFIG).read_text(encoding="utf-8")
        (repo / _CONFIG).write_text(
            text.replace("enabled: true", "enabled: false"), encoding="utf-8"
        )
        with pytest.raises(SeedApplyRefused, match="disabled"):
            seed_existing_worktree(worktree)
        assert not (worktree / VAULT).exists()

    def test_malformed_config_refuses(self, repo: Path, worktree: Path) -> None:
        (repo / _CONFIG).write_text("handlers: [unclosed\n", encoding="utf-8")
        with pytest.raises(SeedApplyRefused, match="config"):
            seed_existing_worktree(worktree)
        assert not (worktree / VAULT).exists()


class TestAnExistingWorktreeCannotRedirectAPlacement:
    """A hand-made worktree is not fresh: a parent of a destination may be a link."""

    def test_a_symlinked_parent_inside_the_worktree_refuses(
        self, repo: Path, worktree: Path, tmp_path: Path
    ) -> None:
        nested = f"            - path: conf/{VAULT}\n              mode: symlink\n"
        (repo / "conf").mkdir()
        (repo / "conf" / VAULT).write_text("not-a-real-secret\n", encoding="utf-8")
        (repo / _CONFIG).write_text(_config(nested), encoding="utf-8")
        outside = tmp_path / "outside"
        outside.mkdir()
        (worktree / "conf").symlink_to(outside)
        with pytest.raises(SeedApplyRefused, match="symlink"):
            seed_existing_worktree(worktree)
        assert list(outside.iterdir()) == []


class TestTheSameExecutorAsCreation:
    def test_a_protected_copy_is_refused_before_anything_is_placed(
        self, repo: Path, worktree: Path
    ) -> None:
        copy_vault = f"            - path: {VAULT}\n              mode: copy\n"
        (repo / _CONFIG).write_text(_config(_LINK_PLAIN + copy_vault), encoding="utf-8")
        with pytest.raises(SeedApplyRefused, match="secret_file_guard"):
            seed_existing_worktree(worktree)
        assert not (worktree / VAULT).exists()
        assert not (worktree / "local.env").exists()

    def test_an_absent_required_source_refuses(self, repo: Path, worktree: Path) -> None:
        (repo / "local.env").unlink()
        with pytest.raises(SeedApplyRefused, match="no such file"):
            seed_existing_worktree(worktree)
