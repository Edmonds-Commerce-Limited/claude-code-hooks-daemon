"""Tests for the git_sync utility (Plan 00178).

git_sync is the focused home for the upstream-sync git operations the
``git_upstream_checker`` SessionStart handler needs: resolve the current branch
and its upstream, count ahead/behind, check the working tree is clean, run an
additive ``git fetch --all`` (never ``--prune`` — Plan 00179), detect local
branches whose upstream was deleted on the remote, and perform a safe
``git pull --ff-only``.

These tests init real git repos (with a local bare "remote") in tmp_path so the
production subprocess path is exercised end to end. Failure / env-assertion
paths use monkeypatch.
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils import git_sync

_TIMEOUT = Timeout.GIT_CONTEXT


def _run(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=Timeout.GIT_FETCH_BACKGROUND,
    )
    return result.stdout.strip()


def _configure_identity(repo: Path) -> None:
    _run(repo, "config", "user.email", "t@t")
    _run(repo, "config", "user.name", "tester")
    _run(repo, "config", "commit.gpgsign", "false")


def _commit(repo: Path, name: str, content: str) -> None:
    (repo / name).write_text(content)
    _run(repo, "add", name)
    _run(repo, "commit", "-m", f"add {name}")


def _make_remote_and_clone(tmp_path: Path) -> tuple[Path, Path]:
    """Create a bare remote with one commit on ``main`` and a tracking clone.

    Returns (remote_bare, clone) where clone's ``main`` tracks ``origin/main``
    and is exactly in sync.
    """
    seed = tmp_path / "seed"
    seed.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(seed)],
        capture_output=True,
        check=True,
        timeout=_TIMEOUT,
    )
    _configure_identity(seed)
    _commit(seed, "README.md", "seed\n")

    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "clone", "--bare", str(seed), str(remote)],
        capture_output=True,
        check=True,
        timeout=_TIMEOUT,
    )

    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(remote), str(clone)],
        capture_output=True,
        check=True,
        timeout=_TIMEOUT,
    )
    _configure_identity(clone)
    return remote, clone


def _advance_remote(tmp_path: Path, remote: Path, *, commits: int = 1) -> None:
    """Push ``commits`` new commits to the remote via a throwaway clone."""
    pusher = tmp_path / "pusher"
    if not pusher.exists():
        subprocess.run(
            ["git", "clone", str(remote), str(pusher)],
            capture_output=True,
            check=True,
            timeout=_TIMEOUT,
        )
        _configure_identity(pusher)
    for i in range(commits):
        _commit(pusher, f"remote_{i}.txt", f"remote change {i}\n")
    _run(pusher, "push", "origin", "main")


def _status(repo: Path) -> git_sync.UpstreamStatus:
    """Assert-non-None helper so tests stay free of type: ignore."""
    status = git_sync.upstream_status(repo)
    assert status is not None
    return status


class TestCurrentBranch:
    def test_returns_branch_name(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        assert git_sync.current_branch(clone) == "main"

    def test_returns_none_when_detached(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        head = _run(clone, "rev-parse", "HEAD")
        _run(clone, "checkout", head)
        assert git_sync.current_branch(clone) is None

    def test_returns_none_when_not_a_repo(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert git_sync.current_branch(plain) is None


class TestUpstreamRef:
    def test_returns_tracking_ref(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        assert git_sync.upstream_ref(clone) == "origin/main"

    def test_returns_none_when_no_upstream(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        _run(clone, "checkout", "-b", "local-only")
        assert git_sync.upstream_ref(clone) is None

    def test_returns_none_when_not_a_repo(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert git_sync.upstream_ref(plain) is None


class TestUpstreamStatus:
    def test_in_sync(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        status = _status(clone)
        assert status.branch == "main"
        assert status.upstream == "origin/main"
        assert status.behind == 0
        assert status.ahead == 0

    def test_behind_after_remote_advances_and_fetch(self, tmp_path: Path) -> None:
        remote, clone = _make_remote_and_clone(tmp_path)
        _advance_remote(tmp_path, remote, commits=2)
        assert git_sync.fetch_all(clone) is True
        status = _status(clone)
        assert status.behind == 2
        assert status.ahead == 0

    def test_ahead_after_local_commit(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        _commit(clone, "local.txt", "local\n")
        status = _status(clone)
        assert status.behind == 0
        assert status.ahead == 1

    def test_diverged(self, tmp_path: Path) -> None:
        remote, clone = _make_remote_and_clone(tmp_path)
        _advance_remote(tmp_path, remote, commits=1)
        git_sync.fetch_all(clone)
        _commit(clone, "local.txt", "local\n")
        status = _status(clone)
        assert status.behind == 1
        assert status.ahead == 1

    def test_none_when_detached(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        head = _run(clone, "rev-parse", "HEAD")
        _run(clone, "checkout", head)
        assert git_sync.upstream_status(clone) is None

    def test_none_when_no_upstream(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        _run(clone, "checkout", "-b", "local-only")
        assert git_sync.upstream_status(clone) is None

    def test_none_when_not_a_repo(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert git_sync.upstream_status(plain) is None


class _FakeCompleted:
    """Minimal CompletedProcess stand-in for defensive-branch tests."""

    def __init__(self, returncode: int, stdout: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


class TestUpstreamStatusDefensive:
    """Cover the defensive rev-list branches unreachable via real git."""

    def _patch_branch_and_upstream(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(git_sync, "current_branch", lambda _cwd: "main")
        monkeypatch.setattr(git_sync, "upstream_ref", lambda _cwd: "origin/main")

    def test_none_when_rev_list_returns_nonzero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_branch_and_upstream(monkeypatch)
        monkeypatch.setattr(git_sync, "_run_git", lambda *_a, **_k: _FakeCompleted(1, ""))
        assert git_sync.upstream_status(tmp_path) is None

    def test_none_when_rev_list_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_branch_and_upstream(monkeypatch)
        monkeypatch.setattr(git_sync, "_run_git", lambda *_a, **_k: None)
        assert git_sync.upstream_status(tmp_path) is None

    def test_none_when_field_count_wrong(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_branch_and_upstream(monkeypatch)
        monkeypatch.setattr(git_sync, "_run_git", lambda *_a, **_k: _FakeCompleted(0, "5"))
        assert git_sync.upstream_status(tmp_path) is None

    def test_none_when_fields_not_integers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_branch_and_upstream(monkeypatch)
        monkeypatch.setattr(git_sync, "_run_git", lambda *_a, **_k: _FakeCompleted(0, "x\ty"))
        assert git_sync.upstream_status(tmp_path) is None


class TestWorkingTreeClean:
    def test_clean_repo(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        assert git_sync.working_tree_clean(clone) is True

    def test_dirty_with_untracked(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        (clone / "new.txt").write_text("x\n")
        assert git_sync.working_tree_clean(clone) is False

    def test_dirty_with_modified(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        (clone / "README.md").write_text("changed\n")
        assert git_sync.working_tree_clean(clone) is False

    def test_not_a_repo_is_not_clean(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert git_sync.working_tree_clean(plain) is False


class TestFetchAll:
    def test_fetch_updates_remote_tracking_ref(self, tmp_path: Path) -> None:
        remote, clone = _make_remote_and_clone(tmp_path)
        _advance_remote(tmp_path, remote, commits=1)
        # Before fetch the clone still sees itself in sync.
        assert _status(clone).behind == 0
        assert git_sync.fetch_all(clone) is True
        assert _status(clone).behind == 1

    def test_returns_false_when_not_a_repo(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert git_sync.fetch_all(plain) is False

    def test_fail_silent_on_subprocess_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, clone = _make_remote_and_clone(tmp_path)

        def _raise(*_a: object, **_k: object) -> None:
            raise OSError("git missing")

        monkeypatch.setattr(subprocess, "run", _raise)
        assert git_sync.fetch_all(clone) is False

    def test_fail_silent_on_timeout(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, clone = _make_remote_and_clone(tmp_path)

        def _timeout(*_a: object, **_k: object) -> None:
            raise subprocess.TimeoutExpired(cmd="git fetch", timeout=Timeout.GIT_FETCH_SESSION)

        monkeypatch.setattr(subprocess, "run", _timeout)
        assert git_sync.fetch_all(clone) is False

    def test_is_additive_never_prunes_and_noninteractive_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """fetch_all is purely additive: --all, and NEVER --prune (Plan 00179)."""
        _, clone = _make_remote_and_clone(tmp_path)
        captured: dict[str, Any] = {}

        class _Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        def _capture(cmd: list[str], **kwargs: Any) -> _Completed:
            captured["cmd"] = cmd
            captured["env"] = kwargs.get("env")
            return _Completed()

        monkeypatch.setattr(subprocess, "run", _capture)
        git_sync.fetch_all(clone)
        cmd = captured["cmd"]
        assert "fetch" in cmd
        assert "--all" in cmd
        assert "--prune" not in cmd  # must never prune automatically
        # --no-prune is passed explicitly so the additive guarantee holds even
        # when the user has fetch.prune=true configured (Plan 00179).
        assert "--no-prune" in cmd
        env = captured["env"]
        assert isinstance(env, dict)
        assert env.get("GIT_TERMINAL_PROMPT") == "0"


class TestPullFfOnly:
    def test_fast_forward_success(self, tmp_path: Path) -> None:
        remote, clone = _make_remote_and_clone(tmp_path)
        _advance_remote(tmp_path, remote, commits=2)
        git_sync.fetch_all(clone)
        result = git_sync.pull_ff_only(clone)
        assert result.ok is True
        assert _status(clone).behind == 0

    def test_non_fast_forward_fails_gracefully(self, tmp_path: Path) -> None:
        remote, clone = _make_remote_and_clone(tmp_path)
        _advance_remote(tmp_path, remote, commits=1)
        git_sync.fetch_all(clone)
        _commit(clone, "local.txt", "diverge\n")  # now diverged -> ff impossible
        result = git_sync.pull_ff_only(clone)
        assert result.ok is False
        assert result.detail  # non-empty reason

    def test_fail_silent_on_subprocess_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, clone = _make_remote_and_clone(tmp_path)

        def _raise(*_a: object, **_k: object) -> None:
            raise OSError("git missing")

        monkeypatch.setattr(subprocess, "run", _raise)
        result = git_sync.pull_ff_only(clone)
        assert result.ok is False


def _make_gone_branch(
    tmp_path: Path,
    *,
    unique_commit: bool,
    shadow_tag: bool = False,
    shadow_base_tag: bool = False,
) -> Path:
    """Return a clone with a local branch ``feature`` whose upstream was deleted.

    ``origin/feature`` is pushed then deleted on the remote; the clone still
    holds the stale ``origin/feature`` ref (we never prune). When
    ``unique_commit`` is True the local ``feature`` carries a commit not on
    ``main`` (so it is NOT merged into the default branch).

    ``shadow_tag`` additionally creates a TAG called ``feature``, which makes the
    bare branch name AMBIGUOUS: git resolves the tag ahead of the branch. No
    fixture here creates a tag, which is why the ``%(refname:short)`` bug was
    invisible to this suite (Plan 00255).

    ``shadow_base_tag`` shadows the DEFAULT branch name instead, pointing the tag
    at ``feature``'s tip — so a merged-ness question asked with the bare base
    name is answered about the tag.
    """
    remote, clone = _make_remote_and_clone(tmp_path)
    pusher = tmp_path / "feature_pusher"
    subprocess.run(
        ["git", "clone", str(remote), str(pusher)],
        capture_output=True,
        check=True,
        timeout=_TIMEOUT,
    )
    _configure_identity(pusher)
    _run(pusher, "checkout", "-b", "feature")
    if unique_commit:
        _commit(pusher, "feat.txt", "feat\n")
    _run(pusher, "push", "origin", "feature")

    # Clone: create a local branch tracking origin/feature, then return to main.
    _run(clone, "fetch", "origin")
    _run(clone, "checkout", "feature")
    _run(clone, "checkout", "main")

    if shadow_tag:
        _run(clone, "tag", "feature", "main")
    if shadow_base_tag:
        # A tag named after the DEFAULT branch, pointing at feature's tip.
        _run(clone, "tag", "main", "feature")

    # Delete feature on the remote. The clone keeps the stale origin/feature ref.
    _run(pusher, "push", "origin", "--delete", "feature")
    return clone


class TestDefaultBranch:
    def test_returns_main_for_clone(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        assert git_sync.default_branch(clone) == "main"

    def test_none_when_not_a_repo(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert git_sync.default_branch(plain) is None


class TestGoneBranches:
    def test_none_when_nothing_deleted(self, tmp_path: Path) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        assert git_sync.gone_branches(clone) == []

    def test_detects_merged_gone_branch(self, tmp_path: Path) -> None:
        clone = _make_gone_branch(tmp_path, unique_commit=False)
        gone = git_sync.gone_branches(clone)
        assert len(gone) == 1
        assert gone[0].name == "feature"
        assert gone[0].upstream == "origin/feature"
        assert gone[0].merged is True  # no unique commits -> safe to delete

    def test_detects_unmerged_gone_branch(self, tmp_path: Path) -> None:
        clone = _make_gone_branch(tmp_path, unique_commit=True)
        gone = git_sync.gone_branches(clone)
        assert len(gone) == 1
        assert gone[0].name == "feature"
        assert gone[0].merged is False  # has unique commit -> needs confirmation

    def test_empty_when_not_a_repo(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert git_sync.gone_branches(plain) == []

    def test_fail_silent_on_subprocess_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, clone = _make_remote_and_clone(tmp_path)

        def _raise(*_a: object, **_k: object) -> None:
            raise OSError("git missing")

        monkeypatch.setattr(subprocess, "run", _raise)
        assert git_sync.gone_branches(clone) == []


class TestASameNamedTagCannotDisguiseAGoneBranch:
    """A tag shadowing a branch must not change the NAME the advisory reports.

    ``%(refname:short)`` returns the shortest UNAMBIGUOUS name, so a branch
    shadowed by a same-named tag comes back as ``heads/feature`` — a string that
    is not a branch name and that no git command accepts (Plan 00255).
    """

    def test_the_reported_name_is_the_branch_name(self, tmp_path: Path) -> None:
        clone = _make_gone_branch(tmp_path, unique_commit=False, shadow_tag=True)
        gone = git_sync.gone_branches(clone)
        assert [g.name for g in gone] == ["feature"]

    def test_the_cleanup_command_the_advisory_offers_actually_works(self, tmp_path: Path) -> None:
        """The advisory renders ``git branch -d <name>`` — so <name> must be usable.

        This is the consequence that matters: with the shortest-unambiguous name
        the offered command fails with "branch 'heads/feature' not found", and a
        human following the guidance is simply stuck.
        """
        clone = _make_gone_branch(tmp_path, unique_commit=False, shadow_tag=True)
        (gone,) = git_sync.gone_branches(clone)
        assert gone.merged is True

        deleted = subprocess.run(
            ["git", "branch", "-d", gone.name],
            cwd=clone,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        assert deleted.returncode == 0, deleted.stderr

    def test_classification_still_agrees_with_itself(self, tmp_path: Path) -> None:
        """Both listings read the same field, so merged/not-merged stays correct.

        Guards the half-fix: correcting one listing and not the other would
        desynchronise them and turn a cosmetic bug into a wrong verdict.
        """
        clone = _make_gone_branch(tmp_path, unique_commit=True, shadow_tag=True)
        (gone,) = git_sync.gone_branches(clone)
        assert gone.name == "feature"
        assert gone.merged is False  # has a unique commit -> needs confirmation


class TestASameNamedTagCannotFlipTheMergedVerdict:
    """The merged/not-merged verdict must be measured against the BRANCH.

    ``default_branch`` returns a bare name, and ``git branch --merged main``
    answers about whatever ``main`` resolves to — a tag first. This is the same
    ambiguity as the naming bug above but a materially worse consequence: the
    advisory renders "safe to remove: `git branch -d <name>`" for a branch that
    holds commits nobody else has (Plan 00255, reproduced).
    """

    def test_unmerged_work_is_not_reported_as_safe_to_remove(self, tmp_path: Path) -> None:
        clone = _make_gone_branch(tmp_path, unique_commit=True, shadow_base_tag=True)
        (gone,) = git_sync.gone_branches(clone)
        assert gone.name == "feature"
        assert gone.merged is False

    def test_the_base_is_qualified_when_a_local_branch_of_that_name_exists(
        self, tmp_path: Path
    ) -> None:
        _, clone = _make_remote_and_clone(tmp_path)
        assert git_sync._merged_base_ref(clone, "main") == "refs/heads/main"

    def test_the_base_falls_back_to_the_bare_name_when_it_has_no_local_branch(
        self, tmp_path: Path
    ) -> None:
        """The fallback is the half of the fix that a blind qualification would lose.

        ``default_branch`` can name a branch it read from ``origin/HEAD`` that was
        never checked out here. ``refs/heads/<base>`` is then a malformed object
        name (git exits 128) while the bare name still resolves, so qualifying
        unconditionally would empty the merged set and report every gone branch as
        unmerged. Asserted directly because no end-to-end test would fail if the
        fallback were deleted.
        """
        _, clone = _make_remote_and_clone(tmp_path)
        assert git_sync._merged_base_ref(clone, "no-such-branch") == "no-such-branch"


class TestDefaultBranchDefensive:
    def test_falls_back_to_local_main(self, tmp_path: Path) -> None:
        # A plain repo with no origin/HEAD must fall back to local `main`.
        repo = tmp_path / "plain_repo"
        repo.mkdir()
        subprocess.run(
            ["git", "init", "-b", "main", str(repo)],
            capture_output=True,
            check=True,
            timeout=_TIMEOUT,
        )
        _configure_identity(repo)
        _commit(repo, "f.txt", "x\n")
        assert git_sync.default_branch(repo) == "main"

    def test_none_when_symbolic_ref_empty_and_no_local_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake(_cwd: Path, *args: str, **_k: object) -> _FakeCompleted:
            # symbolic-ref returns rc 0 but empty; show-ref always fails.
            if args and args[0] == "symbolic-ref":
                return _FakeCompleted(0, "")
            return _FakeCompleted(1, "")

        monkeypatch.setattr(git_sync, "_run_git", _fake)
        assert git_sync.default_branch(tmp_path) is None


class _DispatchGit:
    """Arg-dispatching fake for _run_git to drive gone_branches deterministically."""

    def __init__(self, *, prune: str, for_each: str, merged: str) -> None:
        self._prune = prune
        self._for_each = for_each
        self._merged = merged

    def __call__(self, _cwd: Path, *args: str, **_k: object) -> _FakeCompleted:
        first = args[0] if args else ""
        if first == "remote" and len(args) == 1:
            return _FakeCompleted(0, "origin")
        if first == "remote" and "prune" in args:
            return _FakeCompleted(0, self._prune)
        if first == "for-each-ref":
            return _FakeCompleted(0, self._for_each)
        if first == "symbolic-ref":
            return _FakeCompleted(0, "origin/main")
        if first == "branch":
            return _FakeCompleted(0, self._merged)
        return _FakeCompleted(1, "")


class TestGoneBranchesDefensive:
    _SEP = "\x1f"

    def test_parses_would_prune_and_skips_header_lines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prune_out = "Pruning origin\nURL: git@example\n * [would prune] origin/feature\n"
        for_each = f"main{self._SEP}origin/main\nfeature{self._SEP}origin/feature\n"
        merged = "main\nfeature\n"  # feature merged -> safe
        monkeypatch.setattr(
            git_sync, "_run_git", _DispatchGit(prune=prune_out, for_each=for_each, merged=merged)
        )
        gone = git_sync.gone_branches(tmp_path)
        assert [g.name for g in gone] == ["feature"]
        assert gone[0].merged is True

    def test_empty_when_no_local_branch_tracks_stale_ref(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prune_out = " * [would prune] origin/orphan\n"
        for_each = f"main{self._SEP}origin/main\n"  # nothing tracks origin/orphan
        monkeypatch.setattr(
            git_sync, "_run_git", _DispatchGit(prune=prune_out, for_each=for_each, merged="main")
        )
        assert git_sync.gone_branches(tmp_path) == []

    def test_not_merged_when_merged_query_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prune_out = " * [would prune] origin/feature\n"
        for_each = f"feature{self._SEP}origin/feature\n"
        monkeypatch.setattr(
            git_sync, "_run_git", _DispatchGit(prune=prune_out, for_each=for_each, merged="")
        )
        gone = git_sync.gone_branches(tmp_path)
        assert len(gone) == 1
        assert gone[0].merged is False

    def test_stale_detection_skips_failed_remote_prune(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake(_cwd: Path, *args: str, **_k: object) -> _FakeCompleted:
            if args and args[0] == "remote" and len(args) == 1:
                return _FakeCompleted(0, "origin")
            if args and args[0] == "remote" and "prune" in args:
                return _FakeCompleted(1, "")  # prune probe failed -> skipped
            return _FakeCompleted(1, "")

        monkeypatch.setattr(git_sync, "_run_git", _fake)
        assert git_sync.gone_branches(tmp_path) == []
