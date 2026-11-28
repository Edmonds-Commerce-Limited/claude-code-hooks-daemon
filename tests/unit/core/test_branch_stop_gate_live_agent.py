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

    def test_an_unpushed_branch_with_a_live_author_is_not_left_unpushed(
        self, repo: Path, untracked: Path, transcript: str
    ) -> None:
        _unpushed_branch(repo, "feat-a", WORKER)
        _agent(transcript, WORKER)
        decisions = [
            _decide(repo, untracked, transcript=transcript) for _ in range(MAX_STOP_BLOCKS + 1)
        ]
        assert all(decision.reason is None for decision in decisions)
        assert not any("left unpushed" in line for line in decisions[-1].context)
        assert _state(untracked)["in_flight"] == ["feat-a"]

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
