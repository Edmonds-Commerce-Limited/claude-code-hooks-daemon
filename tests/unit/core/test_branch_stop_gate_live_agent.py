"""N758: a branch a live sub-agent of the session is working on is in flight, not abandoned.

The lead stops to wait for a background agent editing the shared worktree. The
guard used to deny that stop three times, suggest ``git add -A`` (which would sweep
the agent's half-done files into the lead's commit), and then record the branch as
abandoned. A sub-agent of the session counts as live only on daemon state: its
touch record on the branch, its transcript having moved within
``Timeout.STOP_GUARD_AGENT_SILENCE``, its turn not ended, and no ``background_tasks``
report (recorded or in this payload) saying it is no longer running. Anything else
is today's behaviour.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.core.branch_records import TOUCHED_KEY
from claude_code_hooks_daemon.core.branch_stop_gate import (
    MAX_STOP_BLOCKS,
    STATE_KIND,
    StopDecision,
    decide_stop,
)
from claude_code_hooks_daemon.utils.session_load import record_background_tasks
from claude_code_hooks_daemon.utils.spend_ledger import read_state, state_path

SESSION = "sess-1"
WORKER = "aworker0000000001"
OTHER = "aother00000000002"
NOW = 1_800_000_000.0
BRANCH = "shared"
#: The line a stop that gives way writes for an abandoned branch.
ABANDONED_RECORD = "Branches abandoned at stop"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    root = tmp_path / "repo"
    _git(tmp_path, "clone", "-q", str(remote), str(root))
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / ".git" / "info" / "exclude").write_text("untracked/\n")
    _git(root, "checkout", "-q", "-b", "main")
    _git(root, "commit", "-q", "--allow-empty", "-m", "root")
    _git(root, "push", "-q", "-u", "origin", "main")
    _git(root, "remote", "set-head", "origin", "main")
    return root


@pytest.fixture
def untracked(tmp_path: Path) -> Path:
    path = tmp_path / "untracked"
    path.mkdir()
    return path


@pytest.fixture
def transcript(tmp_path: Path) -> str:
    """The lead's transcript path; sub-agent transcripts sit in its sibling directory."""
    projects = tmp_path / "projects"
    (projects / SESSION / "subagents").mkdir(parents=True)
    main = projects / f"{SESSION}.jsonl"
    main.write_text("")
    return str(main)


def _subagents(transcript: str) -> Path:
    return Path(transcript).parent / SESSION / "subagents"


def _agent(
    transcript: str,
    agent_id: str,
    *,
    silent_for: float = 10.0,
    stopped: bool = False,
    name: str = "",
) -> Path:
    """A sub-agent transcript last written ``silent_for`` seconds before ``NOW``."""
    directory = _subagents(transcript)
    record = {
        "type": "assistant",
        "message": {
            "model": "claude-sonnet-5-5",
            "stop_reason": "end_turn" if stopped else "tool_use",
            "usage": {"cache_read_input_tokens": 1000},
        },
    }
    path = directory / f"agent-{agent_id}.jsonl"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    if name:
        (directory / f"agent-{agent_id}.meta.json").write_text(json.dumps({"name": name}))
    os.utime(path, (NOW - silent_for, NOW - silent_for))
    return path


def _raw_agent(transcript: str, agent_id: str, content: bytes, *, silent_for: float = 10.0) -> None:
    path = _subagents(transcript) / f"agent-{agent_id}.jsonl"
    path.write_bytes(content)
    os.utime(path, (NOW - silent_for, NOW - silent_for))


def _touch(repo: Path, branch: str, agent: str) -> None:
    _git(repo, "config", "--add", f"branch.{branch}.{TOUCHED_KEY}", f"{SESSION}:{agent}")


def _dirty_shared_branch(repo: Path, *agents: str) -> None:
    """The main worktree on ``shared``, with a half-written file, touched by the lead and ``agents``."""
    _git(repo, "checkout", "-q", "-b", BRANCH)
    _git(repo, "push", "-q", "-u", "origin", BRANCH)
    (repo / "half_done.py").write_text("x = (\n")
    _touch(repo, BRANCH, "")
    for agent in agents:
        _touch(repo, BRANCH, agent)


