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
    # The committed config is the baseline a protected link must already be listed in.
    _git(root, "add", _CONFIG)
    _git(root, "commit", "-q", "-m", "config")
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
        placed = seed_existing_worktree(worktree, project_root=repo)
        assert sorted(p.name for p in placed) == sorted([VAULT, "local.env"])
        link = worktree / VAULT
        assert link.is_symlink()
        assert not Path(str(link.readlink())).is_absolute()
        assert link.resolve() == (repo / VAULT).resolve()

    def test_works_from_the_main_checkout_path_spelling_of_a_worktree(
        self, repo: Path, worktree: Path
    ) -> None:
        placed = seed_existing_worktree(Path(str(worktree) + "/"), project_root=repo)
        assert len(placed) == 2

    def test_audits_the_protected_link_under_its_own_verb(self, repo: Path, worktree: Path) -> None:
        seed_existing_worktree(worktree, project_root=repo)
        lines = seed_link_audit_path(repo).read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines]
        assert [r["path"] for r in records] == [VAULT]
        assert records[0]["verb"] == SEED_APPLY_VERB
        assert records[0]["outcome"] == "linked"
        assert records[0]["worktree"] == str(worktree.resolve())

    def test_a_second_run_places_nothing_and_leaves_the_links(
        self, repo: Path, worktree: Path
    ) -> None:
        seed_existing_worktree(worktree, project_root=repo)
        assert seed_existing_worktree(worktree, project_root=repo) == []
        assert (worktree / VAULT).is_symlink()

    def test_no_seed_configured_places_nothing(self, repo: Path, worktree: Path) -> None:
        (repo / _CONFIG).write_text("version: '2.0'\n", encoding="utf-8")
        assert seed_existing_worktree(worktree, project_root=repo) == []

    def test_never_writes_the_protected_content_anywhere_new(
        self, repo: Path, worktree: Path
    ) -> None:
        seed_existing_worktree(worktree, project_root=repo)
        audit = seed_link_audit_path(repo).read_text(encoding="utf-8")
        assert "not-a-real-secret" not in audit
        assert not any(
            p.is_file() and not p.is_symlink() and p.name == VAULT for p in worktree.rglob("*")
        )


