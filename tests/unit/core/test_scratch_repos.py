"""Classifying the repositories inside a scratch entry (Plan 00627 Tasks 2.1 and 2.2).

Every test builds real repositories: a project pushed to a bare ``origin`` and
nested repositories under its scratch root. The remote is a local path, so
``git ls-remote`` answers without a network.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.scratch_repos import (
    NESTED_GIT_ENV,
    GitRunner,
    LiveTips,
    ProjectGit,
    RepoFindings,
    RepoKind,
    blob_id,
    build_project_git,
    classify_entry,
)
from claude_code_hooks_daemon.core.scratch_walk import WalkBudget, walk_entry
from claude_code_hooks_daemon.utils.git_repo import GIT_TIMED_OUT, run_git
from tests.support.scratch_tree import GitProject, build_git_project, commit_file, git


def _project_git(
    gp: GitProject, *, runner: GitRunner = run_git, live_tips: LiveTips | None = None
) -> ProjectGit:
    if live_tips is None:
        return build_project_git(gp.project, remote="origin", default_branch="main", runner=runner)
    return build_project_git(
        gp.project, remote="origin", default_branch="main", runner=runner, live_tips=live_tips
    )


def _classify(
    gp: GitProject,
    name: str,
    *,
    project: ProjectGit | None = None,
    runner: GitRunner = run_git,
) -> RepoFindings:
    walk = walk_entry(
        gp.tree.root, name, now=0.0, budget=WalkBudget(seconds=60, max_inodes=100_000)
    )
    assert walk.complete, walk.reason
    return classify_entry(
        gp.tree.root,
        name,
        nodes=tuple(node.path for node in walk.value.nodes),
        markers=walk.value.git_markers,
        project=project or _project_git(gp),
        runner=runner,
    )


@pytest.fixture
def gp(tmp_path: Path) -> GitProject:
    return build_git_project(tmp_path)


class TestStandalone:
    def test_a_fresh_unrelated_repository_is_standalone(self, gp: GitProject) -> None:
        gp.standalone("e/repo")
        findings = _classify(gp, "e")
        assert findings.kinds == {"e/repo/.git": RepoKind.STANDALONE}
        assert findings.stuck == ()
        assert findings.protected == ()
        assert findings.p4_covered == ()
        assert findings.standalone_roots == ("e/repo",)

    def test_a_standalone_root_inside_a_related_clone_names_both_roots(
        self, gp: GitProject
    ) -> None:
        gp.clone("e")
        gp.standalone("e/sub")
        findings = _classify(gp, "e")
        assert findings.standalone_roots == ("e/sub",)
        assert findings.other_roots == ("e",)

    def test_an_empty_repository_with_no_commit_is_standalone(self, gp: GitProject) -> None:
        gp.standalone("e", commit=False)
        assert _classify(gp, "e").kinds == {"e/.git": RepoKind.STANDALONE}

    def test_a_linked_worktree_inside_the_entry_is_judged_with_its_parent(
        self, gp: GitProject
    ) -> None:
        parent = gp.standalone("e/main")
        git(parent, "worktree", "add", "-q", "-b", "side", str(gp.tree.root / "e" / "side"))
        findings = _classify(gp, "e")
        assert set(findings.kinds.values()) == {RepoKind.STANDALONE}
        assert findings.stuck == ()
        assert findings.standalone_roots == (
            "e/main",
            "e/main/.git/worktrees/side",
            "e/side",
        )


class TestNotARepository:
    def test_an_empty_dot_git_directory_is_stuck_not_standalone(self, gp: GitProject) -> None:
        gp.tree.git_marker("e")
        gp.tree.file("e/a.txt")
        findings = _classify(gp, "e")
        assert findings.kinds["e/.git"] is RepoKind.BROKEN
        assert findings.stuck

    def test_a_broken_marker_never_answers_for_the_enclosing_project(self, gp: GitProject) -> None:
        # git -C <dir> on a fake .git would walk up and report the project itself.
        gp.tree.git_marker("e/fake")
        findings = _classify(gp, "e")
        assert RepoKind.RELATED not in findings.kinds.values()
        assert RepoKind.STANDALONE not in findings.kinds.values()


class TestInProgress:
    @pytest.mark.parametrize(
        "rel",
        ["index.lock", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "HEAD.lock"],
    )
    def test_an_in_progress_file_makes_the_entry_stuck(self, gp: GitProject, rel: str) -> None:
        repo = gp.standalone("e")
        (repo / ".git" / rel).write_text("x\n")
        findings = _classify(gp, "e")
        assert findings.stuck
        assert "in progress" in " ".join(findings.stuck)

    @pytest.mark.parametrize("rel", ["rebase-merge", "rebase-apply"])
    def test_an_in_progress_directory_makes_the_entry_stuck(self, gp: GitProject, rel: str) -> None:
        repo = gp.standalone("e")
        (repo / ".git" / rel).mkdir()
        (repo / ".git" / rel / "x").write_text("x")
        assert _classify(gp, "e").stuck


class TestUntrustedConfig:
    def _sentinel_script(self, gp: GitProject) -> tuple[Path, Path]:
        sentinel = gp.tree.outside / "ran"
        script = gp.tree.outside / "hook.sh"
        script.write_text(f"#!/bin/sh\ntouch {sentinel}\ncat\n")
        script.chmod(0o755)
        return script, sentinel

    def test_an_fsmonitor_command_is_never_run(self, gp: GitProject) -> None:
        script, sentinel = self._sentinel_script(gp)
        repo = gp.clone("e")
        git(repo, "config", "core.fsmonitor", str(script))
        findings = _classify(gp, "e")
        assert findings.stuck
        assert not sentinel.exists()

    def test_a_clean_filter_is_never_run(self, gp: GitProject) -> None:
        script, sentinel = self._sentinel_script(gp)
        repo = gp.clone("e")
        (repo / ".gitattributes").write_text("*.py filter=evil\n")
        git(repo, "config", "filter.evil.clean", str(script))
        (repo / "src" / "app.py").write_text("changed\n")
        findings = _classify(gp, "e")
        assert findings.stuck
        assert not sentinel.exists()

    def test_an_include_makes_the_entry_stuck(self, gp: GitProject) -> None:
        repo = gp.standalone("e")
        git(repo, "config", "include.path", str(gp.tree.outside / "more.cfg"))
        assert _classify(gp, "e").stuck

    def test_a_stat_dirty_tracked_file_does_not_rewrite_the_nested_index(
        self, gp: GitProject
    ) -> None:
        repo = gp.clone("e")
        tracked = repo / "src" / "app.py"
        os.utime(tracked, (1_000_000, 1_000_000))  # stat-dirty, content unchanged
        index = repo / ".git" / "index"
        before = os.lstat(index)
        _classify(gp, "e")
        after = os.lstat(index)
        assert (after.st_ino, after.st_mtime_ns, after.st_ctime_ns) == (
            before.st_ino,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )

    def test_control_the_same_fixture_with_optional_locks_on_does_rewrite_the_index(
        self, gp: GitProject
    ) -> None:
        """Mutation check: without the no-optional-locks guard the index IS rewritten,
        so the test above can fail and is not vacuous."""
        repo = gp.clone("e")
        os.utime(repo / "src" / "app.py", (1_000_000, 1_000_000))
        index = repo / ".git" / "index"
        before = os.lstat(index)
        env = {**NESTED_GIT_ENV, "GIT_OPTIONAL_LOCKS": "1"}
        subprocess.run(  # nosec B603 B607 - fixed argv, test fixture only
            ["git", f"--git-dir={repo / '.git'}", f"--work-tree={repo}", "status", "--porcelain"],
            check=True,
            capture_output=True,
            env={**{k: v for k, v in os.environ.items() if not k.startswith("GIT_")}, **env},
        )
        after = os.lstat(index)
        assert (after.st_ino, after.st_mtime_ns) != (before.st_ino, before.st_mtime_ns)


class TestRelated:
    def test_a_clean_pushed_clone_is_covered_by_p4(self, gp: GitProject) -> None:
        gp.clone("e")
        findings = _classify(gp, "e")
        assert findings.kinds == {"e/.git": RepoKind.RELATED}
        assert findings.protected == ()
        assert findings.stuck == ()
        assert "e/.git" in findings.p4_covered
        assert "e/src/app.py" in findings.p4_covered
        assert "e/.gitignore" in findings.p4_covered

    def test_an_unpushed_commit_protects_the_entry(self, gp: GitProject) -> None:
        repo = gp.clone("e")
        commit_file(repo, "new.txt", "only here\n")
        findings = _classify(gp, "e")
        assert findings.protected
        assert findings.p4_covered == ()

    def test_a_forged_remote_tracking_ref_inside_the_clone_proves_nothing(
        self, gp: GitProject
    ) -> None:
        repo = gp.clone("e")
        sha = commit_file(repo, "new.txt", "only here\n")
        git(repo, "update-ref", "refs/remotes/origin/main", sha)
        assert _classify(gp, "e").protected

    def test_a_dirty_tracked_file_protects_the_entry(self, gp: GitProject) -> None:
        repo = gp.clone("e")
        (repo / "src" / "app.py").write_text("edited\n")
        assert _classify(gp, "e").protected

    def test_a_staged_change_protects_the_entry(self, gp: GitProject) -> None:
        repo = gp.clone("e")
        (repo / "added.txt").write_text("new\n")
        git(repo, "add", "added.txt")
        assert _classify(gp, "e").protected

    @pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
    def test_an_edit_hidden_from_status_by_an_index_flag_protects_the_entry(
        self, gp: GitProject, flag: str
    ) -> None:
        repo = gp.clone("e")
        git(repo, "update-index", flag, "src/app.py")
        (repo / "src" / "app.py").write_text("edited, but status will not say so\n")
        findings = _classify(gp, "e")
        assert findings.protected
        assert findings.p4_covered == ()

    def test_a_clean_pushed_clone_covers_only_its_git_directory_by_prefix(
        self, gp: GitProject
    ) -> None:
        gp.clone("e")
        assert _classify(gp, "e").p4_git_dirs == ("e/.git",)

    def test_a_stash_protects_the_entry(self, gp: GitProject) -> None:
        repo = gp.clone("e")
        (repo / "src" / "app.py").write_text("edited\n")
        git(repo, "stash", "-q")
        assert _classify(gp, "e").protected

    def test_a_clone_with_its_remote_removed_is_still_related(self, gp: GitProject) -> None:
        repo = gp.clone("e")
        git(repo, "remote", "remove", "origin")
        commit_file(repo, "new.txt", "only here\n")
        findings = _classify(gp, "e")
        assert findings.kinds["e/.git"] is RepoKind.RELATED
        assert findings.protected

    def test_a_shallow_clone_with_no_remote_is_related_not_standalone(self, gp: GitProject) -> None:
        commit_file(gp.project, "second.txt", "two\n")
        git(gp.project, "push", "-q", "origin", "main")
        target = gp.tree.root / "e"
        git(gp.tree.root, "clone", "-q", "--depth", "1", f"file://{gp.remote}", str(target))
        git(target, "remote", "remove", "origin")
        commit_file(target, "local.txt", "local\n")
        findings = _classify(gp, "e")
        assert findings.kinds["e/.git"] is RepoKind.RELATED
        assert findings.protected

    def test_no_live_remote_answer_means_nothing_is_proved_pushed(self, gp: GitProject) -> None:
        gp.clone("e")

        def no_answer(directory: Path, remote: str, names: list[str]) -> dict[str, str]:
            return {}

        findings = _classify(gp, "e", project=_project_git(gp, live_tips=no_answer))
        assert findings.protected
        assert findings.p4_covered == ()


class TestWorktreesAndOutsidePointers:
    def test_a_registered_worktree_of_the_project_is_protected(self, gp: GitProject) -> None:
        gp.worktree("wt", "feature")
        findings = _classify(gp, "wt")
        assert findings.kinds == {"wt/.git": RepoKind.REGISTERED_WORKTREE}
        assert findings.protected
        assert "git worktree remove" in " ".join(findings.protected)

    def test_a_dot_git_file_pointing_outside_is_protected(self, gp: GitProject) -> None:
        gp.tree.git_marker("e", gitdir=str(gp.tree.outside / "elsewhere.git"))
        findings = _classify(gp, "e")
        assert findings.kinds == {"e/.git": RepoKind.OUTSIDE_POINTING}
        assert findings.protected

    def test_a_mixed_entry_with_a_worktree_is_protected(self, gp: GitProject) -> None:
        gp.standalone("e/throwaway")
        gp.worktree("e/wt", "feature")
        findings = _classify(gp, "e")
        assert findings.kinds["e/throwaway/.git"] is RepoKind.STANDALONE
        assert findings.kinds["e/wt/.git"] is RepoKind.REGISTERED_WORKTREE
        assert findings.protected

    def test_the_same_entry_without_the_worktree_is_not_protected(self, gp: GitProject) -> None:
        gp.standalone("e/throwaway")
        assert _classify(gp, "e").protected == ()


def _injecting(subcommand: str, mode: str) -> GitRunner:
    def runner(
        cwd: Path, *args: str, timeout: float = 30.0, env: Mapping[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        if subcommand in args:
            if mode == "fail":
                return subprocess.CompletedProcess(["git"], 128, "", "injected failure")
            if mode == "timeout":
                return subprocess.CompletedProcess(["git"], GIT_TIMED_OUT, "", "timed out")
            return subprocess.CompletedProcess(["git"], 0, "garbage\x00more garbage\n", "")
        return run_git(cwd, *args, timeout=timeout, env=env)

    return runner


_SUBCOMMANDS = (
    "rev-parse",
    "config",
    "rev-list",
    "for-each-ref",
    "status",
    "ls-files",
    "worktree",
    "ls-remote",
)

#: Subcommands the standalone path never runs, so injecting into them changes nothing.
_NOT_ON_THE_STANDALONE_PATH = frozenset({"status", "ls-files", "worktree", "ls-remote"})

#: Subcommands that decide whether a clone with a remote is pushed. ``rev-list`` and
#: ``worktree`` are not on that path: a remote alone makes a clone related.
_ON_THE_PUSHED_CLONE_PATH = ("rev-parse", "config", "for-each-ref", "status", "ls-remote")


class TestWrongVerdictControls:
    @pytest.mark.parametrize("mode", ["fail", "timeout"])
    @pytest.mark.parametrize("subcommand", _SUBCOMMANDS)
    def test_a_git_failure_never_reads_as_standalone(
        self, gp: GitProject, subcommand: str, mode: str
    ) -> None:
        gp.standalone("e")
        runner = _injecting(subcommand, mode)
        findings = _classify(gp, "e", project=_project_git(gp, runner=runner), runner=runner)
        if subcommand in _NOT_ON_THE_STANDALONE_PATH:
            assert findings.kinds["e/.git"] is RepoKind.STANDALONE
        else:
            assert findings.stuck
            assert RepoKind.STANDALONE not in findings.kinds.values()

    @pytest.mark.parametrize("mode", ["fail", "timeout", "garbage"])
    @pytest.mark.parametrize("subcommand", _ON_THE_PUSHED_CLONE_PATH)
    def test_a_git_failure_never_proves_a_clone_pushed(
        self, gp: GitProject, subcommand: str, mode: str
    ) -> None:
        gp.clone("e")
        runner = _injecting(subcommand, mode)
        findings = _classify(gp, "e", project=_project_git(gp, runner=runner), runner=runner)
        assert findings.stuck or findings.protected
        assert findings.p4_covered == ()

    @pytest.mark.parametrize("mode", ["fail", "timeout"])
    def test_a_failed_tracked_listing_makes_a_pushed_clone_stuck(
        self, gp: GitProject, mode: str
    ) -> None:
        gp.clone("e")
        runner = _injecting("ls-files", mode)
        findings = _classify(gp, "e", runner=runner)
        assert findings.stuck
        assert findings.p4_covered == ()

    def test_a_garbage_tracked_listing_makes_a_pushed_clone_stuck(self, gp: GitProject) -> None:
        gp.clone("e")
        findings = _classify(gp, "e", runner=_injecting("ls-files", "garbage"))
        assert findings.stuck
        assert findings.p4_covered == ()

    def test_a_listed_path_the_walk_did_not_see_covers_nothing(self, gp: GitProject) -> None:
        # Git is trusted to list what the index tracks; a listed name the walk never
        # saw must not widen coverage.
        gp.clone("e")

        def inventing(
            cwd: Path, *args: str, timeout: float = 30.0, env: Mapping[str, str] | None = None
        ) -> subprocess.CompletedProcess[str]:
            if "ls-files" in args:
                return subprocess.CompletedProcess(["git"], 0, "H invented.txt\x00", "")
            return run_git(cwd, *args, timeout=timeout, env=env)

        findings = _classify(gp, "e", runner=inventing)
        assert findings.p4_covered == ("e/.git",)

    def test_a_bare_repository_with_unpushed_work_is_protected(self, gp: GitProject) -> None:
        bare = gp.tree.root / "e" / "b.git"
        git(gp.tree.root, "clone", "-q", "--bare", str(gp.remote), str(bare))
        work = gp.tree.outside / "work"
        git(gp.tree.outside, "clone", "-q", str(gp.remote), str(work))
        commit_file(work, "new.txt", "only in the bare repository\n")
        git(work, "push", "-q", str(bare), "main")
        findings = _classify(gp, "e")
        assert findings.kinds == {"e/b.git": RepoKind.RELATED}
        assert findings.protected


class TestBlobId:
    """The in-process blob hash P3 and the dirty-file check use (Plan 00627 Task 2.3)."""

    @pytest.mark.parametrize(
        "content", [b"", b"line\r\nother\r\n", b"\x00\xffbinary", b"plain text\n"]
    )
    def test_it_matches_git_hash_object_no_filters(self, tmp_path: Path, content: bytes) -> None:
        path = tmp_path / "f"
        path.write_bytes(content)
        expected = git(tmp_path, "hash-object", "--no-filters", "--", str(path)).strip()
        assert blob_id(path, sha_length=40) == expected

    def test_it_matches_a_sha256_repository(self, tmp_path: Path) -> None:
        path = tmp_path / "f"
        path.write_bytes(b"abc\n")
        expected = hashlib.sha256(b"blob 4\x00abc\n").hexdigest()
        assert blob_id(path, sha_length=64) == expected

    def test_a_link_is_never_followed(self, tmp_path: Path) -> None:
        target = tmp_path / "target"
        target.write_bytes(b"x")
        (tmp_path / "link").symlink_to(target)
        assert blob_id(tmp_path / "link", sha_length=40) is None

    def test_a_fifo_is_not_hashed(self, tmp_path: Path) -> None:
        os.mkfifo(tmp_path / "fifo")
        assert blob_id(tmp_path / "fifo", sha_length=40) is None

    def test_an_unknown_sha_length_proves_nothing(self, tmp_path: Path) -> None:
        (tmp_path / "f").write_bytes(b"x")
        assert blob_id(tmp_path / "f", sha_length=41) is None

    def test_a_missing_file_proves_nothing(self, tmp_path: Path) -> None:
        assert blob_id(tmp_path / "absent", sha_length=40) is None