def _unpushed_branch(repo: Path, name: str, *agents: str) -> None:
    _git(repo, "branch", name, "main")
    tree = _git(repo, "rev-parse", f"{name}^{{tree}}").strip()
    parent = _git(repo, "rev-parse", name).strip()
    tip = _git(repo, "commit-tree", tree, "-p", parent, "-m", "work").strip()
    _git(repo, "update-ref", f"refs/heads/{name}", tip)
    _touch(repo, name, "")
    for agent in agents:
        _touch(repo, name, agent)


def _decide(
    repo: Path,
    untracked: Path,
    *,
    transcript: str = "",
    background_tasks: Any = None,
    agent: str | None = None,
    now: float = NOW,
) -> StopDecision:
    return decide_stop(
        repo,
        BranchesConfig(),
        untracked,
        session_id=SESSION,
        agent_id=agent,
        handoff=False,
        now=now,
        transcript_path=transcript,
        background_tasks=background_tasks,
    )


def _state(untracked: Path, key: str = "main") -> dict[str, Any]:
    return read_state(state_path(untracked, SESSION, STATE_KIND, key))


def _in_flight_lines(decision: StopDecision) -> list[str]:
    return [line for line in decision.context if "in flight" in line]


class TestALiveAuthorKeepsTheBranchInFlight:
    def test_the_stop_is_allowed_naming_the_agent_and_the_branch(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        _dirty_shared_branch(repo, WORKER)
        _agent(transcript, WORKER, name="developer")
        decision = _decide(repo, untracked, transcript=transcript)
        assert decision.reason is None
        lines = _in_flight_lines(decision)
        assert len(lines) == 1
        assert BRANCH in lines[0] and "developer" in lines[0] and WORKER in lines[0]
        assert not any(ABANDONED_RECORD in line for line in decision.context)

    def test_the_remedy_is_wait_stop_or_have_it_commit_never_stage_everything(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        _dirty_shared_branch(repo, WORKER)
        _agent(transcript, WORKER)
        text = "\n".join(_decide(repo, untracked, transcript=transcript).context)
        assert "add -A" not in text
        assert "wait for" in text and "stop it" in text and "commit its own work" in text

    def test_it_is_recorded_in_flight_and_draws_no_block(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        _dirty_shared_branch(repo, WORKER)
        _agent(transcript, WORKER)
        for _ in range(MAX_STOP_BLOCKS + 2):
            decision = _decide(repo, untracked, transcript=transcript)
            assert decision.reason is None
            assert not any(ABANDONED_RECORD in line for line in decision.context)
        state = _state(untracked)
        assert state["in_flight"] == [BRANCH]
        assert "abandoned" not in state
        assert "blocks" not in state

    def test_only_the_dirty_finding_goes_in_flight_the_leads_unpushed_commit_is_held(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        """Review blocker 1: a push never touches the agent's files, so it is still owed."""
        _dirty_shared_branch(repo, WORKER)
        _git(repo, "commit", "-q", "--allow-empty", "-m", "lead work")
        _agent(transcript, WORKER)
        decision = _decide(repo, untracked, transcript=transcript)
        assert decision.reason is not None
        assert f"  - {BRANCH}: commits no remote holds" in decision.reason
        assert f"git push -u origin {BRANCH}" in decision.reason
        assert "dirty worktree" not in decision.reason
        assert "add -A" not in decision.reason
        assert any(BRANCH in line for line in _in_flight_lines(decision))

    def test_an_unpushed_branch_with_a_live_author_is_held_exactly_as_without_one(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        _unpushed_branch(repo, "feat-a", WORKER)
        without = _decide(repo, untracked)
        _agent(transcript, WORKER)
        with_agent = _decide(repo, untracked, transcript=transcript)
        assert with_agent.reason is not None
        assert with_agent.reason == (without.reason or "").replace("Block 1 of", "Block 2 of")
        assert not _in_flight_lines(with_agent)

    def test_the_in_flight_record_is_cleared_by_a_stop_with_nothing_left_behind(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        """Review minor 5: the record must not outlive the work it describes."""
        _dirty_shared_branch(repo, WORKER)
        _agent(transcript, WORKER)
        assert _decide(repo, untracked, transcript=transcript).reason is None
        assert _state(untracked)["in_flight"] == [BRANCH]
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "agent work")
        _git(repo, "push", "-q")
        decision = _decide(repo, untracked, transcript=transcript)
        assert decision.reason is None
        assert "in_flight" not in _state(untracked)

    def test_the_in_flight_record_is_cleared_once_the_agent_is_gone(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        _dirty_shared_branch(repo, WORKER)
        path = _agent(transcript, WORKER)
        assert _decide(repo, untracked, transcript=transcript).reason is None
        path.unlink()
        assert _decide(repo, untracked, transcript=transcript).reason is not None
        assert "in_flight" not in _state(untracked)


class TestEveryOtherCaseIsTodaysBehaviour:
    """No verifiable live author means the branch is judged exactly as before."""

    @staticmethod
    def _held_as_before(decision: StopDecision) -> None:
        assert decision.reason is not None
        assert "add -A" in decision.reason
        assert not _in_flight_lines(decision)

    def test_no_transcript_path(self, repo: Path, untracked: Path, transcript: str) -> None:
        _dirty_shared_branch(repo, WORKER)
        _agent(transcript, WORKER)
        self._held_as_before(_decide(repo, untracked))

    def test_an_agent_whose_turn_ended(self, repo: Path, untracked: Path, transcript: str) -> None:
        _dirty_shared_branch(repo, WORKER)
        _agent(transcript, WORKER, stopped=True)
        self._held_as_before(_decide(repo, untracked, transcript=transcript))

    def test_an_agent_silent_past_the_bound(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        _dirty_shared_branch(repo, WORKER)
        _agent(transcript, WORKER, silent_for=Timeout.STOP_GUARD_AGENT_SILENCE + 1)
        self._held_as_before(_decide(repo, untracked, transcript=transcript))

    def test_an_agent_silent_just_inside_the_bound_is_still_in_flight(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        _dirty_shared_branch(repo, WORKER)
        _agent(transcript, WORKER, silent_for=Timeout.STOP_GUARD_AGENT_SILENCE - 1)
        assert _decide(repo, untracked, transcript=transcript).reason is None

    def test_the_bound_is_one_maximal_foreground_tool_call_and_a_turn(self) -> None:
        assert Timeout.STOP_GUARD_AGENT_SILENCE == (
            Timeout.BASH_MAX // Timeout.MILLISECONDS_PER_SECOND + Timeout.REQUEST_LONG
        )

    def test_an_agent_this_payload_reports_as_no_longer_running(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        _dirty_shared_branch(repo, WORKER)
        _agent(transcript, WORKER)
        tasks = [{"id": WORKER, "type": "subagent", "status": "failed"}]
        self._held_as_before(
            _decide(repo, untracked, transcript=transcript, background_tasks=tasks)
        )

    def test_an_agent_an_earlier_stop_recorded_as_no_longer_running(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        _dirty_shared_branch(repo, WORKER)
        _agent(transcript, WORKER, name="developer")
        record_background_tasks(
            untracked,
            SESSION,
            [{"id": "task-9", "type": "subagent", "status": "killed", "description": "developer"}],
        )
        self._held_as_before(_decide(repo, untracked, transcript=transcript))

    def test_an_unreadable_transcript(
        self,
        repo: Path,
        untracked: Path,
        transcript: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def refuse(path: Path, **_: object) -> object:
            raise PermissionError(13, "Permission denied", str(path))

        _dirty_shared_branch(repo, WORKER)
        _agent(transcript, WORKER)
        monkeypatch.setattr("claude_code_hooks_daemon.utils.session_load.read_tail", refuse)
        self._held_as_before(_decide(repo, untracked, transcript=transcript))

    def test_a_transcript_dated_past_the_clock_skew_in_the_future(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        """Review blocker 2: a negative idle time must not stretch the bound for ever."""
        _dirty_shared_branch(repo, WORKER)
        _agent(transcript, WORKER, silent_for=-(Timeout.TRANSCRIPT_CLOCK_SKEW + 1))
        self._held_as_before(_decide(repo, untracked, transcript=transcript))

    def test_a_transcript_a_little_ahead_within_the_clock_skew_is_still_in_flight(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        _dirty_shared_branch(repo, WORKER)
        _agent(transcript, WORKER, silent_for=-(Timeout.TRANSCRIPT_CLOCK_SKEW - 1))
        assert _decide(repo, untracked, transcript=transcript).reason is None

    @pytest.mark.parametrize(
        "content",
        [b"", b"\x00\xff\xfe garbage \x80" * 1000, b"{not json\n" * 1000],
        ids=["empty", "binary", "invalid-json"],
    )
    def test_a_transcript_with_no_real_record(
        self, repo: Path, untracked: Path, transcript: str, content: bytes
    ) -> None:
        """Review blocker 3: only a parsed prompt makes a record-less transcript a fresh agent."""
        _dirty_shared_branch(repo, WORKER)
        _raw_agent(transcript, WORKER, content)
        self._held_as_before(_decide(repo, untracked, transcript=transcript))

    def test_a_fresh_agent_with_only_its_prompt_is_in_flight(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        _dirty_shared_branch(repo, WORKER)
        _raw_agent(transcript, WORKER, b'{"type":"user","message":{"content":"go"}}\n')
        assert _decide(repo, untracked, transcript=transcript).reason is None

    def test_a_symlinked_transcript(
        self, repo: Path, untracked: Path, transcript: str, tmp_path: Path
    ) -> None:
        """Review minor 4: a link to another session's live transcript is not this agent."""
        _dirty_shared_branch(repo, WORKER)
        foreign = tmp_path / "other-session" / "subagents" / f"agent-{WORKER}.jsonl"
        foreign.parent.mkdir(parents=True)
        foreign.write_text(_agent(transcript, WORKER).read_text())
        os.utime(foreign, (NOW - 10, NOW - 10))
        link = _subagents(transcript) / f"agent-{WORKER}.jsonl"
        link.unlink()
        link.symlink_to(foreign)
        self._held_as_before(_decide(repo, untracked, transcript=transcript))

    def test_a_spent_read_budget_reads_nothing_and_judges_as_before(
        self,
        repo: Path,
        untracked: Path,
        transcript: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Review minor 7: the reads are bounded, and an unread agent is not live."""
        _dirty_shared_branch(repo, WORKER)
        _agent(transcript, WORKER)
        monkeypatch.setattr(Timeout, "STOP_GUARD_LIVE_AGENT_READ_BUDGET", 0)
        self._held_as_before(_decide(repo, untracked, transcript=transcript))

    def test_the_leads_own_touch_never_matches_a_transcript_named_with_no_id(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        """Review minor 6: the main thread's empty touch id is not a sub-agent's."""
        _dirty_shared_branch(repo)
        _agent(transcript, "")
        decision = _decide(repo, untracked, transcript=transcript)
        assert decision.reason is not None
        assert not _in_flight_lines(decision)

    def test_a_live_agent_of_another_session_is_not_this_sessions(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        _dirty_shared_branch(repo)
        _git(repo, "config", "--add", f"branch.{BRANCH}.{TOUCHED_KEY}", f"other-sess:{WORKER}")
        _agent(transcript, WORKER)
        decision = _decide(repo, untracked, transcript=transcript)
        assert decision.reason is not None
        assert not _in_flight_lines(decision)

    def test_a_dirty_tree_and_no_live_agent_at_all_gives_way_as_abandoned(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        _dirty_shared_branch(repo)
        for _ in range(MAX_STOP_BLOCKS):
            self._held_as_before(_decide(repo, untracked, transcript=transcript))
        decision = _decide(repo, untracked, transcript=transcript)
        assert decision.reason is None
        assert any(ABANDONED_RECORD in line and BRANCH in line for line in decision.context)


class TestNoStagingEverythingWhileAnotherAgentIsLive:
    def test_a_dirty_branch_the_live_agent_never_touched_names_it_and_drops_add_all(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        _dirty_shared_branch(repo)
        _agent(transcript, OTHER, name="reviewer")
        decision = _decide(repo, untracked, transcript=transcript)
        assert decision.reason is not None
        assert "add -A" not in decision.reason
        assert "reviewer" in decision.reason
        assert "by name" in decision.reason
        assert "commit its own work" in decision.reason
        assert not _in_flight_lines(decision)

    def test_a_newly_judged_harness_branch_keeps_its_hold_remedies(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        _unpushed_branch(repo, "agent-x", "sub-1")
        where = repo / ".claude" / "worktrees" / "agent-x"
        where.parent.mkdir(parents=True)
        _git(repo, "worktree", "add", "-q", str(where), "agent-x")
        (where / "dirty.txt").write_text("uncommitted\n")
        _agent(transcript, OTHER, name="reviewer")
        reason = _decide(repo, untracked, transcript=transcript).reason
        assert reason is not None
        assert f"git worktree lock {where}" in reason
        assert "by name" not in reason

    def test_other_branches_are_still_held_beside_an_in_flight_one(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        _dirty_shared_branch(repo, WORKER)
        _unpushed_branch(repo, "feat-b")
        _agent(transcript, WORKER)
        decision = _decide(repo, untracked, transcript=transcript)
        assert decision.reason is not None
        assert "feat-b" in decision.reason
        assert f"  - {BRANCH}:" not in decision.reason
        assert any(BRANCH in line for line in _in_flight_lines(decision))


class TestOnlyTheTranscriptsThatCanMatterAreRead:
    """Review minor 7: reads are filtered to the branch's authors before any is made."""

    @staticmethod
    def _spy(monkeypatch: pytest.MonkeyPatch) -> list[str]:
        from claude_code_hooks_daemon.utils import session_load

        read: list[str] = []
        real = session_load.read_tail

        def spy(path: Path, **kwargs: Any) -> Any:
            read.append(path.name)
            return real(path, **kwargs)

        monkeypatch.setattr(session_load, "read_tail", spy)
        return read

    def test_an_in_flight_author_is_the_only_transcript_read(
        self,
        repo: Path,
        untracked: Path,
        transcript: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _dirty_shared_branch(repo, WORKER)
        _agent(transcript, WORKER)
        for index in range(5):
            _agent(transcript, f"abystander{index:011d}")
        read = self._spy(monkeypatch)
        assert _decide(repo, untracked, transcript=transcript).reason is None
        assert read == [f"agent-{WORKER}.jsonl"]

    def test_the_remedy_check_stops_at_the_first_live_bystander(
        self,
        repo: Path,
        untracked: Path,
        transcript: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _dirty_shared_branch(repo)
        for index in range(5):
            _agent(transcript, f"abystander{index:011d}", silent_for=10.0 + index)
        read = self._spy(monkeypatch)
        reason = _decide(repo, untracked, transcript=transcript).reason
        assert reason is not None and "add -A" not in reason
        assert read == ["agent-abystander00000000000.jsonl"]

    def test_a_clean_stop_reads_nothing(
        self,
        repo: Path,
        untracked: Path,
        transcript: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _agent(transcript, WORKER)
        read = self._spy(monkeypatch)
        assert _decide(repo, untracked, transcript=transcript).reason is None
        assert read == []


class TestASubAgentStop:
    def test_its_own_transcript_never_keeps_its_branch_in_flight(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        _dirty_shared_branch(repo, WORKER)
        _agent(transcript, WORKER)
        decision = _decide(repo, untracked, transcript=transcript, agent=WORKER)
        assert decision.reason is not None
        assert "add -A" in decision.reason
        assert not _in_flight_lines(decision)

    def test_a_live_sibling_on_its_branch_keeps_it_in_flight(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        _dirty_shared_branch(repo, WORKER, OTHER)
        _agent(transcript, WORKER)
        _agent(transcript, OTHER, name="sibling")
        decision = _decide(repo, untracked, transcript=transcript, agent=WORKER)
        assert decision.reason is None
        assert any("sibling" in line for line in _in_flight_lines(decision))
        assert _state(untracked, WORKER)["in_flight"] == [BRANCH]