class TestRefusesAnythingButARegisteredWorktree:
    def test_the_main_checkout(self, repo: Path, worktree: Path) -> None:
        with pytest.raises(SeedApplyRefused, match="main checkout"):
            seed_existing_worktree(repo, project_root=repo)

    def test_an_unregistered_directory(self, repo: Path, tmp_path: Path) -> None:
        stray = tmp_path / "stray"
        stray.mkdir()
        with pytest.raises(SeedApplyRefused):
            seed_existing_worktree(stray, project_root=repo)

    def test_a_subdirectory_of_a_worktree(self, repo: Path, worktree: Path) -> None:
        sub = worktree / "sub"
        sub.mkdir()
        with pytest.raises(SeedApplyRefused, match="registered worktree"):
            seed_existing_worktree(sub, project_root=repo)
        assert not (sub / VAULT).exists()

    @staticmethod
    def _other_repository(tmp_path: Path, *, configured: bool) -> Path:
        """A second repository with a hand-made worktree; optionally with its own seed config."""
        other = tmp_path / "other"
        other.mkdir()
        _git(other, "init", "-q", "-b", "main")
        _git(other, "config", "user.email", "test@example.invalid")
        _git(other, "config", "user.name", "Test")
        _git(other, "commit", "-q", "--allow-empty", "-m", "init")
        if configured:
            (other / "local.env").write_text("ordinary\n", encoding="utf-8")
            (other / ".claude").mkdir()
            (other / _CONFIG).write_text(_config(_LINK_PLAIN), encoding="utf-8")
            _git(other, "add", _CONFIG)
            _git(other, "commit", "-q", "-m", "config")
        other_wt = tmp_path / "other-wt"
        _git(other, "worktree", "add", "-q", "-b", "x", str(other_wt))
        return other_wt

    def test_a_worktree_of_another_repository_is_refused(self, repo: Path, tmp_path: Path) -> None:
        other_wt = self._other_repository(tmp_path, configured=False)
        with pytest.raises(SeedApplyRefused, match="not a worktree of this project"):
            seed_existing_worktree(other_wt, project_root=repo)
        assert not (other_wt / VAULT).exists()

    def test_a_configured_worktree_of_another_repository_is_refused(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """D-PATH 1: a sibling clone with a valid config of its own is still not this project."""
        other_wt = self._other_repository(tmp_path, configured=True)
        with pytest.raises(SeedApplyRefused, match="not a worktree of this project"):
            seed_existing_worktree(other_wt, project_root=repo)
        assert not (other_wt / "local.env").exists()
        assert not (tmp_path / "other" / "untracked").exists()

    def test_a_project_root_inside_a_worktree_anchors_to_the_same_main_checkout(
        self, repo: Path, worktree: Path
    ) -> None:
        """A daemon rooted at the worktree is still this project."""
        assert len(seed_existing_worktree(worktree, project_root=worktree)) == 2

    def test_a_project_root_that_is_no_repository_refuses(
        self, repo: Path, worktree: Path, tmp_path: Path
    ) -> None:
        bare = tmp_path / "not-a-repo"
        bare.mkdir()
        with pytest.raises(SeedApplyRefused, match="not a worktree of this project"):
            seed_existing_worktree(worktree, project_root=bare)
        assert not (worktree / VAULT).exists()

    def test_a_path_that_does_not_exist(self, repo: Path, tmp_path: Path) -> None:
        with pytest.raises(SeedApplyRefused):
            seed_existing_worktree(tmp_path / "absent", project_root=repo)

    def test_a_path_with_a_control_character(self, repo: Path, worktree: Path) -> None:
        with pytest.raises(SeedApplyRefused):
            seed_existing_worktree(Path(str(worktree) + "\n"), project_root=repo)

    def test_a_path_too_long_to_name_refuses_without_a_traceback(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """D-PATH 2: ENAMETOOLONG is a refusal, not a raw OSError."""
        with pytest.raises(SeedApplyRefused):
            seed_existing_worktree(tmp_path / ("x" * 300), project_root=repo)

    def test_a_symlink_to_a_worktree_is_judged_by_where_it_resolves(
        self, repo: Path, worktree: Path, tmp_path: Path
    ) -> None:
        alias = tmp_path / "alias"
        alias.symlink_to(worktree)
        placed = seed_existing_worktree(alias, project_root=repo)
        assert {p.parent for p in placed} == {worktree.resolve()}


class TestReadsTheConfigStrictly:
    def test_missing_config_refuses(self, repo: Path, worktree: Path) -> None:
        (repo / _CONFIG).unlink()
        with pytest.raises(SeedApplyRefused, match="config"):
            seed_existing_worktree(worktree, project_root=repo)
        assert not (worktree / VAULT).exists()

    def test_a_yml_config_is_read_as_the_daemon_reads_it(self, repo: Path, worktree: Path) -> None:
        (repo / _CONFIG).rename(repo / ".claude" / "hooks-daemon.yml")
        assert len(seed_existing_worktree(worktree, project_root=repo)) == 2

    def test_a_disabled_worktree_create_handler_refuses(self, repo: Path, worktree: Path) -> None:
        text = (repo / _CONFIG).read_text(encoding="utf-8")
        (repo / _CONFIG).write_text(
            text.replace("enabled: true", "enabled: false"), encoding="utf-8"
        )
        with pytest.raises(SeedApplyRefused, match="disabled"):
            seed_existing_worktree(worktree, project_root=repo)
        assert not (worktree / VAULT).exists()

    def test_malformed_config_refuses(self, repo: Path, worktree: Path) -> None:
        (repo / _CONFIG).write_text("handlers: [unclosed\n", encoding="utf-8")
        with pytest.raises(SeedApplyRefused, match="config"):
            seed_existing_worktree(worktree, project_root=repo)
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
            seed_existing_worktree(worktree, project_root=repo)
        assert list(outside.iterdir()) == []


class TestAFilesystemErrorMidPlacementIsARefusal:
    """D-PATH 2: an OSError after the first placement reports what landed and what did not."""

    def test_a_parent_that_is_a_regular_file_refuses_and_names_the_placed(
        self, repo: Path, worktree: Path
    ) -> None:
        (repo / "sub").mkdir()
        (repo / "sub" / "notes.txt").write_text("ordinary\n", encoding="utf-8")
        (repo / "later.txt").write_text("ordinary\n", encoding="utf-8")
        entries = (
            _LINK_PLAIN
            + "            - path: sub/notes.txt\n              mode: symlink\n"
            + "            - path: later.txt\n              mode: symlink\n"
        )
        (repo / _CONFIG).write_text(_config(entries), encoding="utf-8")
        (worktree / "sub").write_text("a file where a directory is expected\n", encoding="utf-8")

        with pytest.raises(SeedApplyRefused) as caught:
            seed_existing_worktree(worktree, project_root=repo)

        message = str(caught.value)
        assert "seed entry #2" in message
        assert "#1" in message  # placed before the failure
        assert "#3" in message  # never attempted
        assert "FileExistsError" in message
        assert caught.value.placed == [worktree.resolve() / "local.env"]
        assert (worktree / "local.env").is_symlink()
        assert not (worktree / "later.txt").exists()


class TestTheSameExecutorAsCreation:
    def test_a_protected_copy_is_refused_before_anything_is_placed(
        self, repo: Path, worktree: Path
    ) -> None:
        copy_vault = f"            - path: {VAULT}\n              mode: copy\n"
        (repo / _CONFIG).write_text(_config(_LINK_PLAIN + copy_vault), encoding="utf-8")
        with pytest.raises(SeedApplyRefused, match="secret_file_guard"):
            seed_existing_worktree(worktree, project_root=repo)
        assert not (worktree / VAULT).exists()
        assert not (worktree / "local.env").exists()

    def test_an_absent_required_source_refuses(self, repo: Path, worktree: Path) -> None:
        (repo / "local.env").unlink()
        with pytest.raises(SeedApplyRefused, match="no such file"):
            seed_existing_worktree(worktree, project_root=repo)


class TestAProtectedLinkMustBeInTheCommittedConfig:
    """Residual (1) of the 261120 handoff: an agent edits the seed list, then runs the verb.

    The verb reads the config fresh from disk, so an uncommitted edit would place a
    link to any protected path at once. A link-mode entry whose source is, holds or
    links to a protected path is placed only when the config committed at HEAD of
    the main checkout lists the same entry; an unprotected entry is not gated.
    """

    def test_an_uncommitted_protected_entry_refuses_before_anything_is_placed(
        self, repo: Path, worktree: Path
    ) -> None:
        (repo / "conf").mkdir()
        (repo / "conf" / VAULT).write_text("not-a-real-secret\n", encoding="utf-8")
        added = "            - path: conf\n              mode: symlink\n"
        (repo / _CONFIG).write_text(_config(_LINK_PLAIN + added), encoding="utf-8")
        with pytest.raises(SeedApplyRefused, match="committed"):
            seed_existing_worktree(worktree, project_root=repo)
        assert not (worktree / "conf").exists()
        assert not (worktree / "local.env").exists()

    def test_an_uncommitted_unprotected_entry_is_placed(self, repo: Path, worktree: Path) -> None:
        (repo / "notes.txt").write_text("ordinary\n", encoding="utf-8")
        added = "            - path: notes.txt\n              mode: symlink\n"
        (repo / _CONFIG).write_text(_config(_LINK_VAULT + added), encoding="utf-8")
        placed = seed_existing_worktree(worktree, project_root=repo)
        assert sorted(p.name for p in placed) == sorted([VAULT, "notes.txt"])

    def test_a_committed_protected_entry_is_placed(self, repo: Path, worktree: Path) -> None:
        assert (worktree.resolve() / VAULT) in seed_existing_worktree(worktree, project_root=repo)

    def test_no_committed_config_refuses_a_protected_entry(
        self, repo: Path, worktree: Path
    ) -> None:
        _git(repo, "rm", "-q", "--cached", _CONFIG)
        _git(repo, "commit", "-q", "-m", "untrack config")
        with pytest.raises(SeedApplyRefused, match="committed"):
            seed_existing_worktree(worktree, project_root=repo)
        assert not (worktree / VAULT).exists()

    def test_unprotecting_the_path_in_the_working_config_does_not_ungate_it(
        self, repo: Path, worktree: Path
    ) -> None:
        guarded = (
            "  pre_tool_use:\n"
            "    secret_file_guard:\n"
            "      enabled: true\n"
            "      options:\n"
            "        protected_paths:\n"
            "          - conf/app.txt\n"
        )
        (repo / "conf").mkdir()
        (repo / "conf" / "app.txt").write_text("not-a-real-secret\n", encoding="utf-8")
        committed = _config(_LINK_PLAIN).replace("handlers:\n", "handlers:\n" + guarded)
        (repo / _CONFIG).write_text(committed, encoding="utf-8")
        _git(repo, "add", _CONFIG)
        _git(repo, "commit", "-q", "-m", "protect conf")
        added = "            - path: conf\n              mode: symlink\n"
        (repo / _CONFIG).write_text(_config(_LINK_PLAIN + added), encoding="utf-8")
        with pytest.raises(SeedApplyRefused, match="committed"):
            seed_existing_worktree(worktree, project_root=repo)
        assert not (worktree / "conf").exists()
