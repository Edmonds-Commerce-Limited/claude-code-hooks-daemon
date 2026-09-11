"""Reading worktree state out of git, with failures that stay refusals.

`is_reapable` is only as safe as what it is fed. The collector's job is to turn
git's output into a `WorktreeState`, and its one hard requirement is that a git
call it could not complete must produce a state the predicate REFUSES — never a
state that happens to look clean. A collector that reported "0 commits ahead"
when `rev-list` failed would turn an unreadable worktree into a deletable one
(Plan 00349).
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

import claude_code_hooks_daemon.core.worktree_reaping as worktree_reaping_module
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core.worktree_reaping import (
    MINIMUM_AGE_SECONDS,
    UNKNOWN_COUNT,
    collect_worktree_states,
    is_reapable,
    reap_refusal_reason,
)


#: For tests whose subject is the uncommitted/commit-count axis, not Plan
#: 00372's age/live-process axis — injected so `is_reapable` stays silent
#: there and the assertion actually isolates what the test is about.
def _old_enough(_path: Path) -> float:
    return MINIMUM_AGE_SECONDS + 1


def _nobody_home() -> dict[int, Path]:
    return {}


_LISTING = """worktree /repo
HEAD abc123
branch refs/heads/main

worktree /repo/.claude/worktrees/agent-aaa-111
HEAD def456
branch refs/heads/agent-aaa-111

worktree /repo/untracked/worktrees/agent-bbb-222
HEAD 789abc
branch refs/heads/agent-bbb-222
"""

#: A directory name and its branch name are independent: `git worktree add
#: <dir> -b <branch>` names them separately, and nothing keeps them in step.
_RENAMED_LISTING = """worktree /repo
HEAD abc123
branch refs/heads/main

worktree /repo/.claude/worktrees/agent-aaa-111
HEAD def456
branch refs/heads/feature/something-else
"""

#: `git worktree add --detach` produces a record with no branch line at all.
_DETACHED_LISTING = """worktree /repo
HEAD abc123
branch refs/heads/main

