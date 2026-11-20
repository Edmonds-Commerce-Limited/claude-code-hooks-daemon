"""Tests for BranchRejectVerdictRecorderHandler (Plan 00620 Task 2.2 item 5).

The SubagentStop recorder is a thin shell over ``core.branch_reject.record_review_stop``:
it resolves the reviewer's own transcript and ``meta.json``, takes the reply strictly
from the payload, and lets the core decide. It never blocks a stop. Every failure writes
no verdict, which is the closed state: no verdict, no removal.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants import HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.branch_reject import (
    DECISION_NO_VALUE,
    REVIEWER_AGENT_TYPE,
    VERDICT_BLOCK_END,
    VERDICT_BLOCK_START,
    DispatchCall,
    Inventory,
    RejectError,
    RejectRequest,
    RejectStore,
    admit_dispatch,
    bind_agent,
    compose_prompt,
    new_id,
    prompt_digest,
)
from claude_code_hooks_daemon.handlers.subagent_stop import (
    branch_reject_verdict_recorder as recorder,
)
from claude_code_hooks_daemon.handlers.subagent_stop.branch_reject_verdict_recorder import (
    BranchRejectVerdictRecorderHandler,
)

OPUS = "claude-opus-5-5"
SESSION = "s1"
TOOL_USE = "toolu_1"
AGENT = "a0123456789abcdef"
SHA_A = "3" * 40
TIP = "1" * 40
DEFAULT = "2" * 40


@pytest.fixture
def root(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    return project.resolve()


@pytest.fixture
def handler(root: Path, monkeypatch: pytest.MonkeyPatch) -> BranchRejectVerdictRecorderHandler:
    monkeypatch.setattr(
        BranchRejectVerdictRecorderHandler, "_project_root", staticmethod(lambda: root)
    )
    return BranchRejectVerdictRecorderHandler()


def _store(root: Path) -> RejectStore:
    return RejectStore(root / BranchesConfig().reject.state_dir)


def _requested(root: Path) -> tuple[RejectRequest, str]:
    """A request, its dispatch admitted and bound to AGENT, as the gate and binder leave it."""
    store = _store(root)
    nonce = new_id()
    prompt = compose_prompt(
        nonce=nonce,
        branch="feat",
        tip=TIP,
        default_sha=DEFAULT,
        commits=((SHA_A, "subject"),),
        paths=("src/feature.py",),
        keep_reasons=(),
    )
    request = RejectRequest(
        nonce=nonce,
        branch="feat",
        tip=TIP,
        default_sha=DEFAULT,
        inventory=Inventory(commits=(SHA_A,), paths=("src/feature.py",)),
        reviewers_required=1,
        prompt_sha256=prompt_digest(prompt),
        created_at=1_800_000_000.0 - 60,
    )
    store.write_request(request)
    admit_dispatch(
        DispatchCall(
            session_id=SESSION,
            tool_use_id=TOOL_USE,
            subagent_type=REVIEWER_AGENT_TYPE,
            prompt=prompt,
            predicted_family="opus",
            resume=False,
            definition_current=True,
        ),
        store,
    )
    assert bind_agent(store, nonce, session_id=SESSION, tool_use_id=TOOL_USE, agent_id=AGENT)
    return request, prompt


def _reply(request: RejectRequest) -> str:
    return "\n".join(
        [
            "I read every commit.",
            "",
            f"{VERDICT_BLOCK_START} nonce={request.nonce} tip={request.tip}",
            f"commit {SHA_A} {DECISION_NO_VALUE}: scratch work",
            f"path src/feature.py {DECISION_NO_VALUE}: scratch file",
            f"overall {DECISION_NO_VALUE}",
            VERDICT_BLOCK_END,
        ]
    )


def _rec(kind: str, **fields: Any) -> dict[str, Any]:
    return {"isSidechain": True, "agentId": AGENT, "sessionId": SESSION, "type": kind, **fields}


def _transcript(
    directory: Path, prompt: str, reply: str, *, meta: dict[str, Any] | None = None
) -> Path:
    """``agent-<id>.jsonl`` and its ``meta.json``, in the shape of a live agent's."""
    directory.mkdir(parents=True, exist_ok=True)
    records = [
        _rec("user", promptId="p1", message={"role": "user", "content": prompt}),
        _rec(
            "assistant",
            message={
                "role": "assistant",
                "model": OPUS,
                "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}],
            },
        ),
        _rec(
            "user",
            message={
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}],
            },
        ),
        _rec(
            "assistant",
            message={"role": "assistant", "model": OPUS, "content": [{"type": "text", "text": reply}]},
        ),
    ]
    path = directory / f"agent-{AGENT}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    if meta is None:
        meta = {"agentType": REVIEWER_AGENT_TYPE, "toolUseId": TOOL_USE, "model": "opus"}
    if meta:
        (directory / f"agent-{AGENT}.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return path


def _event(transcript: Path, reply: Any, **overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "hook_event_name": "SubagentStop",
        "session_id": SESSION,
        "transcript_path": str(transcript.parent.parent / f"{SESSION}.jsonl"),
        "stop_hook_active": False,
        "agent_id": AGENT,
        "agent_type": REVIEWER_AGENT_TYPE,
        "agent_transcript_path": str(transcript),
        "last_assistant_message": reply,
    }
    event.update(overrides)
    return event


def _state_files(root: Path, sub: str) -> list[str]:
    directory = root / BranchesConfig().reject.state_dir / sub
    if not directory.exists():
        return []
    return sorted(p.name for p in directory.iterdir() if p.is_file())


def _setup(root: Path, tmp_path: Path) -> tuple[RejectRequest, Path, str]:
    request, prompt = _requested(root)
    reply = _reply(request)
    transcript = _transcript(tmp_path / "transcripts" / SESSION / "subagents", prompt, reply)
    return request, transcript, reply


class TestShape:
    def test_identity(self, handler: BranchRejectVerdictRecorderHandler) -> None:
        assert handler.priority == Priority.BRANCH_REJECT_VERDICT_RECORDER == 13
        assert handler.terminal is False
        assert HandlerTag.NON_TERMINAL in handler.tags
        assert HandlerTag.WORKFLOW in handler.tags
        assert HandlerTag.BLOCKING not in handler.tags
        assert HandlerTag.SAFETY not in handler.tags
        assert handler.get_claude_md() is None

    def test_declares_branches_for_registry_injection(self) -> None:
        assert isinstance(BranchRejectVerdictRecorderHandler()._branches, BranchesConfig)


class TestMatches:
    def test_matches_a_reviewer_stop(
        self, handler: BranchRejectVerdictRecorderHandler, tmp_path: Path
    ) -> None:
        assert handler.matches(_event(tmp_path / "agent.jsonl", "x")) is True

    @pytest.mark.parametrize("active", [True, "true", 1, None])
    def test_matches_a_re_entry_stop(
        self, handler: BranchRejectVerdictRecorderHandler, tmp_path: Path, active: Any
    ) -> None:
        event = _event(tmp_path / "agent.jsonl", "x", stop_hook_active=active)
        assert handler.matches(event) is True

    @pytest.mark.parametrize("agent_type", ["Explore", "fork", "", None, 5])
    def test_ignores_other_agents(
        self, handler: BranchRejectVerdictRecorderHandler, tmp_path: Path, agent_type: Any
    ) -> None:
        event = _event(tmp_path / "agent.jsonl", "x", agent_type=agent_type)
        assert handler.matches(event) is False

    def test_ignores_a_synthetic_stop(
        self,
        handler: BranchRejectVerdictRecorderHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(recorder, "is_synthetic_event", lambda _event: True)
        assert handler.matches(_event(tmp_path / "agent.jsonl", "x")) is False

    def test_matches_never_reads_the_store(
        self,
        handler: BranchRejectVerdictRecorderHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def explode() -> Path:
            raise AssertionError("matches must be store-free")

        monkeypatch.setattr(
            BranchRejectVerdictRecorderHandler, "_project_root", staticmethod(explode)
        )
        assert handler.matches(_event(tmp_path / "missing" / "agent.jsonl", "x")) is True


class TestHandle:
    def test_a_clean_stop_records_the_verdict(
        self, handler: BranchRejectVerdictRecorderHandler, root: Path, tmp_path: Path
    ) -> None:
        request, transcript, reply = _setup(root, tmp_path)
        result = handler.handle(_event(transcript, reply))
        assert result.decision == Decision.ALLOW
        assert _state_files(root, "verdicts") == [f"{request.nonce}.json"]
        verdict = _store(root).read_verdict(request.nonce)
        assert verdict is not None
        assert verdict.reviewer.agent_id == AGENT
        assert verdict.reviewer.models == (OPUS,)

    def test_the_dispatch_agent_id_and_ledger_are_untouched(
        self, handler: BranchRejectVerdictRecorderHandler, root: Path, tmp_path: Path
    ) -> None:
        request, transcript, reply = _setup(root, tmp_path)
        before = _store(root).read_dispatch(request.nonce)
        handler.handle(_event(transcript, reply))
        assert _store(root).read_dispatch(request.nonce) == before
        ledger = root / BranchesConfig().reject.ledger_path
        assert not ledger.exists()

    def test_a_second_stop_withdraws_the_verdict(
        self, handler: BranchRejectVerdictRecorderHandler, root: Path, tmp_path: Path
    ) -> None:
        _request, transcript, reply = _setup(root, tmp_path)
        handler.handle(_event(transcript, reply))
        result = handler.handle(_event(transcript, reply))
        assert result.decision == Decision.ALLOW
        assert _state_files(root, "verdicts") == []

    @pytest.mark.parametrize("active", [True, "true", "false", 1, 0, None])
    def test_anything_but_a_literal_false_stop_hook_active_records_nothing(
        self,
        handler: BranchRejectVerdictRecorderHandler,
        root: Path,
        tmp_path: Path,
        active: Any,
    ) -> None:
        _request, transcript, reply = _setup(root, tmp_path)
        result = handler.handle(_event(transcript, reply, stop_hook_active=active))
        assert result.decision == Decision.ALLOW
        assert _state_files(root, "verdicts") == []

    def test_a_missing_stop_hook_active_records_nothing(
        self, handler: BranchRejectVerdictRecorderHandler, root: Path, tmp_path: Path
    ) -> None:
        _request, transcript, reply = _setup(root, tmp_path)
        event = _event(transcript, reply)
        del event["stop_hook_active"]
        handler.handle(event)
        assert _state_files(root, "verdicts") == []

    def test_a_re_entry_withdraws_an_earlier_verdict(
        self, handler: BranchRejectVerdictRecorderHandler, root: Path, tmp_path: Path
    ) -> None:
        _request, transcript, reply = _setup(root, tmp_path)
        handler.handle(_event(transcript, reply))
        handler.handle(_event(transcript, reply, stop_hook_active=True))
        assert _state_files(root, "verdicts") == []

    @pytest.mark.parametrize("reply", [None, 7, "", "a different reply"])
    def test_the_reply_comes_only_from_the_payload(
        self,
        handler: BranchRejectVerdictRecorderHandler,
        root: Path,
        tmp_path: Path,
        reply: Any,
    ) -> None:
        _request, transcript, _real = _setup(root, tmp_path)
        result = handler.handle(_event(transcript, reply))
        assert result.decision == Decision.ALLOW
        assert _state_files(root, "verdicts") == []

    @pytest.mark.parametrize("agent_id", ["../x", "", None, "a/b"])
    def test_an_unsafe_agent_id_writes_nothing(
        self,
        handler: BranchRejectVerdictRecorderHandler,
        root: Path,
        tmp_path: Path,
        agent_id: Any,
    ) -> None:
        _request, transcript, reply = _setup(root, tmp_path)
        result = handler.handle(_event(transcript, reply, agent_id=agent_id))
        assert result.decision == Decision.ALLOW
        assert _state_files(root, "verdicts") == []
        assert _state_files(root, "stops") == []

    def test_a_transcript_of_another_agent_writes_nothing(
        self, handler: BranchRejectVerdictRecorderHandler, root: Path, tmp_path: Path
    ) -> None:
        _request, transcript, reply = _setup(root, tmp_path)
        handler.handle(_event(transcript, reply, agent_id="aother"))
        assert _state_files(root, "verdicts") == []
        assert _state_files(root, "stops") == []

    def test_a_missing_meta_writes_nothing_and_takes_no_marker(
        self, handler: BranchRejectVerdictRecorderHandler, root: Path, tmp_path: Path
    ) -> None:
        request, prompt = _requested(root)
        reply = _reply(request)
        transcript = _transcript(tmp_path / "t", prompt, reply, meta={})
        handler.handle(_event(transcript, reply))
        assert _state_files(root, "verdicts") == []
        assert _state_files(root, "stops") == []

    def test_a_fork_meta_writes_nothing(
        self, handler: BranchRejectVerdictRecorderHandler, root: Path, tmp_path: Path
    ) -> None:
        request, prompt = _requested(root)
        reply = _reply(request)
        meta = {"agentType": "fork", "toolUseId": TOOL_USE}
        transcript = _transcript(tmp_path / "t", prompt, reply, meta=meta)
        handler.handle(_event(transcript, reply))
        assert _state_files(root, "verdicts") == []

    def test_an_unresolvable_transcript_writes_nothing(
        self, handler: BranchRejectVerdictRecorderHandler, root: Path, tmp_path: Path
    ) -> None:
        _request, transcript, reply = _setup(root, tmp_path)
        event = _event(transcript, reply, agent_transcript_path=str(tmp_path / "nope.jsonl"))
        result = handler.handle(event)
        assert result.decision == Decision.ALLOW
        assert _state_files(root, "verdicts") == []


class TestFailsClosed:
    def test_an_uninitialised_project_allows_and_writes_nothing(
        self,
        handler: BranchRejectVerdictRecorderHandler,
        root: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _request, transcript, reply = _setup(root, tmp_path)

        def uninitialised() -> Path:
            raise RuntimeError("ProjectContext not initialised")

        monkeypatch.setattr(
            BranchRejectVerdictRecorderHandler, "_project_root", staticmethod(uninitialised)
        )
        assert handler.handle(_event(transcript, reply)).decision == Decision.ALLOW
        assert _state_files(root, "verdicts") == []

    def test_an_unreadable_transcript_allows_and_writes_nothing(
        self,
        handler: BranchRejectVerdictRecorderHandler,
        root: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _request, transcript, reply = _setup(root, tmp_path)

        def unreadable(_path: Path) -> Any:
            raise RejectError("too big")

        monkeypatch.setattr(recorder, "read_review_transcript", unreadable)
        assert handler.handle(_event(transcript, reply)).decision == Decision.ALLOW
        assert _state_files(root, "verdicts") == []

    @pytest.mark.parametrize("exc", [OSError("disk"), ValueError("bad")])
    def test_a_store_failure_allows_and_writes_nothing(
        self,
        handler: BranchRejectVerdictRecorderHandler,
        root: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        exc: Exception,
    ) -> None:
        _request, transcript, reply = _setup(root, tmp_path)

        def broken(*_args: Any, **_kwargs: Any) -> str:
            raise exc

        monkeypatch.setattr(recorder, "record_review_stop", broken)
        assert handler.handle(_event(transcript, reply)).decision == Decision.ALLOW
        assert _state_files(root, "verdicts") == []


class TestAcceptance:
    def test_declares_one_allow_case(self, handler: BranchRejectVerdictRecorderHandler) -> None:
        tests = handler.get_acceptance_tests()
        assert len(tests) == 1
        assert tests[0].expected_decision == Decision.ALLOW
