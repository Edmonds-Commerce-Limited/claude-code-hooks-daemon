"""Tests for the post-merge and ``branch-sweep --clean`` cleanup (Plan 00558 Task 3.1).

Real repositories throughout: the subject is git's own reachability, worktree
and ignore semantics, which a mock would only restate.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

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
    def test_default_lines_exempt_and_protected_are_refused(self) -> None:
        assert policy_refusal("main", _CONFIG, "main") is not None
        assert policy_refusal("release/1.0", _CONFIG, "main") is not None
        assert policy_refusal("users/alice", _CONFIG, "main") is not None
        assert policy_refusal("develop", _CONFIG, "main") is not None
        assert policy_refusal("feature", _CONFIG, "main") is None

    def test_merge_target_must_be_default_or_a_line(self) -> None:
        assert merge_target_qualifies("main", _CONFIG, "main") is True
        assert merge_target_qualifies("release/2", _CONFIG, "main") is True
        assert merge_target_qualifies("feature", _CONFIG, "main") is False
        assert merge_target_qualifies(None, _CONFIG, "main") is False


class TestCleanupTargets:
    def test_only_existing_refs_are_targets(self, repo: Path) -> None:
        _git(repo, "branch", "release/1")
        assert cleanup_targets(repo, _CONFIG, "main") == ["main", "refs/heads/release/1"]


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

    def test_untracked_and_modified_files_block(self, repo: Path) -> None:
        _git(repo, "branch", "feat")
        path = _worktree(repo, "feat")
        (path / "new.txt").write_text("x\n", encoding="utf-8")
        (path / ".gitignore").write_text("changed\n", encoding="utf-8")
        assert set(worktree_blockers(path, _REGENERABLE)) == {"new.txt", ".gitignore"}


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
        assert "bin/hooks-daemon delete-branch feat --protected-ref main" in report.commands

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
        assert "bin/hooks-daemon branch-sweep --clean" in report.commands

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

    def test_a_locked_worktree_refusal_is_reported_verbatim(
        self, repo: Path, tmp_path: Path
    ) -> None:
        _merged(repo, "feat")
        path = _worktree(repo, "feat")
        _git(repo, "worktree", "lock", str(path))
        report = clean_sweep(repo, _CONFIG, dry_run=False, bundle_dir=tmp_path / "b")
        assert report.deleted == ()
        assert path.is_dir()
        assert any("git refused to remove" in line for line in report.skipped)

    def test_the_sweep_prints_the_remote_delete(self, repo: Path, tmp_path: Path) -> None:
        bare = tmp_path / "remote.git"
        _git(tmp_path, "init", "--quiet", "--bare", str(bare))
        _git(repo, "remote", "add", "origin", str(bare))
        _merged(repo, "feat")
        _git(repo, "push", "--quiet", "origin", "feat")
        report = clean_sweep(repo, _CONFIG, dry_run=False, bundle_dir=tmp_path / "b")
        assert "git push origin --delete feat" in report.commands
