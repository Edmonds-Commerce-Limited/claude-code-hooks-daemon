"""Tests for the first-class GitRepo utility (Plan 00113).

GitRepo is the single home for the git operations the daemon needs:
resolve the enclosing repo of a path, and read/write ``git config --local``
values. These tests init real git repos in tmp_path so the production
subprocess path is exercised.
"""

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.git_repo import GitRepo, run_git

_KEY = "hooksdaemon.testValue"


def _git_init(repo_root: Path) -> Path:
    repo_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", str(repo_root)],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )
    return repo_root


def _give_identity(repo: Path) -> None:
    """Set a local commit identity, so this repo can commit on its own terms.

    A fresh repo inherits nothing: on a developer machine a global
    ``user.email``/``user.name`` silently supplies one, and on a CI runner there
    is none, so ``git commit`` fails and ``HEAD`` never exists. Any test here
    that commits MUST call this — it is the premise, not a convenience (Plan
    00245 Task 3.4 fixed exactly this class, and Plan 00251 hit it again in a
    test that hand-rolled its own commit instead of reusing the helper that
    established it).
    """
    for key, value in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(
            ["git", "-C", str(repo), "config", "--local", key, value],
            capture_output=True,
            check=True,
            timeout=Timeout.GIT_CONTEXT,
        )