worktree /repo/.claude/worktrees/agent-aaa-111
HEAD def456
detached
"""


def _ok(stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 0, stdout, "")


def _fail(stderr: str = "boom") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 1, "", stderr)


class _FakeGit:
    """Answers by subcommand, so tests state intent rather than argv order."""

    def __init__(self, **answers: subprocess.CompletedProcess[str]) -> None:
        self._answers = answers
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cwd: Path, *args: str, **_: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if args[0] == "worktree":
            return self._answers.get("listing", _ok(_LISTING))
        if args[0] == "status":
            return self._answers.get("status", _ok(""))
        if args[0] == "rev-list":
            return self._answers.get("rev_list", _ok("0\n"))
        if args[0] == "cherry":
            return self._answers.get("cherry", _ok(""))
        if args[0] == "check-ignore":
            # Real `git check-ignore` exits 1 and prints nothing when no path
            # is ignored, so the default answer models that, not an error.
            return self._answers.get("check_ignore", _fail(stderr=""))
        raise AssertionError(f"unexpected git call: {args}")


class TestWhichWorktreesAreCollected:
    def test_the_main_checkout_is_not_one_of_them(self) -> None:
        """`/repo` itself is in the listing and must never be a reap candidate."""
        states = collect_worktree_states(Path("/repo"), "main", run_fn=_FakeGit())
        assert [s.name for s in states] == ["agent-aaa-111", "agent-bbb-222"]

    def test_both_sanctioned_worktree_locations_are_read(self) -> None:
        """`.claude/worktrees/` and `untracked/worktrees/` are both in use."""
        states = collect_worktree_states(Path("/repo"), "main", run_fn=_FakeGit())
        assert len(states) == 2

    def test_an_unlistable_repo_yields_nothing_rather_than_guessing(self) -> None:
        git = _FakeGit(listing=_fail("not a git repository"))
        assert collect_worktree_states(Path("/repo"), "main", run_fn=git) == ()


class TestWhatTheListingAlreadySaysIsKept:
    """Anything rebuilt from the name afterwards is a guess git need not make."""

    def test_each_state_carries_the_path_git_reported(self) -> None:
        states = collect_worktree_states(Path("/repo"), "main", run_fn=_FakeGit())
        assert [state.path for state in states] == [
            Path("/repo/.claude/worktrees/agent-aaa-111"),
            Path("/repo/untracked/worktrees/agent-bbb-222"),
        ]

    def test_the_untracked_root_is_not_rewritten_to_the_dot_claude_one(self) -> None:
        """Both roots are sanctioned, so neither may be assumed."""
        states = collect_worktree_states(Path("/repo"), "main", run_fn=_FakeGit())
        assert str(states[1].path) == "/repo/untracked/worktrees/agent-bbb-222"

    def test_each_state_carries_the_branch_git_reported(self) -> None:
        states = collect_worktree_states(Path("/repo"), "main", run_fn=_FakeGit())
        assert [state.branch for state in states] == ["agent-aaa-111", "agent-bbb-222"]

    def test_a_branch_named_differently_from_its_directory_is_read_as_it_is(self) -> None:
        git = _FakeGit(listing=_ok(_RENAMED_LISTING))
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert state.name == "agent-aaa-111"
        assert state.branch == "feature/something-else"

    def test_a_detached_worktree_has_no_branch_rather_than_a_guessed_one(self) -> None:
        git = _FakeGit(listing=_ok(_DETACHED_LISTING))
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert state.branch is None

    def test_the_main_checkouts_branch_never_attaches_to_an_agent_worktree(self) -> None:
        """`refs/heads/main` sits in a record this collector skips entirely."""
        states = collect_worktree_states(Path("/repo"), "main", run_fn=_FakeGit())
        assert all(state.branch != "main" for state in states)


class TestTheCleanReading:
    def test_a_clean_worktree_collects_as_reapable(self) -> None:
        """Old enough and nobody home, injected: this test is about the
        uncommitted/commit-count axis, not Plan 00372's age/process axis.
        """
        states = collect_worktree_states(
            Path("/repo"),
            "main",
            run_fn=_FakeGit(),
            age_fn=_old_enough,
            process_cwds_fn=_nobody_home,
        )
        assert all(is_reapable(state) for state in states)

    def test_status_lines_become_paths_without_their_status_prefix(self) -> None:
        git = _FakeGit(status=_ok("A  .claude/ccy/CLAUDE.md\n?? untracked.txt\n"))
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert state.uncommitted_paths == (".claude/ccy/CLAUDE.md", "untracked.txt")

    def test_counts_are_read_from_git_not_inferred(self) -> None:
        git = _FakeGit(rev_list=_ok("211\n"), cherry=_ok("+ 1d49da27 subject\n- aaa other\n"))
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert state.commits_ahead_of_base == 211
        assert state.unlanded_patches == 1

    def test_a_cherry_line_marked_minus_is_a_landed_patch(self) -> None:
        """`-` means git found an equivalent patch on the base."""
        git = _FakeGit(cherry=_ok("- aaa landed\n- bbb landed\n"))
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert state.unlanded_patches == 0


class TestGeneratedOutputIsNotWork:
    """The real failure (Plan 00380): four worktrees held by the daemon's own file.

    `git status` runs INSIDE the worktree, so it applies that worktree's
    `.gitignore` — which is pinned to whatever commit the worktree sits on. A
    generated path added to the ignore list later is therefore invisible to it,
    and the daemon's own `.claude/reports/…/ADVISORY.md` read as the agent's
    unsaved work. Main's ignore rules are the current authority, so an UNTRACKED
    path main would ignore is not work.
    """

    def test_an_untracked_path_main_ignores_does_not_count(self) -> None:
        git = _FakeGit(
            status=_ok("?? .claude/reports/\n"),
            check_ignore=_ok(".claude/reports/\n"),
        )
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert state.uncommitted_paths == ()

    def test_that_worktree_becomes_reapable(self) -> None:
        """The whole point: five of these sat unreapable for days."""
        git = _FakeGit(
            status=_ok("?? .claude/reports/\n"),
            check_ignore=_ok(".claude/reports/\n"),
        )
        state = collect_worktree_states(
            Path("/repo"),
            "main",
            run_fn=git,
            age_fn=_old_enough,
            process_cwds_fn=_nobody_home,
        )[0]
        assert is_reapable(state)

    def test_an_untracked_path_main_does_not_ignore_still_counts(self) -> None:
        git = _FakeGit(status=_ok("?? real-work.py\n"))
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert state.uncommitted_paths == ("real-work.py",)

    def test_only_the_generated_one_is_dropped_from_a_mixed_worktree(self) -> None:
        git = _FakeGit(
            status=_ok("?? .claude/reports/\n?? real-work.py\n"),
            check_ignore=_ok(".claude/reports/\n"),
        )
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert state.uncommitted_paths == ("real-work.py",)
        assert not is_reapable(state)


class TestOnlyUntrackedPathsCanBeDropped:
    """The narrowing that keeps this safe.

    `git check-ignore` answers about a PATH, and it cannot know that the path is
    tracked-and-modified in the worktree. Were any status code eligible, a
    modification to a file main happens to ignore would be silently discarded.
    So only `??` is ever a candidate; a tracked change always still refuses.
    """

    def test_a_modified_tracked_path_survives_an_ignore_match(self) -> None:
        git = _FakeGit(
            status=_ok(" M .claude/reports/notes.md\n"),
            check_ignore=_ok(".claude/reports/notes.md\n"),
        )
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert state.uncommitted_paths == (".claude/reports/notes.md",)
        assert not is_reapable(state)

    def test_a_staged_path_survives_an_ignore_match(self) -> None:
        git = _FakeGit(
            status=_ok("A  .claude/reports/added.md\n"),
            check_ignore=_ok(".claude/reports/added.md\n"),
        )
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert state.uncommitted_paths == (".claude/reports/added.md",)

    def test_a_deleted_tracked_path_survives_an_ignore_match(self) -> None:
        git = _FakeGit(
            status=_ok(" D .claude/reports/gone.md\n"),
            check_ignore=_ok(".claude/reports/gone.md\n"),
        )
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert state.uncommitted_paths == (".claude/reports/gone.md",)


class TestTheIgnoreQueryIsNeverReadAsPermissionToReap:
    def test_a_failed_check_ignore_drops_nothing(self) -> None:
        """Same doctrine as the counts: a failed call is never 'nothing to lose'."""
        git = _FakeGit(status=_ok("?? .claude/reports/\n"), check_ignore=_fail())
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert state.uncommitted_paths == (".claude/reports/",)
        assert not is_reapable(state)

    def test_a_failed_status_is_not_passed_to_check_ignore(self) -> None:
        """The sentinel is a message, not a path — asking git about it is nonsense."""
        git = _FakeGit(status=_fail())
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert not is_reapable(state)
        assert "check-ignore" not in {call[0] for call in git.calls}

    def test_no_untracked_paths_means_no_ignore_query(self) -> None:
        git = _FakeGit(status=_ok(" M src/thing.py\n"))
        collect_worktree_states(Path("/repo"), "main", run_fn=git)
        assert "check-ignore" not in {call[0] for call in git.calls}

    def test_the_query_is_asked_of_the_main_checkout_not_the_worktree(self) -> None:
        """A worktree's own rules are the stale ones — asking it changes nothing."""
        seen: list[Path] = []

        class _RecordingGit(_FakeGit):
            def __call__(self, cwd: Path, *args: str, **kw: object):
                if args[0] == "check-ignore":
                    seen.append(cwd)
                return super().__call__(cwd, *args, **kw)

        git = _RecordingGit(status=_ok("?? .claude/reports/\n"))
        collect_worktree_states(Path("/repo"), "main", run_fn=git)
        assert seen and all(path == Path("/repo") for path in seen)


