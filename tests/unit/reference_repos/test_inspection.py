"""Reading a governed repo's state without touching the network (Plan 00401 Task 1.2).

These tests init real git repositories against a local bare "remote", because
the classification boundaries being asserted are git's, and a mocked git would
only prove that the mock matches my belief about git.

The load-bearing test in this file is
``test_inspection_never_performs_network_io``. The whole architecture rests on
PreToolUse doing no network work — ``GIT_FETCH_SESSION`` and
``GIT_PULL_SESSION`` are 30s each against a 30s hook socket budget, so a single
fetch here could consume the entire budget and reproduce the ``socket_timeout``
failure the daemon already has dedicated error text for. A future refactor that
"helpfully" adds a fetch would be caught by that test and nothing else.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.reference_repos.inspection import inspect_repo
from claude_code_hooks_daemon.reference_repos.model import Checkability
from claude_code_hooks_daemon.utils import git_sync


def _run(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout.strip()


def _identity(repo: Path) -> None:
    _run(repo, "config", "user.email", "t@t")
    _run(repo, "config", "user.name", "tester")
    _run(repo, "config", "commit.gpgsign", "false")


def _commit(repo: Path, name: str, content: str) -> None:
    (repo / name).write_text(content, encoding="utf-8")
    _run(repo, "add", name)
    _run(repo, "commit", "-m", f"add {name}")


def _remote_and_clone(tmp_path: Path) -> tuple[Path, Path]:
    """A bare remote with one commit, and a clone tracking its default branch."""
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    seed.mkdir()
    _run(seed, "init", "-b", "main")
    _identity(seed)
    _commit(seed, "README.md", "one\n")
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(origin)],
        capture_output=True,
        check=True,
        timeout=30,
    )
    _run(seed, "remote", "add", "origin", str(origin))
    _run(seed, "push", "-u", "origin", "main")

    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(origin), str(clone)],
        capture_output=True,
        check=True,
        timeout=30,
    )
    _identity(clone)
    return origin, clone


def _advance_origin(tmp_path: Path, origin: Path) -> None:
    """Put a new commit on the remote, without the clone knowing."""
    pusher = tmp_path / "pusher"
    if not pusher.exists():
        subprocess.run(
            ["git", "clone", str(origin), str(pusher)],
            capture_output=True,
            check=True,
            timeout=30,
        )
        _identity(pusher)
    _commit(pusher, f"extra-{len(list(pusher.glob('extra-*')))}.md", "more\n")
    _run(pusher, "push", "origin", "main")


class TestACheckableRepo:
    def test_a_fresh_clone_is_checkable_and_current(self, tmp_path: Path) -> None:
        _, clone = _remote_and_clone(tmp_path)

        state = inspect_repo(clone)

        assert state.checkability is Checkability.CHECKABLE
        assert state.checkable is True
        assert state.branch == "main"
        assert state.default_branch == "main"
        assert state.upstream == "origin/main"
        assert state.behind == 0
        assert state.ahead == 0
        assert state.dirty is False
        assert state.needs_attention is False

    def test_the_path_is_carried_on_the_state(self, tmp_path: Path) -> None:
        """Reports name the repo, so the reading must know which repo it is."""
        _, clone = _remote_and_clone(tmp_path)

        assert inspect_repo(clone).path == clone


class TestStalenessIsSeenOnlyAfterAFetch:
    def test_a_clone_is_not_behind_until_its_tracking_refs_are_updated(
        self, tmp_path: Path
    ) -> None:
        """This is the architecture, asserted rather than assumed.

        The inspector does not fetch, so a commit pushed to origin is invisible
        to it until something else fetches. That is exactly why SessionStart
        owns the network work and PreToolUse reads cached state.
        """
        origin, clone = _remote_and_clone(tmp_path)
        _advance_origin(tmp_path, origin)

        assert inspect_repo(clone).behind == 0

    def test_after_a_fetch_the_clone_reads_as_behind(self, tmp_path: Path) -> None:
        origin, clone = _remote_and_clone(tmp_path)
        _advance_origin(tmp_path, origin)
        _run(clone, "fetch", "origin")

        state = inspect_repo(clone)

        assert state.behind == 1
        assert state.is_behind is True
        assert state.needs_attention is True
        assert state.safe_to_pull is True


class TestLocalConditions:
    def test_an_uncommitted_change_reads_as_dirty(self, tmp_path: Path) -> None:
        _, clone = _remote_and_clone(tmp_path)
        (clone / "README.md").write_text("edited\n", encoding="utf-8")

        state = inspect_repo(clone)

        assert state.dirty is True
        assert state.safe_to_pull is False

    def test_an_untracked_file_also_reads_as_dirty(self, tmp_path: Path) -> None:
        """An untracked file can be clobbered by a merge, so it counts."""
        _, clone = _remote_and_clone(tmp_path)
        (clone / "scratch.txt").write_text("mine\n", encoding="utf-8")

        assert inspect_repo(clone).dirty is True

    def test_a_local_commit_reads_as_ahead(self, tmp_path: Path) -> None:
        _, clone = _remote_and_clone(tmp_path)
        _commit(clone, "local.md", "local\n")

        state = inspect_repo(clone)

        assert state.ahead == 1
        assert state.safe_to_pull is False

    def test_a_feature_branch_is_reported_as_off_the_default_branch(self, tmp_path: Path) -> None:
        _, clone = _remote_and_clone(tmp_path)
        _run(clone, "checkout", "-b", "wip")
        _run(clone, "branch", "--set-upstream-to", "origin/main", "wip")

        state = inspect_repo(clone)

        assert state.branch == "wip"
        assert state.default_branch == "main"
        assert state.is_on_default_branch is False
        assert state.needs_attention is True


class TestUncheckableClassifications:
    def test_a_directory_that_is_not_a_repo(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()

        state = inspect_repo(plain)

        assert state.checkability is Checkability.NOT_A_REPO
        assert state.needs_attention is False

    def test_a_repo_with_no_remote(self, tmp_path: Path) -> None:
        local = tmp_path / "local"
        local.mkdir()
        _run(local, "init", "-b", "main")
        _identity(local)
        _commit(local, "README.md", "one\n")

        state = inspect_repo(local)

        assert state.checkability is Checkability.NO_REMOTE
        assert state.needs_attention is False

    def test_a_branch_with_no_upstream(self, tmp_path: Path) -> None:
        _, clone = _remote_and_clone(tmp_path)
        _run(clone, "checkout", "-b", "untracked-branch")

        state = inspect_repo(clone)

        assert state.checkability is Checkability.NO_UPSTREAM
        assert state.needs_attention is False

    def test_a_detached_head(self, tmp_path: Path) -> None:
        _, clone = _remote_and_clone(tmp_path)
        head = _run(clone, "rev-parse", "HEAD")
        _run(clone, "checkout", "--detach", head)

        state = inspect_repo(clone)

        assert state.checkability is Checkability.DETACHED_HEAD
        assert state.needs_attention is False

    def test_an_unreachable_remote_is_still_classified_without_hanging(
        self, tmp_path: Path
    ) -> None:
        """The canary case: origin points somewhere that cannot be reached.

        Because nothing here contacts the remote, an invalid origin costs
        nothing and classifies from local refs alone. A design that reached out
        would stall here for the full fetch timeout.
        """
        _, clone = _remote_and_clone(tmp_path)
        _run(clone, "remote", "set-url", "origin", "https://invalid.invalid/canary.git")

        state = inspect_repo(clone)

        assert state.checkability is Checkability.CHECKABLE
        assert state.needs_attention is False


class TestTheInspectorDoesNoNetworkIO:
    def test_inspection_never_performs_network_io(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The architectural invariant, enforced rather than documented.

        PreToolUse reads this on the hook socket's 30s budget, and one fetch can
        consume all of it. Any future change that adds a fetch or a pull to the
        inspection path fails here.
        """
        _, clone = _remote_and_clone(tmp_path)

        def _forbidden(*_args: object, **_kwargs: object) -> object:
            raise AssertionError("inspection must not perform network I/O")

        monkeypatch.setattr(git_sync, "fetch_all", _forbidden)
        monkeypatch.setattr(git_sync, "pull_ff_only", _forbidden)

        assert inspect_repo(clone).checkable is True