class TestResolveFor:
    def test_resolves_repo_for_path_inside(self, tmp_path: Path) -> None:
        repo = _git_init(tmp_path / "proj")
        resolved = GitRepo.resolve_for(repo / "src" / "x.py")
        assert resolved is not None
        assert resolved.root.resolve() == repo.resolve()

    def test_resolves_for_target_that_does_not_exist_yet(self, tmp_path: Path) -> None:
        repo = _git_init(tmp_path / "proj")
        (repo / "CLAUDE" / "Plan").mkdir(parents=True)
        target = repo / "CLAUDE" / "Plan" / "00042-not-created/PLAN.md"
        resolved = GitRepo.resolve_for(target)
        assert resolved is not None
        assert resolved.root.resolve() == repo.resolve()

    def test_resolves_nested_repo_not_outer(self, tmp_path: Path) -> None:
        outer = _git_init(tmp_path / "outer")
        inner = _git_init(outer / "vendor" / "lib")
        resolved = GitRepo.resolve_for(inner / "a/b.py")
        assert resolved is not None
        assert resolved.root.resolve() == inner.resolve()
        assert resolved.root.resolve() != outer.resolve()

    def test_returns_none_when_not_in_repo(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert GitRepo.resolve_for(plain / "x.py") is None

    def test_returns_none_when_git_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _git_init(tmp_path / "proj")

        def _raise(*_a: object, **_k: object) -> None:
            raise OSError("git missing")

        monkeypatch.setattr(subprocess, "run", _raise)
        assert GitRepo.resolve_for(repo / "x.py") is None


class TestReadConfig:
    def test_absent_key_returns_none(self, tmp_path: Path) -> None:
        repo = GitRepo(_git_init(tmp_path / "proj"))
        assert repo.read_config(_KEY) is None

    def test_reads_written_value(self, tmp_path: Path) -> None:
        repo = GitRepo(_git_init(tmp_path / "proj"))
        repo.write_config(_KEY, "42")
        assert repo.read_config(_KEY) == "42"

    def test_returns_raw_string_not_parsed(self, tmp_path: Path) -> None:
        """read_config is type-agnostic — returns the raw string; typed parsing
        is the caller's job (e.g. plan_numbering parses int)."""
        repo = GitRepo(_git_init(tmp_path / "proj"))
        repo.write_config(_KEY, "not-a-number")
        assert repo.read_config(_KEY) == "not-a-number"

    def test_returns_none_when_git_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = GitRepo(_git_init(tmp_path / "proj"))

        def _raise(*_a: object, **_k: object) -> None:
            raise OSError("git missing")

        monkeypatch.setattr(subprocess, "run", _raise)
        assert repo.read_config(_KEY) is None


class TestWriteConfig:
    def test_write_then_read_roundtrips(self, tmp_path: Path) -> None:
        repo = GitRepo(_git_init(tmp_path / "proj"))
        repo.write_config(_KEY, "110")
        assert repo.read_config(_KEY) == "110"

    def test_overwrites_previous(self, tmp_path: Path) -> None:
        repo = GitRepo(_git_init(tmp_path / "proj"))
        repo.write_config(_KEY, "110")
        repo.write_config(_KEY, "111")
        assert repo.read_config(_KEY) == "111"

    def test_write_raises_on_invalid_repo(self, tmp_path: Path) -> None:
        """FAIL FAST: writing to a non-repo path raises (not a silent no-op)."""
        not_a_repo = tmp_path / "plain"
        not_a_repo.mkdir()
        repo = GitRepo(not_a_repo)
        with pytest.raises(subprocess.CalledProcessError):
            repo.write_config(_KEY, "1")

    def test_value_survives_branch_switch(self, tmp_path: Path) -> None:
        """A --local config value lives in .git/config, so it is identical
        regardless of the checked-out branch (the core stability property)."""
        root = _git_init(tmp_path / "proj")
        _give_identity(root)
        (root / "f.txt").write_text("x")
        subprocess.run(
            ["git", "-C", str(root), "add", "f.txt"],
            capture_output=True,
            check=True,
            timeout=Timeout.GIT_CONTEXT,
        )
        subprocess.run(
            ["git", "-C", str(root), "commit", "-m", "init"],
            capture_output=True,
            check=True,
            timeout=Timeout.GIT_CONTEXT,
        )
        repo = GitRepo(root)
        repo.write_config(_KEY, "110")
        subprocess.run(
            ["git", "-C", str(root), "checkout", "-b", "feature"],
            capture_output=True,
            check=True,
            timeout=Timeout.GIT_CONTEXT,
        )
        assert repo.read_config(_KEY) == "110"


class TestGitRepoValueSemantics:
    def test_equality_by_root(self, tmp_path: Path) -> None:
        """GitRepo is a value object: two instances with the same root are equal."""
        assert GitRepo(tmp_path) == GitRepo(tmp_path)


def _commit_a_file(repo: Path) -> Path:
    """Give `repo` an identity and one committed file. Returns the file."""
    _give_identity(repo)
    tracked = repo / "tracked.txt"
    tracked.write_text("one\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo), "add", "tracked.txt"],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )
    return tracked


def _index_identity(repo: Path) -> tuple[int, int]:
    """Inode + mtime of `.git/index` — changes iff git rewrote the index."""
    stat = (repo / ".git" / "index").stat()
    return (stat.st_ino, stat.st_mtime_ns)


def _make_index_stale(tracked: Path) -> None:
    """Touch a tracked file so git WANTS to refresh the index on the next read.

    Without this the index is already up to date, git skips the refresh anyway,
    and a test asserting "the index was not rewritten" would pass vacuously.
    """
    tracked.touch()


class TestReadOnlyGitDoesNotTakeTheIndexLock:
    """Plan 00246: the daemon must not lock the agent's index just to read.

    `git status` is not a read — it refreshes the index and writes it back,
    taking `.git/index.lock`. The daemon does this on every user prompt, every
    status refresh and every daemon start, contending with the agent working in
    the same tree. `GIT_OPTIONAL_LOCKS=0` declines the refresh.

    These tests are behavioural on purpose. Asserting "the env var was passed"
    proves only that we set a variable; asserting the index was not rewritten
    proves the lock was not taken, which is the thing that matters.
    """

    def test_a_read_through_the_runner_does_not_rewrite_the_index(self, tmp_path: Path) -> None:
        repo = _git_init(tmp_path / "proj")
        tracked = _commit_a_file(repo)
        _make_index_stale(tracked)
        before = _index_identity(repo)

        run_git(repo, "status", "--porcelain")

        assert _index_identity(repo) == before, (
            "a read-only git call rewrote .git/index, which means it took "
            ".git/index.lock and can collide with the agent's own git commands"
        )

    def test_the_control_shows_bare_git_would_have_rewritten_it(self, tmp_path: Path) -> None:
        """Without this, the test above could pass for the wrong reason.

        If git had no interest in refreshing the index here, "not rewritten"
        would be true of any implementation and the test above would be
        vacuous. This pins that the scenario really does provoke a rewrite.
        """
        repo = _git_init(tmp_path / "proj")
        tracked = _commit_a_file(repo)
        _make_index_stale(tracked)
        before = _index_identity(repo)

        subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            capture_output=True,
            check=True,
            timeout=Timeout.GIT_CONTEXT,
        )

        assert _index_identity(repo) != before, (
            "scenario does not provoke an index refresh, so the sibling test "
            "would pass vacuously — fix the fixture, not the assertion"
        )

    def test_output_is_still_returned_verbatim(self, tmp_path: Path) -> None:
        """Declining the refresh must not change what git reports."""
        repo = _git_init(tmp_path / "proj")
        _commit_a_file(repo)
        (repo / "new.txt").write_text("x\n", encoding="utf-8")

        result = run_git(repo, "status", "--porcelain")

        assert result.returncode == 0
        assert "new.txt" in result.stdout

    def test_failure_is_reported_not_raised(self, tmp_path: Path) -> None:
        """Callers branch on returncode; a non-repo is an answer, not a crash."""
        not_a_repo = tmp_path / "bare"
        not_a_repo.mkdir()

        result = run_git(not_a_repo, "rev-parse", "--git-dir")

        assert result.returncode != 0
        assert result.stderr != ""

    def test_the_parent_environment_survives(self, tmp_path: Path) -> None:
        """The runner ADDS a variable; it must not replace the environment.

        A runner that passed only its own variable would drop PATH and git
        would not be found at all — so this is pinned rather than assumed.
        """
        repo = _git_init(tmp_path / "proj")
        _commit_a_file(repo)

        result = run_git(repo, "rev-parse", "--show-toplevel")

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() != ""

    def test_output_that_is_not_valid_utf8_is_reported_not_raised(self, tmp_path: Path) -> None:
        """The "never raises" contract has to hold for BYTES too (Plan 00248 F2).

        ``text=True`` decodes with ``errors="strict"``, so one invalid byte in
        git's stdout raises ``UnicodeDecodeError`` — which is a ``ValueError``,
        so neither ``OSError`` nor ``SubprocessError`` catches it and it escapes
        this runner entirely.

        That is not a theoretical shape. ``claude_md_injector`` reads a committed
        CLAUDE.md with ``git show`` on the daemon-startup path, whose caller
        (``DaemonController.initialise``) has no try/except and a comment
        asserting this cannot raise. One mis-encoded byte anywhere in that file
        would stop the daemon from starting.
        """
        repo = _git_init(tmp_path / "proj")
        _give_identity(repo)
        undecodable = repo / "bad.txt"
        undecodable.write_bytes(b"before \xff\xfe after\n")
        run_git(repo, "add", "bad.txt")
        committed = run_git(repo, "commit", "-m", "commit a file git cannot decode as UTF-8")

        # Assert the SETUP worked before asserting the behaviour. Without this the
        # test fails at the `git show` below with "invalid object name 'HEAD'",
        # which describes the fixture rather than the thing under test — the
        # actual CI failure this test shipped with.
        assert committed.returncode == 0, committed.stderr

        result = run_git(repo, "show", "HEAD:./bad.txt")

        assert result.returncode == 0, result.stderr
        assert "before" in result.stdout
        assert "after" in result.stdout

    def test_the_existing_read_helpers_route_through_it(self, tmp_path: Path) -> None:
        """`resolve_for` / `read_config` must stop locking too.

        They are the reads the daemon already funnels through this module, so a
        runner that only new callers use would leave them locking.
        """
        repo = _git_init(tmp_path / "proj")
        tracked = _commit_a_file(repo)
        resolved = GitRepo.resolve_for(repo / "src" / "x.py")
        assert resolved is not None

        _make_index_stale(tracked)
        before = _index_identity(repo)

        GitRepo.resolve_for(repo / "src" / "x.py")
        resolved.read_config(_KEY)

        assert _index_identity(repo) == before


class TestEveryGitCallIsBounded:
    """A wedged git must never stall a hook dispatch or daemon startup."""

    def test_the_runner_passes_a_timeout(self, tmp_path: Path) -> None:
        repo = _git_init(tmp_path / "proj")
        with mock.patch("subprocess.run") as runner:
            runner.return_value = subprocess.CompletedProcess([], 0, "", "")
            run_git(repo, "status", "--porcelain")

        assert runner.call_args.kwargs["timeout"] is not None

    def test_a_caller_may_tighten_the_timeout(self, tmp_path: Path) -> None:
        """Hot paths (status line, per-prompt) want a shorter bound than startup."""
        repo = _git_init(tmp_path / "proj")
        with mock.patch("subprocess.run") as runner:
            runner.return_value = subprocess.CompletedProcess([], 0, "", "")
            run_git(repo, "status", timeout=Timeout.GIT_STATUS_SHORT)

        assert runner.call_args.kwargs["timeout"] == Timeout.GIT_STATUS_SHORT

    def test_a_timeout_is_reported_not_raised(self, tmp_path: Path) -> None:
        """A wedged git is a failed read, not a daemon crash."""
        repo = _git_init(tmp_path / "proj")
        with mock.patch("subprocess.run") as runner:
            runner.side_effect = subprocess.TimeoutExpired(["git"], 1)
            result = run_git(repo, "status")

        assert result.returncode != 0


class TestCallerSuppliedEnvironment:
    """Some callers must ADD a variable — e.g. a fetch that must never prompt."""

    def test_caller_variables_are_added_to_the_environment(self, tmp_path: Path) -> None:
        repo = _git_init(tmp_path / "proj")
        with mock.patch("subprocess.run") as runner:
            runner.return_value = subprocess.CompletedProcess([], 0, "", "")
            run_git(repo, "fetch", env={"GIT_TERMINAL_PROMPT": "0"})

        passed = runner.call_args.kwargs["env"]
        assert passed["GIT_TERMINAL_PROMPT"] == "0"

    def test_caller_variables_do_not_replace_the_environment(self, tmp_path: Path) -> None:
        """Replacing it would drop PATH, and git would not be found at all."""
        repo = _git_init(tmp_path / "proj")
        with mock.patch("subprocess.run") as runner:
            runner.return_value = subprocess.CompletedProcess([], 0, "", "")
            run_git(repo, "fetch", env={"GIT_TERMINAL_PROMPT": "0"})

        passed = runner.call_args.kwargs["env"]
        assert "PATH" in passed

    def test_the_declined_index_lock_survives_a_caller_environment(self, tmp_path: Path) -> None:
        """The whole point of the runner must not be overridable by accident."""
        repo = _git_init(tmp_path / "proj")
        with mock.patch("subprocess.run") as runner:
            runner.return_value = subprocess.CompletedProcess([], 0, "", "")
            run_git(repo, "fetch", env={"GIT_TERMINAL_PROMPT": "0"})

        assert runner.call_args.kwargs["env"]["GIT_OPTIONAL_LOCKS"] == "0"

    def test_a_caller_cannot_re_enable_the_optional_lock(self, tmp_path: Path) -> None:
        """Not theoretical: a caller passing a whole `os.environ` copy would
        otherwise reinstate an inherited value and silently undo the runner's
        one guarantee. `git_sync._noninteractive_env` does exactly that copy.
        """
        repo = _git_init(tmp_path / "proj")
        with mock.patch("subprocess.run") as runner:
            runner.return_value = subprocess.CompletedProcess([], 0, "", "")
            run_git(repo, "status", env={"GIT_OPTIONAL_LOCKS": "1"})

        assert runner.call_args.kwargs["env"]["GIT_OPTIONAL_LOCKS"] == "0", (
            "a caller overrode the declined index lock, so the runner no longer "
            "guarantees the property it exists for"
        )
