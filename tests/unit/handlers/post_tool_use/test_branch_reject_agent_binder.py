"""Tests for BranchRejectAgentBinderHandler (Plan 00620 Task 2.2 item 4b).

The PostToolUse ``Agent`` binder fills the dispatch record's agent id from
``tool_response.agentId``, and only that. It never denies: every failure leaves the
record unbound (so no verdict chains) and lets the tool result through.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants import HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.branch_reject import (
    PROMPT_MARKER,
    REVIEWER_AGENT_TYPE,
    DispatchRecord,
    RejectStore,
    new_id,
)
from claude_code_hooks_daemon.handlers.post_tool_use import branch_reject_agent_binder as binder
from claude_code_hooks_daemon.handlers.post_tool_use.branch_reject_agent_binder import (
    BranchRejectAgentBinderHandler,
)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    return project.resolve()


@pytest.fixture
def handler(root: Path, monkeypatch: pytest.MonkeyPatch) -> BranchRejectAgentBinderHandler:
    monkeypatch.setattr(BranchRejectAgentBinderHandler, "_project_root", staticmethod(lambda: root))
    return BranchRejectAgentBinderHandler()


def _store(root: Path) -> RejectStore:
    return RejectStore(root / BranchesConfig().reject.state_dir)


def _dispatched(root: Path, *, agent_id: str = "") -> str:
    nonce = new_id()
    _store(root).create_dispatch(
        DispatchRecord(nonce=nonce, session_id="s1", tool_use_id="toolu_1", agent_id=agent_id)
    )
    return nonce


def _prompt(nonce: str) -> str:
    return f"{PROMPT_MARKER}{nonce}\nReview the branch."


def _event(
    nonce: str,
    *,
    response: Any = None,
    session_id: Any = "s1",
    tool_use_id: Any = "toolu_1",
    tool_name: str = "Agent",
    prompt: Any = None,
) -> dict[str, Any]:
    return {
        "hook_event_name": "PostToolUse",
        "session_id": session_id,
        "tool_use_id": tool_use_id,
        "tool_name": tool_name,
        "tool_input": {
            "subagent_type": REVIEWER_AGENT_TYPE,
            "description": "branch review",
            "prompt": _prompt(nonce) if prompt is None else prompt,
        },
        "tool_response": (
            {"status": "async_launched", "agentId": "agent-a1"} if response is None else response
        ),
    }


def _agent_id(root: Path, nonce: str) -> str:
    record = _store(root).read_dispatch(nonce)
    assert record is not None
    return record.agent_id


def _files(root: Path) -> list[str]:
    state = root / BranchesConfig().reject.state_dir
    if not state.exists():
        return []
    return sorted(str(p.relative_to(state)) for p in state.rglob("*") if p.is_file())


class TestShape:
    def test_identity(self, handler: BranchRejectAgentBinderHandler) -> None:
        assert handler.priority == Priority.BRANCH_REJECT_AGENT_BINDER
        assert handler.terminal is False
        assert HandlerTag.NON_TERMINAL in handler.tags
        assert handler.get_claude_md() is None

    def test_declares_branches_for_registry_injection(self) -> None:
        assert isinstance(BranchRejectAgentBinderHandler()._branches, BranchesConfig)


class TestMatches:
    def test_matches_a_review_prompt_dispatch(
        self, handler: BranchRejectAgentBinderHandler
    ) -> None:
        assert handler.matches(_event(new_id())) is True

    def test_matches_task_tool_too(self, handler: BranchRejectAgentBinderHandler) -> None:
        assert handler.matches(_event(new_id(), tool_name="Task")) is True

    @pytest.mark.parametrize(
        "prompt",
        ["review the branch", f"note: {PROMPT_MARKER}{'a' * 32}", 7, f"{PROMPT_MARKER}xyz"],
    )
    def test_ignores_a_prompt_without_a_nonce_first_line(
        self, handler: BranchRejectAgentBinderHandler, prompt: Any
    ) -> None:
        assert handler.matches(_event(new_id(), prompt=prompt)) is False

    def test_ignores_other_tools(self, handler: BranchRejectAgentBinderHandler) -> None:
        assert handler.matches(_event(new_id(), tool_name="Bash")) is False

    @pytest.mark.parametrize("tool_use_id", ["", None, 5])
    def test_ignores_a_call_without_tool_use_id(
        self, handler: BranchRejectAgentBinderHandler, tool_use_id: Any
    ) -> None:
        assert handler.matches(_event(new_id(), tool_use_id=tool_use_id)) is False

    def test_ignores_a_non_dict_tool_input(self, handler: BranchRejectAgentBinderHandler) -> None:
        event = _event(new_id())
        event["tool_input"] = "x"
        assert handler.matches(event) is False

    def test_matches_never_reads_the_store(
        self, handler: BranchRejectAgentBinderHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode() -> Path:
            raise AssertionError("matches must be store-free")

        monkeypatch.setattr(BranchRejectAgentBinderHandler, "_project_root", staticmethod(explode))
        assert handler.matches(_event(new_id())) is True


class TestBinds:
    def test_background_response_binds(
        self, handler: BranchRejectAgentBinderHandler, root: Path
    ) -> None:
        nonce = _dispatched(root)
        result = handler.handle(_event(nonce))
        assert result.decision == Decision.ALLOW
        assert _agent_id(root, nonce) == "agent-a1"

    def test_foreground_response_binds_after_the_agent_finished(
        self, handler: BranchRejectAgentBinderHandler, root: Path
    ) -> None:
        # Foreground order: SubagentStop has already run; PostToolUse still binds.
        nonce = _dispatched(root)
        response = {"status": "completed", "agentId": "agent-f1", "content": []}
        handler.handle(_event(nonce, response=response))
        assert _agent_id(root, nonce) == "agent-f1"

    def test_touches_nothing_but_the_dispatch_record(
        self, handler: BranchRejectAgentBinderHandler, root: Path
    ) -> None:
        nonce = _dispatched(root)
        handler.handle(_event(nonce))
        assert _files(root) == [f"dispatches/{nonce}.json"]


class TestDoesNotBind:
    @pytest.mark.parametrize(
        "response",
        [
            {"status": "completed"},
            {"status": "completed", "agentId": ""},
            {"status": "completed", "agentId": 42},
            {"status": "completed", "agentId": None},
            "not a dict",
            None,
        ],
    )
    def test_no_usable_agent_id(
        self, handler: BranchRejectAgentBinderHandler, root: Path, response: Any
    ) -> None:
        nonce = _dispatched(root)
        event = _event(nonce)
        event["tool_response"] = response
        assert handler.handle(event).decision == Decision.ALLOW
        assert _agent_id(root, nonce) == ""

    def test_other_session(self, handler: BranchRejectAgentBinderHandler, root: Path) -> None:
        nonce = _dispatched(root)
        handler.handle(_event(nonce, session_id="s2"))
        assert _agent_id(root, nonce) == ""

    def test_other_tool_use_id(self, handler: BranchRejectAgentBinderHandler, root: Path) -> None:
        nonce = _dispatched(root)
        handler.handle(_event(nonce, tool_use_id="toolu_2"))
        assert _agent_id(root, nonce) == ""

    def test_already_bound_record_is_not_rebound(
        self, handler: BranchRejectAgentBinderHandler, root: Path
    ) -> None:
        nonce = _dispatched(root, agent_id="agent-first")
        handler.handle(_event(nonce, response={"agentId": "agent-second"}))
        assert _agent_id(root, nonce) == "agent-first"

    def test_no_dispatch_record_writes_nothing(
        self, handler: BranchRejectAgentBinderHandler, root: Path
    ) -> None:
        assert handler.handle(_event(new_id())).decision == Decision.ALLOW
        assert _files(root) == []


class TestFailsQuietly:
    def test_unreadable_record_allows_and_stays_unbound(
        self, handler: BranchRejectAgentBinderHandler, root: Path
    ) -> None:
        nonce = new_id()
        path = root / BranchesConfig().reject.state_dir / "dispatches" / f"{nonce}.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        assert handler.handle(_event(nonce)).decision == Decision.ALLOW
        assert path.read_text(encoding="utf-8") == "{not json"

    def test_uninitialised_project_root_allows(
        self, handler: BranchRejectAgentBinderHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def uninitialised() -> Path:
            raise RuntimeError("ProjectContext not initialised")

        monkeypatch.setattr(
            BranchRejectAgentBinderHandler, "_project_root", staticmethod(uninitialised)
        )
        assert handler.handle(_event(new_id())).decision == Decision.ALLOW

    def test_main_checkout_failure_allows_and_writes_nothing(
        self,
        handler: BranchRejectAgentBinderHandler,
        root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        nonce = _dispatched(root)

        def broken(repo: Path) -> Path:
            raise OSError("git unavailable")

        monkeypatch.setattr(binder, "main_checkout", broken)
        assert handler.handle(_event(nonce)).decision == Decision.ALLOW
        assert _agent_id(root, nonce) == ""


def test_acceptance_tests_declared(handler: BranchRejectAgentBinderHandler) -> None:
    tests = handler.get_acceptance_tests()
    assert tests
    assert all(t.expected_decision == Decision.ALLOW for t in tests)
