"""Tests for the reviewer dispatch gate and the agent binding (Plan 00620 Task 2.2 item 4).

PreToolUse ``Agent`` admits a reviewer dispatch only when its prompt is byte-equal to an
outstanding request's, and writes the dispatch record (empty ``agent_id``) exclusively.
PostToolUse alone fills ``agent_id``. Neither ever touches the ledger or deletes anything.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.branch_reject import (
    PROMPT_MARKER,
    REVIEWER_AGENT_TYPE,
    DispatchCall,
    DispatchRecord,
    Inventory,
    RejectError,
    RejectRefusedError,
    RejectRequest,
    RejectStore,
    admit_dispatch,
    bind_agent,
    compose_prompt,
    dispatch_problems,
    is_reviewer_dispatch,
    new_id,
    prompt_digest,
)

NOW = 1_800_000_000.0


@pytest.fixture
def store(tmp_path: Path) -> RejectStore:
    return RejectStore(tmp_path / "state")


def _request(store: RejectStore) -> tuple[RejectRequest, str]:
    nonce = new_id()
    prompt = compose_prompt(
        nonce=nonce,
        branch="feat",
        tip="1" * 40,
        default_sha="2" * 40,
        commits=(("3" * 40, "add feature"),),
        paths=("src/feature.py",),
        keep_reasons=(),
    )
    request = RejectRequest(
        nonce=nonce,
        branch="feat",
        tip="1" * 40,
        default_sha="2" * 40,
        inventory=Inventory(commits=("3" * 40,), paths=("src/feature.py",)),
        reviewers_required=1,
        prompt_sha256=prompt_digest(prompt),
        created_at=NOW,
    )
    store.write_request(request)
    return request, prompt


def _call(
    prompt: str,
    *,
    session_id: str = "s1",
    tool_use_id: str = "toolu_1",
    subagent_type: str = REVIEWER_AGENT_TYPE,
    predicted_family: str | None = "opus",
    resume: bool = False,
    definition_current: bool = True,
) -> DispatchCall:
    return DispatchCall(
        session_id=session_id,
        tool_use_id=tool_use_id,
        subagent_type=subagent_type,
        prompt=prompt,
        predicted_family=predicted_family,
        resume=resume,
        definition_current=definition_current,
    )


class TestIsReviewerDispatch:
    def test_the_reviewer_type_is_a_reviewer_dispatch(self) -> None:
        assert is_reviewer_dispatch(REVIEWER_AGENT_TYPE, "anything")

    def test_a_marker_prompt_is_a_reviewer_dispatch(self) -> None:
        assert is_reviewer_dispatch("general-purpose", f"{PROMPT_MARKER}{'0' * 32}\n")

    def test_an_unrelated_dispatch_is_not(self) -> None:
        assert not is_reviewer_dispatch("general-purpose", "review this plan")

    def test_the_marker_quoted_mid_prompt_is_not(self) -> None:
        """A prompt discussing the route is not a review dispatch."""
        assert not is_reviewer_dispatch("general-purpose", f"see {PROMPT_MARKER}x")


class TestDispatchProblems:
    def test_the_canonical_dispatch_passes(self, store: RejectStore) -> None:
        _, prompt = _request(store)
        assert dispatch_problems(_call(prompt), store) == []

    def test_a_marker_prompt_on_another_type_is_refused(self, store: RejectStore) -> None:
        _, prompt = _request(store)
        assert dispatch_problems(_call(prompt, subagent_type="general-purpose"), store)

    def test_the_reviewer_type_with_another_prompt_is_refused(self, store: RejectStore) -> None:
        _request(store)
        assert dispatch_problems(_call("confirm this branch is obsolete"), store)

    def test_one_changed_byte_is_refused(self, store: RejectStore) -> None:
        _, prompt = _request(store)
        assert dispatch_problems(_call(prompt + "\n"), store)
        changed = prompt.replace("Doubt means keep", "Doubt means go")
        assert dispatch_problems(_call(changed), store)

    def test_a_nonce_with_no_request_is_refused(self, store: RejectStore) -> None:
        _, prompt = _request(store)
        other = prompt.replace(prompt.split("\n", 1)[0], f"{PROMPT_MARKER}{new_id()}")
        assert any("request" in p for p in dispatch_problems(_call(other), store))

    def test_an_already_dispatched_nonce_is_refused(self, store: RejectStore) -> None:
        request, prompt = _request(store)
        store.write_dispatch(DispatchRecord(request.nonce, "s1", "toolu_0", ""))
        assert any("already" in p for p in dispatch_problems(_call(prompt), store))

    @pytest.mark.parametrize("family", ["sonnet", "haiku", None, "nonsense"])
    def test_a_predicted_family_below_opus_is_refused(
        self, store: RejectStore, family: str | None
    ) -> None:
        _, prompt = _request(store)
        assert dispatch_problems(_call(prompt, predicted_family=family), store)

    def test_a_resume_is_refused(self, store: RejectStore) -> None:
        _, prompt = _request(store)
        assert dispatch_problems(_call(prompt, resume=True), store)

    def test_a_definition_that_is_not_current_is_refused(self, store: RejectStore) -> None:
        _, prompt = _request(store)
        assert dispatch_problems(_call(prompt, definition_current=False), store)

    def test_an_empty_session_is_refused(self, store: RejectStore) -> None:
        _, prompt = _request(store)
        assert dispatch_problems(_call(prompt, session_id=""), store)

    def test_an_empty_tool_use_id_is_refused(self, store: RejectStore) -> None:
        _, prompt = _request(store)
        assert dispatch_problems(_call(prompt, tool_use_id=""), store)

    def test_an_unreadable_request_is_refused(self, store: RejectStore) -> None:
        request, prompt = _request(store)
        (store.root / "requests" / f"{request.nonce}.json").write_text("{", encoding="utf-8")
        assert dispatch_problems(_call(prompt), store)


class TestAdmitDispatch:
    def test_admission_writes_an_unbound_record(self, store: RejectStore) -> None:
        request, prompt = _request(store)
        record = admit_dispatch(_call(prompt), store)
        assert record == DispatchRecord(request.nonce, "s1", "toolu_1", "")
        assert store.read_dispatch(request.nonce) == record

    def test_a_refused_dispatch_writes_nothing(self, store: RejectStore) -> None:
        request, prompt = _request(store)
        with pytest.raises(RejectRefusedError):
            admit_dispatch(_call(prompt, predicted_family="sonnet"), store)
        assert store.read_dispatch(request.nonce) is None

    def test_a_second_dispatch_of_one_nonce_is_refused(self, store: RejectStore) -> None:
        """Two parallel calls with one prompt: the second never overwrites the first."""
        request, prompt = _request(store)
        admit_dispatch(_call(prompt), store)
        with pytest.raises(RejectRefusedError):
            admit_dispatch(_call(prompt, tool_use_id="toolu_2"), store)
        record = store.read_dispatch(request.nonce)
        assert record is not None
        assert record.tool_use_id == "toolu_1"

    def test_the_exclusive_create_refuses_an_existing_file(self, store: RejectStore) -> None:
        """The race the check above cannot see: the file appears between check and write."""
        request, _ = _request(store)
        store.create_dispatch(DispatchRecord(request.nonce, "s1", "toolu_1", ""))
        with pytest.raises(RejectRefusedError):
            store.create_dispatch(DispatchRecord(request.nonce, "s1", "toolu_2", ""))
        record = store.read_dispatch(request.nonce)
        assert record is not None
        assert record.tool_use_id == "toolu_1"

    def test_the_gate_never_touches_the_ledger_or_a_branch(
        self, store: RejectStore, tmp_path: Path
    ) -> None:
        _, prompt = _request(store)
        before = {p.relative_to(tmp_path) for p in tmp_path.rglob("*")}
        record = admit_dispatch(_call(prompt), store)
        bind_agent(store, record.nonce, session_id="s1", tool_use_id="toolu_1", agent_id="a1")
        after = {p.relative_to(tmp_path) for p in tmp_path.rglob("*")}
        assert before <= after
        assert after - before == {
            Path("state/dispatches"),
            Path("state/dispatches") / f"{record.nonce}.json",
        }


class TestBindAgent:
    def _admitted(self, store: RejectStore) -> DispatchRecord:
        _, prompt = _request(store)
        return admit_dispatch(_call(prompt), store)

    def test_the_matching_call_binds_the_agent(self, store: RejectStore) -> None:
        record = self._admitted(store)
        assert bind_agent(
            store, record.nonce, session_id="s1", tool_use_id="toolu_1", agent_id="a1"
        )
        assert store.read_dispatch(record.nonce) == replace(record, agent_id="a1")

    def test_a_bound_record_is_never_rebound(self, store: RejectStore) -> None:
        record = self._admitted(store)
        bind_agent(store, record.nonce, session_id="s1", tool_use_id="toolu_1", agent_id="a1")
        assert not bind_agent(
            store, record.nonce, session_id="s1", tool_use_id="toolu_1", agent_id="a2"
        )
        bound = store.read_dispatch(record.nonce)
        assert bound is not None
        assert bound.agent_id == "a1"

    @pytest.mark.parametrize(
        ("session_id", "tool_use_id", "agent_id"),
        [("s2", "toolu_1", "a1"), ("s1", "toolu_9", "a1"), ("s1", "toolu_1", "")],
    )
    def test_a_mismatched_or_empty_binding_is_a_no_op(
        self, store: RejectStore, session_id: str, tool_use_id: str, agent_id: str
    ) -> None:
        record = self._admitted(store)
        assert not bind_agent(
            store,
            record.nonce,
            session_id=session_id,
            tool_use_id=tool_use_id,
            agent_id=agent_id,
        )
        assert store.read_dispatch(record.nonce) == record

    def test_no_record_is_a_no_op(self, store: RejectStore) -> None:
        assert not bind_agent(store, new_id(), session_id="s1", tool_use_id="t", agent_id="a1")
        assert not (store.root / "dispatches").exists()

    def test_a_malformed_nonce_raises(self, store: RejectStore) -> None:
        with pytest.raises(RejectError):
            bind_agent(store, "../x", session_id="s1", tool_use_id="t", agent_id="a1")