class TestAFailedGitCallIsNeverReadAsClean:
    """The one property that makes the collector safe to act on."""

    def test_a_failed_status_refuses(self) -> None:
        git = _FakeGit(status=_fail())
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert not is_reapable(state)

    def test_a_failed_rev_list_refuses(self) -> None:
        git = _FakeGit(rev_list=_fail())
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert not is_reapable(state)
        assert state.commits_ahead_of_base == UNKNOWN_COUNT

    def test_a_failed_cherry_refuses(self) -> None:
        git = _FakeGit(cherry=_fail())
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert not is_reapable(state)
        assert state.unlanded_patches == UNKNOWN_COUNT

    def test_unparseable_count_output_refuses(self) -> None:
        """git exited 0 but said something no integer can be read out of."""
        git = _FakeGit(rev_list=_ok("not a number\n"))
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert not is_reapable(state)

    def test_the_unknown_sentinel_is_negative_so_it_can_never_look_clean(self) -> None:
        assert UNKNOWN_COUNT < 0


def _git(cwd: Path, *args: str) -> None:
    """Drive a real git, failing loudly — these calls build the fixture."""
    subprocess.run(  # nosec B603 B607 - git, list form, no shell
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )


class TestAgainstARealGitRepository:
    """A real git, because the fake only ever confirms the argv this builds.

    This used to read THIS repository's own worktrees and assert it found some.
    It passed here, where 21 had accumulated, and failed on a fresh CI checkout
    that has none — a test whose subject is whatever the machine happens to
    contain reports the machine, not the code. So it builds its own repository
    and its own worktree, and is non-vacuous everywhere for that reason rather
    than by luck.
    """

    @staticmethod
    def _repo_with_one_worktree(tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "Test")
        (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        _git(repo, "add", "seed.txt")
        _git(repo, "commit", "-m", "seed")
        _git(repo, "worktree", "add", ".claude/worktrees/agent-probe-1", "-b", "agent-probe-1")
        return repo

    def test_it_finds_the_worktree_and_nothing_else(self, tmp_path: Path) -> None:
        states = collect_worktree_states(self._repo_with_one_worktree(tmp_path), "main")
        assert [state.name for state in states] == ["agent-probe-1"]

    def test_real_git_output_supplies_the_path_and_the_branch(self, tmp_path: Path) -> None:
        repo = self._repo_with_one_worktree(tmp_path)
        state = collect_worktree_states(repo, "main")[0]
        assert state.path == repo / ".claude/worktrees/agent-probe-1"
        assert state.branch == "agent-probe-1"

    def test_a_freshly_created_worktree_at_the_base_is_refused(self, tmp_path: Path) -> None:
        """Plan 00372's live incident, reproduced with real git: a worktree
        seconds old, at the base, with no history of its own, was listed as
        safe to reap. It looks IDENTICAL to a finished one on every axis this
        module tracked before — this is the one that tells them apart.
        """
        states = collect_worktree_states(self._repo_with_one_worktree(tmp_path), "main")
        assert not is_reapable(states[0])
        assert "minimum age" in (reap_refusal_reason(states[0]) or "")

    def test_the_same_worktree_once_it_is_old_enough_is_reapable(self, tmp_path: Path) -> None:
        """Discrimination check: the guard must not just refuse everything.

        `.git` is a plain pointer file `git worktree add` writes once and
        never touches again (verified live, Plan 00372) -- backdating its
        mtime is simulating time passing on a REAL worktree, not faking git.
        """
        repo = self._repo_with_one_worktree(tmp_path)
        worktree = repo / ".claude/worktrees/agent-probe-1"
        past = time.time() - (MINIMUM_AGE_SECONDS + 60)
        os.utime(worktree / ".git", (past, past))
        states = collect_worktree_states(repo, "main")
        assert is_reapable(states[0])

    def test_a_live_process_inside_an_old_worktree_still_refuses_it(self, tmp_path: Path) -> None:
        """The two signals are independent, not redundant: an OLD worktree
        (age check alone would clear it) that someone is actually sitting in
        right now must still be refused. A real subprocess, a real /proc scan
        -- nothing here is mocked.
        """
        repo = self._repo_with_one_worktree(tmp_path)
        worktree = repo / ".claude/worktrees/agent-probe-1"
        past = time.time() - (MINIMUM_AGE_SECONDS + 60)
        os.utime(worktree / ".git", (past, past))

        proc = subprocess.Popen(  # nosec B603 B607 - trusted system tool, list form
            ["sleep", "30"], cwd=worktree
        )
        try:
            states = collect_worktree_states(repo, "main")
            assert not is_reapable(states[0])
            assert proc.pid in states[0].live_process_pids
        finally:
            proc.terminate()
            proc.wait(timeout=Timeout.PROCESS_KILL_WAIT)

    def test_a_platform_with_no_proc_reports_no_live_process_rather_than_erroring(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`/proc` is Linux-only; losing this ONE signal on another platform
        must not take the independent age check down with it.
        """
        monkeypatch.setattr(worktree_reaping_module, "_PROC_ROOT", tmp_path / "no-such-proc-root")
        repo = self._repo_with_one_worktree(tmp_path)
        states = collect_worktree_states(repo, "main")
        assert states[0].live_process_pids == ()

    def test_an_uncommitted_file_makes_it_refuse(self, tmp_path: Path) -> None:
        repo = self._repo_with_one_worktree(tmp_path)
        (repo / ".claude/worktrees/agent-probe-1/new.txt").write_text("x\n", encoding="utf-8")
        states = collect_worktree_states(repo, "main")
        assert not is_reapable(states[0])

    def test_a_commit_ahead_of_the_base_makes_it_refuse(self, tmp_path: Path) -> None:
        repo = self._repo_with_one_worktree(tmp_path)
        worktree = repo / ".claude/worktrees/agent-probe-1"
        (worktree / "new.txt").write_text("x\n", encoding="utf-8")
        _git(worktree, "add", "new.txt")
        _git(worktree, "commit", "-m", "work that exists nowhere else")
        states = collect_worktree_states(repo, "main")
        assert not is_reapable(states[0])


class TestAgainstThisRepository:
    """A read-only run against whatever this checkout has, asserting no count.

    Worth keeping separately from the built fixture above: it is the only place
    the collector meets a repository it did not construct. It must therefore
    assert nothing about how many worktrees exist — that number is a property of
    the machine, and depending on it is what broke the previous version.
    """

    def test_it_classifies_without_removing_anything(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        assert repo_root.is_dir()
        for state in collect_worktree_states(repo_root, "main"):
            assert state.name
            assert isinstance(state.uncommitted_paths, tuple)
            assert isinstance(state.live_process_pids, tuple)
            assert state.age_seconds is None or state.age_seconds >= 0
