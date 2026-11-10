"""Tests for the post-merge and ``branch-sweep --clean`` cleanup (Plan 00558 Task 3.1).

Real repositories throughout: the subject is git's own reachability, worktree
and ignore semantics, which a mock would only restate.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_cleanup
from claude_code_hooks_daemon.core.branch_cleanup import (
    CleanupReport,
    clean_sweep,
    cleanup_after_merge,
    cleanup_targets,
    merge_target_qualifies,
    policy_refusal,
    render,
    worktree_blockers,
)
from claude_code_hooks_daemon.daemon.branch_safety import (
    TIER_UNPROVEN,
    BranchClassification,
    DeletionReport,
)
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs

_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "PATH": "/usr/bin:/bin",
}

_CONFIG = BranchesConfig(default="main", integration_lines=["release/*"], exempt=["users/*"])
_REGENERABLE = _CONFIG.cleanup_after_merge.regenerable


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**_ENV, "HOME": str(repo)},
    )
    return result.stdout


def _commit(repo: Path, filename: str, content: str, message: str) -> None:
    (repo / filename).write_text(content, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", message)


def _branches(repo: Path) -> set[str]:
    out = _git(repo, "for-each-ref", "--format=%(refname)", "refs/heads")
    return {line.removeprefix("refs/heads/") for line in out.splitlines() if line}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-b", "main")
    (path / ".gitignore").write_text("untracked/\n__pycache__/\n", encoding="utf-8")
    _git(path, "add", ".gitignore")
    _git(path, "commit", "-m", "Initial commit")
    return path


def _merged(repo: Path, name: str) -> str:
    _git(repo, "checkout", "-b", name)
    _commit(repo, f"{name.replace('/', '-')}.txt", f"{name}\n", f"Add {name}")
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--no-ff", "-m", f"Merge {name}", name)
    return _git(repo, "rev-parse", f"refs/heads/{name}").strip()


def _patch_equivalent(repo: Path, name: str) -> None:
    _git(repo, "checkout", "-b", name)
    _commit(repo, "picked.txt", "picked\n", "Add picked")
    _git(repo, "checkout", "main")
    _commit(repo, "diverge.txt", "diverge\n", "Diverge")
    _git(repo, "cherry-pick", name)


def _unproven(repo: Path, name: str) -> None:
    _git(repo, "checkout", "-b", name)
    _commit(repo, "novel.txt", "novel\n", "Novel work")
    _git(repo, "checkout", "main")


def _worktree(repo: Path, name: str) -> Path:
    path = repo.parent / f"wt-{name}"
    _git(repo, "worktree", "add", str(path), name)
    return path


class TestPolicy:
    def test_default_exempt_and_protected_are_refused(self) -> None:
        assert policy_refusal("main", _CONFIG, "main") is not None
        assert policy_refusal("users/alice", _CONFIG, "main") is not None
        assert policy_refusal("develop", _CONFIG, "main") is not None
        assert policy_refusal("feature", _CONFIG, "main") is None

    def test_an_integration_line_is_judged_by_proof_not_refused_by_name(self) -> None:
        assert policy_refusal("release/1.0", _CONFIG, "main") is None

    def test_merge_target_must_be_default_or_a_line(self) -> None:
        assert merge_target_qualifies("main", _CONFIG, "main") is True
        assert merge_target_qualifies("release/2", _CONFIG, "main") is True
        assert merge_target_qualifies("feature", _CONFIG, "main") is False
        assert merge_target_qualifies(None, _CONFIG, "main") is False


class TestCleanupTargets:
    def test_only_existing_refs_are_targets(self, repo: Path) -> None:
        _git(repo, "branch", "release/1")
        assert cleanup_targets(repo, _CONFIG, "main") == ["main", "refs/heads/release/1"]


def _lock_pair_branch(repo: Path, name: str, where: str, manifest: str, lock: str | None) -> Path:
    """A worktree whose branch commits ``manifest`` (and ``lock``) under ``where``."""
    _git(repo, "checkout", "-b", name)
    directory = repo / where
    directory.mkdir(parents=True, exist_ok=True)
    for filename in (manifest, lock):
        if filename is not None:
            (directory / filename).write_text("{}\n", encoding="utf-8")
            _git(repo, "add", f"{where}/{filename}")
    (repo / ".gitignore").write_text("untracked/\nvendor/\nnode_modules/\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-m", f"Add {name}")
    _git(repo, "checkout", "main")
    return _worktree(repo, name)


class TestLockRegeneratedBlockers:
    def test_nested_composer_vendor_beside_manifest_and_lock_is_regenerable(
        self, repo: Path
    ) -> None:
        path = _lock_pair_branch(repo, "f1", "svc/api", "composer.json", "composer.lock")
        (path / "svc/api/vendor/pkg").mkdir(parents=True)
        (path / "svc/api/vendor/pkg/a.php").write_text("x\n", encoding="utf-8")
        assert worktree_blockers(path, []) == ()

    def test_without_the_lock_it_still_blocks(self, repo: Path) -> None:
        path = _lock_pair_branch(repo, "f2", "svc/api", "composer.json", None)
        (path / "svc/api/vendor").mkdir(parents=True)
        (path / "svc/api/vendor/a.php").write_text("x\n", encoding="utf-8")
        assert worktree_blockers(path, []) == ("svc/api/vendor/",)

    def test_a_vendor_dir_holding_a_tracked_file_still_blocks(self, repo: Path) -> None:
        path = _lock_pair_branch(repo, "f3", "svc", "composer.json", "composer.lock")
        (path / "svc/vendor").mkdir()
        (path / "svc/vendor/mine.php").write_text("x\n", encoding="utf-8")
        _git(path, "add", "-f", "svc/vendor/mine.php")
        _git(path, "commit", "-m", "track a vendor file")
        (path / "svc/vendor/extra.php").write_text("y\n", encoding="utf-8")
        assert worktree_blockers(path, []) == ("svc/vendor/extra.php",)

    def test_node_modules_at_depth_three_is_regenerable(self, repo: Path) -> None:
        path = _lock_pair_branch(repo, "f4", "a/b/c", "package.json", "package-lock.json")
        (path / "a/b/c/node_modules/x").mkdir(parents=True)
        (path / "a/b/c/node_modules/x/i.js").write_text("x\n", encoding="utf-8")
        assert worktree_blockers(path, []) == ()

    def test_a_vendor_dir_holding_a_nested_git_clone_still_blocks(self, repo: Path) -> None:
        path = _lock_pair_branch(repo, "f6", "svc", "composer.json", "composer.lock")
        (path / "svc/vendor/pkg/.git").mkdir(parents=True)
        (path / "svc/vendor/pkg/a.php").write_text("x\n", encoding="utf-8")
        blockers = worktree_blockers(path, [])
        assert blockers
        assert all(b.startswith("svc/vendor/") for b in blockers)

    def test_a_clone_at_depth_one_and_two_is_found(self, tmp_path: Path) -> None:
        shallow = tmp_path / "shallow"
        (shallow / "pkg" / ".git").mkdir(parents=True)
        deep = tmp_path / "deep"
        (deep / "scope" / "pkg" / ".git").mkdir(parents=True)
        assert branch_cleanup._holds_git_clone(shallow) is True
        assert branch_cleanup._holds_git_clone(deep) is True

    def test_a_clone_below_depth_two_is_not_searched_for(self, tmp_path: Path) -> None:
        """Only `<dir>/*/.git` and `<dir>/*/*/.git` are statted, which bounds the walk."""
        too_deep = tmp_path / "vendor"
        (too_deep / "a" / "b" / "c" / ".git").mkdir(parents=True)
        assert branch_cleanup._holds_git_clone(too_deep) is False

    def test_a_missing_directory_holds_nothing_and_logs_nothing(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG):
            assert branch_cleanup._holds_git_clone(tmp_path / "vendor") is False
        assert caplog.records == []

    def test_the_committed_tree_is_not_read_when_no_ignored_directory_could_be_rebuilt(
        self, repo: Path
    ) -> None:
        _git(repo, "branch", "plain")
        path = _worktree(repo, "plain")
        (path / ".gitignore").write_text("*.log\n", encoding="utf-8")
        _git(path, "add", ".gitignore")
        _git(path, "commit", "-m", "ignore logs")
        (path / "notes.log").write_text("x\n", encoding="utf-8")
        with patch.object(branch_cleanup, "_lock_regenerated") as lock_regenerated:
            blockers = worktree_blockers(path, [])
        lock_regenerated.assert_not_called()
        assert blockers == ("notes.log",)

    def test_scratch_is_never_accepted(self, repo: Path) -> None:
        path = _lock_pair_branch(repo, "f5", "svc", "composer.json", "composer.lock")
        (path / "untracked/scratch").mkdir(parents=True)
        (path / "untracked/scratch/n.md").write_text("x\n", encoding="utf-8")
        assert worktree_blockers(path, []) == ("untracked/scratch/",)


class TestWorktreeBlockers:
    def test_a_clean_worktree_with_only_regenerable_files_has_none(self, repo: Path) -> None:
        _git(repo, "branch", "feat")
        path = _worktree(repo, "feat")
        (path / "untracked" / "qa").mkdir(parents=True)
        (path / "untracked" / "qa" / "out.txt").write_text("x\n", encoding="utf-8")
        assert worktree_blockers(path, _REGENERABLE) == ()

    def test_scratch_notes_block(self, repo: Path) -> None:
        _git(repo, "branch", "feat")
        path = _worktree(repo, "feat")
        (path / "untracked" / "scratch").mkdir(parents=True)
        (path / "untracked" / "scratch" / "notes.md").write_text("x\n", encoding="utf-8")
        assert worktree_blockers(path, _REGENERABLE) == ("untracked/scratch/",)

    def test_the_configured_list_decides(self, repo: Path) -> None:
        _git(repo, "branch", "feat")
        path = _worktree(repo, "feat")
        (path / "untracked" / "qa").mkdir(parents=True)
        (path / "untracked" / "qa" / "out.txt").write_text("x\n", encoding="utf-8")
        assert worktree_blockers(path, ["untracked/docs-qa/"]) == ("untracked/qa/",)

    def _feat_with_daemon_env(self, repo: Path, body: str) -> Path:
        # A real worktree tracks `.claude/`; only the env file inside is ignored.
        (repo / ".claude").mkdir()
        (repo / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
        (repo / ".git" / "info" / "exclude").write_text("untracked/\n.claude/*.env\n")
        _git(repo, "add", ".claude/settings.json")
        _git(repo, "commit", "-q", "-m", "track .claude")
        _git(repo, "branch", "feat")
        path = _worktree(repo, "feat")
        (path / ".claude" / "hooks-daemon.env").write_text(body, encoding="utf-8")
        return path

    def test_the_generated_daemon_env_is_not_a_blocker(self, repo: Path) -> None:
        # setup_worktree.sh writes it with the installer's template: comments
        # and one checkout-agnostic assignment, nothing a removal can lose.
        path = self._feat_with_daemon_env(
            repo, '# generated\n\nHOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH"\n'
        )
        assert worktree_blockers(path, _REGENERABLE) == ()

    def test_a_hand_edited_daemon_env_still_blocks(self, repo: Path) -> None:
        path = self._feat_with_daemon_env(
            repo, 'HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH"\nEXTRA_SETTING="kept"\n'
        )
        assert worktree_blockers(path, _REGENERABLE) == (".claude/hooks-daemon.env",)

    def test_untracked_and_modified_files_block(self, repo: Path) -> None:
        _git(repo, "branch", "feat")
        path = _worktree(repo, "feat")
        (path / "new.txt").write_text("x\n", encoding="utf-8")
        (path / ".gitignore").write_text("changed\n", encoding="utf-8")
        assert set(worktree_blockers(path, _REGENERABLE)) == {"new.txt", ".gitignore"}

    def test_an_empty_scratch_directory_is_not_a_blocker(self, repo: Path) -> None:
        """Nothing is lost by removing a directory that holds no file (Task 3.3)."""
        _git(repo, "branch", "feat")
        path = _worktree(repo, "feat")
        (path / "untracked" / "scratch" / "nested").mkdir(parents=True)
        assert worktree_blockers(path, _REGENERABLE) == ()

    def test_an_empty_directory_elsewhere_is_not_a_blocker(self, repo: Path) -> None:
        _git(repo, "branch", "feat")
        path = _worktree(repo, "feat")
        (path / "src" / "__pycache__").mkdir(parents=True)
        (path / "untracked" / "kept").mkdir(parents=True)
        assert worktree_blockers(path, ["untracked/qa/"]) == ()

    def test_scratch_holding_one_file_deep_down_still_blocks(self, repo: Path) -> None:
        _git(repo, "branch", "feat")
        path = _worktree(repo, "feat")
        deep = path / "untracked" / "scratch" / "a" / "b"
        deep.mkdir(parents=True)
        (deep / "notes.md").write_text("x\n", encoding="utf-8")
        assert worktree_blockers(path, _REGENERABLE) == ("untracked/scratch/",)

    def test_a_symlinked_store_matches_its_directory_glob(self, repo: Path, tmp_path: Path) -> None:
        """``untracked/lsp-venv/`` covers a symlink of that name (Task 3.3)."""
        _git(repo, "branch", "feat")
        path = _worktree(repo, "feat")
        (path / "untracked").mkdir()
        store = tmp_path / "shared-lsp-venv"
        store.mkdir()
        (store / "python").write_text("x\n", encoding="utf-8")
        (path / "untracked" / "lsp-venv").symlink_to(store)
        (path / "untracked" / "gone-venv").symlink_to(tmp_path / "missing")
        assert worktree_blockers(path, ["untracked/lsp-venv/", "untracked/gone-venv/"]) == ()

    def test_a_symlink_to_a_directory_the_globs_do_not_name_is_not_a_blocker(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """Removal only unlinks a symlink; its target outside the worktree survives."""
        _git(repo, "branch", "feat")
        path = _worktree(repo, "feat")
        (path / "untracked").mkdir()
        outside = tmp_path / "outside-dir"
        outside.mkdir()
        (outside / "keep.txt").write_text("x\n", encoding="utf-8")
        (path / "untracked" / "notes").symlink_to(outside)
        assert worktree_blockers(path, ["untracked/lsp-venv/"]) == ()
        _git(repo, "worktree", "remove", str(path))
        assert not path.exists()
        assert (outside / "keep.txt").read_text(encoding="utf-8") == "x\n"

    def test_a_seeded_symlink_to_a_file_outside_is_not_a_blocker(
        self, repo: Path, tmp_path: Path
    ) -> None:
        (repo / ".claude").mkdir()
        (repo / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
        (repo / ".git" / "info" / "exclude").write_text("untracked/\n.claude/*.cfg\n")
        _git(repo, "add", ".claude/settings.json")
        _git(repo, "commit", "-q", "-m", "track .claude")
        _git(repo, "branch", "feat")
        path = _worktree(repo, "feat")
        target = tmp_path / "shared.cfg"
        target.write_text("x\n", encoding="utf-8")
        (path / ".claude" / "seeded.cfg").symlink_to(target)
        assert worktree_blockers(path, _REGENERABLE) == ()

    def test_a_real_ignored_file_beside_a_symlink_still_blocks(
        self, repo: Path, tmp_path: Path
    ) -> None:
        _git(repo, "branch", "feat")
        path = _worktree(repo, "feat")
        (path / "untracked" / "scratch").mkdir(parents=True)
        (path / "untracked" / "scratch" / "notes.md").write_text("x\n", encoding="utf-8")
        (path / "untracked" / "link").symlink_to(tmp_path)
        assert worktree_blockers(path, _REGENERABLE) == ("untracked/scratch/",)


class TestCleanupAfterMerge:
    def test_act_deletes_a_merged_branch_and_prints_the_restore_line(self, repo: Path) -> None:
        tip = _merged(repo, "feat")
        report = cleanup_after_merge(repo, ["feat"], config=_CONFIG, target="main", mode="act")
        assert report.deleted == ("feat",)
        assert "feat" not in _branches(repo)
        assert f"git branch feat {tip}" in report.commands
        assert report.bundle is None

    def test_advise_deletes_nothing_and_names_the_command(self, repo: Path) -> None:
        _merged(repo, "feat")
        report = cleanup_after_merge(repo, ["feat"], config=_CONFIG, target="main", mode="advise")
        assert report.deleted == ()
        assert "feat" in _branches(repo)
        assert (
            f"{daemon_cli_command_for_docs('delete-branch')} feat --protected-ref main"
            in report.commands
        )

    def test_a_worktree_is_never_removed_only_advised(self, repo: Path) -> None:
        _merged(repo, "feat")
        path = _worktree(repo, "feat")
        report = cleanup_after_merge(repo, ["feat"], config=_CONFIG, target="main", mode="act")
        assert report.deleted == ()
        assert path.is_dir()
        assert f"git worktree remove {path}" in report.commands

    def test_patch_equivalent_points_at_the_sweep(self, repo: Path) -> None:
        _patch_equivalent(repo, "picked")
        report = cleanup_after_merge(repo, ["picked"], config=_CONFIG, target="main", mode="act")
        assert report.deleted == ()
        assert daemon_cli_command_for_docs("branch-sweep", "--clean") in report.commands

    def test_an_exempt_branch_is_skipped(self, repo: Path) -> None:
        _merged(repo, "users/alice")
        report = cleanup_after_merge(
            repo, ["users/alice"], config=_CONFIG, target="main", mode="act"
        )
        assert report.deleted == ()
        assert report.skipped

    def test_the_remote_delete_is_printed_never_run(self, repo: Path, tmp_path: Path) -> None:
        bare = tmp_path / "remote.git"
        _git(tmp_path, "init", "--quiet", "--bare", str(bare))
        _git(repo, "remote", "add", "origin", str(bare))
        _merged(repo, "feat")
        _git(repo, "push", "--quiet", "origin", "feat")
        report = cleanup_after_merge(repo, ["feat"], config=_CONFIG, target="main", mode="act")
        assert "git push origin --delete feat" in report.commands
        assert "feat" in _git(bare, "branch")

    def test_a_line_merged_into_another_line_is_refused(self, repo: Path) -> None:
        _git(repo, "branch", "release/2", "main")
        _git(repo, "checkout", "-b", "release/1")
        _commit(repo, "one.txt", "one\n", "Release one")
        _git(repo, "checkout", "release/2")
        _git(repo, "merge", "--no-ff", "-m", "Merge release/1", "release/1")
        report = cleanup_after_merge(
            repo, ["release/1"], config=_CONFIG, target="release/2", mode="act"
        )
        assert report.deleted == ()
        assert "release/1" in _branches(repo)
        assert any("integration line" in line for line in report.skipped)

    def test_a_line_merged_into_the_default_is_deleted_with_its_restore_line(
        self, repo: Path
    ) -> None:
        tip = _merged(repo, "release/1")
        report = cleanup_after_merge(repo, ["release/1"], config=_CONFIG, target="main", mode="act")
        assert report.deleted == ("release/1",)
        assert f"git branch release/1 {tip}" in report.commands
        assert "release/1" not in _branches(repo)

    def test_the_resolved_default_is_never_deleted_when_the_target_is_a_line(
        self, repo: Path
    ) -> None:
        """A default named outside ``protected_names`` stays protected on a line merge."""
        config = BranchesConfig(default="prod", integration_lines=["release/*"])
        _git(repo, "branch", "-m", "main", "prod")
        _git(repo, "checkout", "-b", "release/2")
        report = cleanup_after_merge(
            repo, ["prod"], config=config, target="release/2", mode="act", default="prod"
        )
        assert report.deleted == ()
        assert "prod" in _branches(repo)
        assert report.skipped


class TestCleanSweep:
    def test_dry_run_touches_nothing(self, repo: Path, tmp_path: Path) -> None:
        _merged(repo, "feat")
        report = clean_sweep(repo, _CONFIG, dry_run=True, bundle_dir=tmp_path / "b")
        assert report.deleted == ()
        assert "feat" in _branches(repo)
        assert any("feat" in line for line in report.commands)

    def test_deletes_merged_and_patch_equivalent_with_a_bundle(
        self, repo: Path, tmp_path: Path
    ) -> None:
        _merged(repo, "feat")
        _patch_equivalent(repo, "picked")
        _unproven(repo, "novel")
        report = clean_sweep(repo, _CONFIG, dry_run=False, bundle_dir=tmp_path / "b")
        assert set(report.deleted) == {"feat", "picked"}
        assert "novel" in _branches(repo)
        assert report.bundle is not None
        assert report.bundle.is_file()

    def test_the_sweep_never_offers_an_integration_line(self, repo: Path, tmp_path: Path) -> None:
        _merged(repo, "release/1")
        _unproven(repo, "release/2")
        report = clean_sweep(repo, _CONFIG, dry_run=False, bundle_dir=tmp_path / "b")
        assert report.deleted == ()
        assert {"release/1", "release/2"} <= _branches(repo)

    def test_removes_a_clean_worktree_with_only_regenerable_files(
        self, repo: Path, tmp_path: Path
    ) -> None:
        _merged(repo, "feat")
        path = _worktree(repo, "feat")
        (path / "__pycache__").mkdir()
        (path / "__pycache__" / "x.pyc").write_bytes(b"x")
        report = clean_sweep(repo, _CONFIG, dry_run=False, bundle_dir=tmp_path / "b")
        assert report.removed_worktrees == (path,)
        assert not path.exists()
        assert report.deleted == ("feat",)

    def test_skips_a_worktree_with_scratch_notes(self, repo: Path, tmp_path: Path) -> None:
        _merged(repo, "feat")
        path = _worktree(repo, "feat")
        (path / "untracked").mkdir()
        (path / "untracked" / "notes.md").write_text("keep\n", encoding="utf-8")
        report = clean_sweep(repo, _CONFIG, dry_run=False, bundle_dir=tmp_path / "b")
        assert report.removed_worktrees == ()
        assert report.deleted == ()
        assert (path / "untracked" / "notes.md").is_file()
        assert any("untracked/notes.md" in line for line in report.skipped)

    def test_blockers_are_capped_with_a_count(self, repo: Path, tmp_path: Path) -> None:
        _merged(repo, "feat")
        path = _worktree(repo, "feat")
        for index in range(13):
            (path / f"loose-{index:02d}.txt").write_text("x\n", encoding="utf-8")
        report = clean_sweep(repo, _CONFIG, dry_run=False, bundle_dir=tmp_path / "b")
        line = next(line for line in report.skipped if line.startswith("feat"))
        assert "and 3 more" in line


class TestRender:
    def test_empty_report_renders_nothing(self) -> None:
        assert render(CleanupReport()) == []

    def test_render_names_every_part(self, tmp_path: Path) -> None:
        report = CleanupReport(
            deleted=("a",),
            removed_worktrees=(tmp_path,),
            skipped=("b: why",),
            commands=("git branch a 123",),
            bundle=tmp_path / "x.bundle",
        )
        text = "\n".join(render(report))
        for part in ("a", str(tmp_path), "b: why", "git branch a 123", "x.bundle"):
            assert part in text


def _failing_git(subcommand: str, monkeypatch: pytest.MonkeyPatch) -> None:
    real = branch_cleanup.run_git

    def fake(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if args and args[0] == subcommand:
            return subprocess.CompletedProcess(["git", *args], 128, "", "boom")
        return real(cwd, *args, **kwargs)

    monkeypatch.setattr(branch_cleanup, "run_git", fake)


class TestFailuresAndEdges:
    def test_targets_include_the_remote_default(self, repo: Path, tmp_path: Path) -> None:
        bare = tmp_path / "remote.git"
        _git(tmp_path, "init", "--quiet", "--bare", str(bare))
        _git(repo, "remote", "add", "origin", str(bare))
        _git(repo, "push", "--quiet", "origin", "main")
        config = BranchesConfig(default="main")
        assert cleanup_targets(repo, config, "main") == ["main", "refs/remotes/origin/main"]

    def test_a_failed_ref_listing_raises(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _failing_git("for-each-ref", monkeypatch)
        with pytest.raises(RuntimeError, match="for-each-ref"):
            cleanup_targets(repo, _CONFIG, "main")

    def test_a_failed_worktree_listing_raises(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _failing_git("worktree", monkeypatch)
        with pytest.raises(RuntimeError, match="worktree list"):
            branch_cleanup.linked_worktrees(repo)

    def test_failed_status_and_listing_are_blockers(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _failing_git("status", monkeypatch)
        assert worktree_blockers(repo, _REGENERABLE) == ("<git status failed: boom>",)
        monkeypatch.undo()
        _failing_git("ls-files", monkeypatch)
        assert worktree_blockers(repo, _REGENERABLE) == ("<git ls-files failed: boom>",)

    def test_off_does_nothing(self, repo: Path) -> None:
        _merged(repo, "feat")
        report = cleanup_after_merge(repo, ["feat"], config=_CONFIG, target="main", mode="off")
        assert report == CleanupReport()
        assert "feat" in _branches(repo)

    def test_a_missing_or_unproven_branch_is_skipped(self, repo: Path) -> None:
        _unproven(repo, "novel")
        report = cleanup_after_merge(
            repo, ["ghost", "novel"], config=_CONFIG, target="main", mode="act"
        )
        assert report.deleted == ()
        assert [line.split(":")[0] for line in report.skipped] == ["ghost", "novel"]

    def test_a_refused_delete_is_reported(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _merged(repo, "feat")
        refused = DeletionReport(refused=True, blockers=("git said no",))

        def refuse(*_args: object, **_kwargs: object) -> DeletionReport:
            return refused

        monkeypatch.setattr(branch_cleanup, "delete_branches", refuse)
        report = cleanup_after_merge(repo, ["feat"], config=_CONFIG, target="main", mode="act")
        assert report.deleted == ()
        assert report.skipped == ("feat: git said no",)

    def test_no_default_branch_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "solo"
        path.mkdir()
        _git(path, "init", "-b", "work")
        _commit(path, "a.txt", "a\n", "A")
        with pytest.raises(ValueError, match="default branch"):
            clean_sweep(path, BranchesConfig(), dry_run=True, bundle_dir=tmp_path)

    def test_an_unproven_candidate_is_skipped(
        self, repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _merged(repo, "feat")

        def unproven(_repo: Path, name: str, **_kwargs: object) -> BranchClassification:
            return BranchClassification(name=name, tier=TIER_UNPROVEN, detail="nope")

        monkeypatch.setattr(branch_cleanup, "classify_branch", unproven)
        report = clean_sweep(repo, _CONFIG, dry_run=False, bundle_dir=tmp_path / "b")
        assert report.deleted == ()
        assert report.skipped == ("feat: nope",)

    def test_dry_run_names_the_worktree_it_would_remove(self, repo: Path, tmp_path: Path) -> None:
        _merged(repo, "feat")
        path = _worktree(repo, "feat")
        report = clean_sweep(repo, _CONFIG, dry_run=True, bundle_dir=tmp_path / "b")
        assert f"would remove the worktree {path}" in report.commands
        assert path.is_dir()

    def test_a_locked_worktree_is_skipped_before_git_is_asked(
        self, repo: Path, tmp_path: Path
    ) -> None:
        _merged(repo, "feat")
        path = _worktree(repo, "feat")
        _git(repo, "worktree", "lock", str(path))
        report = clean_sweep(repo, _CONFIG, dry_run=False, bundle_dir=tmp_path / "b")
        assert report.deleted == ()
        assert path.is_dir()
        assert any("locked by git" in line for line in report.skipped)

    def test_the_sweep_prints_the_remote_delete(self, repo: Path, tmp_path: Path) -> None:
        bare = tmp_path / "remote.git"
        _git(tmp_path, "init", "--quiet", "--bare", str(bare))
        _git(repo, "remote", "add", "origin", str(bare))
        _merged(repo, "feat")
        _git(repo, "push", "--quiet", "origin", "feat")
        report = clean_sweep(repo, _CONFIG, dry_run=False, bundle_dir=tmp_path / "b")
        assert "git push origin --delete feat" in report.commands


class TestDeleteIfMerged:
    """The WorktreeRemove branch step (Plan 00558 Task 3.2)."""

    def test_a_merged_branch_is_deleted_with_its_restore_line(self, repo: Path) -> None:
        tip = _merged(repo, "feat")
        report = branch_cleanup.delete_if_merged(repo, "feat", config=_CONFIG, default="main")
        assert report.deleted == ("feat",)
        assert report.commands == (f"git branch feat {tip}",)
        assert "feat" not in _branches(repo)

    def test_a_branch_merged_into_an_integration_line_is_deleted(self, repo: Path) -> None:
        _git(repo, "checkout", "-b", "release/1")
        _git(repo, "checkout", "main")
        _unproven(repo, "feat")
        _git(repo, "checkout", "release/1")
        _git(repo, "merge", "--no-ff", "-m", "Merge feat", "feat")
        _git(repo, "checkout", "main")
        report = branch_cleanup.delete_if_merged(repo, "feat", config=_CONFIG, default="main")
        assert report.deleted == ("feat",)

    def test_a_line_merged_into_the_default_is_deleted(self, repo: Path) -> None:
        tip = _merged(repo, "release/1")
        report = branch_cleanup.delete_if_merged(repo, "release/1", config=_CONFIG, default="main")
        assert report.deleted == ("release/1",)
        assert report.commands == (f"git branch release/1 {tip}",)
        assert "release/1" not in _branches(repo)

    def test_an_unmerged_line_is_refused_as_not_yet_merged_into_the_default(
        self, repo: Path
    ) -> None:
        _unproven(repo, "release/1")
        report = branch_cleanup.delete_if_merged(repo, "release/1", config=_CONFIG, default="main")
        assert report.deleted == ()
        assert "release/1" in _branches(repo)
        assert "integration line" in report.skipped[0]
        assert "not yet merged into" in report.skipped[0]

    def test_a_line_merged_only_into_another_line_is_refused(self, repo: Path) -> None:
        _unproven(repo, "release/1")
        _git(repo, "checkout", "-b", "release/2", "release/1")
        _commit(repo, "two.txt", "two\n", "Only on release/2")
        _git(repo, "checkout", "main")
        report = branch_cleanup.delete_if_merged(repo, "release/1", config=_CONFIG, default="main")
        assert report.deleted == ()
        assert {"release/1", "release/2"} <= _branches(repo)
        assert "not yet merged into" in report.skipped[0]

    def test_a_patch_equivalent_line_is_not_deleted(self, repo: Path) -> None:
        _patch_equivalent(repo, "release/1")
        report = branch_cleanup.delete_if_merged(repo, "release/1", config=_CONFIG, default="main")
        assert report.deleted == ()
        assert "release/1" in _branches(repo)

    def test_unmerged_and_patch_equivalent_are_left_for_the_sweep(self, repo: Path) -> None:
        _unproven(repo, "novel")
        _patch_equivalent(repo, "picked")
        for name in ("novel", "picked"):
            report = branch_cleanup.delete_if_merged(repo, name, config=_CONFIG, default="main")
            assert report.deleted == ()
            assert "branch-sweep --clean" in report.skipped[0]
        assert {"novel", "picked"} <= _branches(repo)

    def test_policy_refuses_an_exempt_branch(self, repo: Path) -> None:
        _merged(repo, "users/alice")
        report = branch_cleanup.delete_if_merged(
            repo, "users/alice", config=_CONFIG, default="main"
        )
        assert report.deleted == ()
        assert "users/alice" in _branches(repo)

    def test_a_branch_checked_out_elsewhere_is_refused_by_the_proof(self, repo: Path) -> None:
        _merged(repo, "feat")
        _worktree(repo, "feat")
        report = branch_cleanup.delete_if_merged(repo, "feat", config=_CONFIG, default="main")
        assert report.deleted == ()
        assert "feat" in _branches(repo)

    def test_a_refused_delete_is_reported(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _merged(repo, "feat")
        monkeypatch.setattr(
            branch_cleanup,
            "delete_branches",
            lambda *a, **k: DeletionReport(refused=True, blockers=("moved",)),
        )
        report = branch_cleanup.delete_if_merged(repo, "feat", config=_CONFIG, default="main")
        assert report.skipped == ("feat: moved",)
