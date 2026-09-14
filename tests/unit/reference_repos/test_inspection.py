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
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.reference_repos.inspection import inspect_repo
from claude_code_hooks_daemon.reference_repos.model import Checkability
from claude_code_hooks_daemon.utils import git_sync


def _run(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
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
        timeout=Timeout.GIT_CONTEXT,
    )
    _run(seed, "remote", "add", "origin", str(origin))
    _run(seed, "push", "-u", "origin", "main")

    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(origin), str(clone)],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
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
            timeout=Timeout.GIT_CONTEXT,
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


#: git subcommands that contact a remote. Checked as a DENY-list over what was
#: actually spawned, rather than by stubbing the two helpers that happen to use
#: them today: a future probe added with a raw `_run_git(cwd, "ls-remote", ...)`
#: would sail straight past a stub of `fetch_all`, which is precisely the shape
#: of change this invariant exists to catch.
_NETWORK_VERBS: Final[frozenset[str]] = frozenset(
    {"fetch", "pull", "push", "clone", "ls-remote", "submodule"}
)

#: `git remote` alone lists local config; these subcommands talk to the remote.
_NETWORK_REMOTE_SUBCOMMANDS: Final[frozenset[str]] = frozenset({"update", "prune", "set-head"})

#: More than one probe. A spy that recorded nothing — because the spawn point
#: moved, or the inspection short-circuited — would satisfy "no network verbs"
#: perfectly while checking nothing at all.
_MINIMUM_LOCAL_PROBES: Final[int] = 2


def _is_network(argv: tuple[str, ...]) -> bool:
    if not argv:
        return False
    if argv[0] in _NETWORK_VERBS:
        return True
    return argv[0] == "remote" and len(argv) > 1 and argv[1] in _NETWORK_REMOTE_SUBCOMMANDS


class TestTheInspectorDoesNoNetworkIO:
    """The architectural invariant, enforced rather than documented.

    PreToolUse reads this on the hook socket's 30s budget, and one fetch can
    consume all of it. So the assertion is over every git command the inspection
    ACTUALLY spawns, taken at the daemon's single spawn point — not over the two
    named helpers a previous version stubbed, which proved only that
    ``inspect_repo`` did not call those two functions BY NAME.
    """

    @staticmethod
    def _spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
        """Record every git argv spawned through ``git_sync``, and pass it on."""
        spawned: list[tuple[str, ...]] = []
        real = git_sync.run_git

        def _record(
            cwd: Path,
            *args: str,
            timeout: float = Timeout.GIT_CONTEXT,
            env: Mapping[str, str] | None = None,
        ) -> subprocess.CompletedProcess[str]:
            spawned.append(tuple(args))
            return real(cwd, *args, timeout=timeout, env=env)

        monkeypatch.setattr(git_sync, "run_git", _record)
        return spawned

    def test_inspection_never_performs_network_io(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, clone = _remote_and_clone(tmp_path)
        spawned = self._spy(monkeypatch)

        assert inspect_repo(clone).checkable is True
        assert [argv for argv in spawned if _is_network(argv)] == []

    def test_the_invariant_is_asserted_against_commands_that_really_ran(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guards the test above from passing vacuously."""
        _, clone = _remote_and_clone(tmp_path)
        spawned = self._spy(monkeypatch)

        inspect_repo(clone)

        assert len(spawned) >= _MINIMUM_LOCAL_PROBES

    def test_the_spy_sees_a_fetch_when_one_really_happens(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The mutation guard: prove the trap would spring.

        Everything above asserts an ABSENCE, and an absence is exactly what a
        spy watching the wrong spawn point also reports. So this drives a real
        fetch through the same seam and asserts it is both recorded and
        classified — if `_run_git` ever stops routing through `run_git`, this
        fails while the invariant tests would go on quietly passing.
        """
        _, clone = _remote_and_clone(tmp_path)
        spawned = self._spy(monkeypatch)

        git_sync.fetch_all(clone)

        assert [argv for argv in spawned if _is_network(argv)] != []

    def test_the_detector_recognises_a_network_verb(self) -> None:
        """The deny-list is only worth having if it would actually fire."""
        assert _is_network(("fetch", "--all")) is True
        assert _is_network(("remote", "prune", "origin")) is True
        assert _is_network(("rev-list", "--count", "HEAD")) is False
        assert _is_network(("remote",)) is False
        assert _is_network(()) is False
