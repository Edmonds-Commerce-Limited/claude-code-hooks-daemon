"""Tests for the SubagentStop verdict recorder's core (Plan 00620 Task 2.2 item 5).

The recorder turns a reviewer agent's final reply into a ``Verdict`` (and a
``KeepRecord`` on keep). Every fact but the decisions, reasons and citations comes from
the request; the reviewer facts come from the agent's own transcript. Fail closed: a
verdict exists only from a clean, final stop, so a second stop of the same nonce (a
stop-hook block, then a retry) withdraws it.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import BranchRejectConfig
from claude_code_hooks_daemon.core.branch_reject import (
    DECISION_KEEP,
    DECISION_NO_VALUE,
    KIND_COMMIT,
    KIND_PATH,
    REVIEWER_AGENT_TYPE,
    STOP_IGNORED,
    STOP_RECORDED,
    STOP_WITHDRAWN,
    VERDICT_BLOCK_END,
    VERDICT_BLOCK_START,
    DispatchCall,
    Inventory,
    RejectError,
    RejectRefusedError,
    RejectRequest,
    RejectStore,
    ReviewStop,
    TranscriptFacts,
    admit_dispatch,
    bind_agent,
    compose_prompt,
    compute_inventory,
    new_id,
    parse_verdict_reply,
    prompt_digest,
    read_review_transcript,
    record_review_stop,
    verdict_problems,
)

NOW = 1_800_000_000.0
OPUS = "claude-opus-5-5"
SESSION = "s1"
TOOL_USE = "toolu_1"
AGENT = "a0123456789abcdef"
SHA_A = "3" * 40
SHA_B = "4" * 40
TIP = "1" * 40
DEFAULT = "2" * 40


@pytest.fixture
def store(tmp_path: Path) -> RejectStore:
    return RejectStore(tmp_path / "state")


def _request(
    store: RejectStore,
    *,
    commits: tuple[str, ...] = (SHA_A,),
    paths: tuple[str, ...] = ("src/feature.py",),
    branch: str = "feat",
    tip: str = TIP,
    default_sha: str = DEFAULT,
) -> tuple[RejectRequest, str]:
    nonce = new_id()
    prompt = compose_prompt(
        nonce=nonce,
        branch=branch,
        tip=tip,
        default_sha=default_sha,
        commits=tuple((sha, "subject") for sha in commits),
        paths=paths,
        keep_reasons=(),
    )
    request = RejectRequest(
        nonce=nonce,
        branch=branch,
        tip=tip,
        default_sha=default_sha,
        inventory=Inventory(commits=commits, paths=paths),
        reviewers_required=1,
        prompt_sha256=prompt_digest(prompt),
        created_at=NOW - 60,
    )
    store.write_request(request)
    return request, prompt


def _admit(store: RejectStore, prompt: str, *, bind: bool = True) -> None:
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
    if bind:
        nonce = prompt.split("\n", 1)[0].rsplit(" ", 1)[1]
        assert bind_agent(store, nonce, session_id=SESSION, tool_use_id=TOOL_USE, agent_id=AGENT)


def _reply(
    request: RejectRequest,
    *,
    decision: str = DECISION_NO_VALUE,
    overall: str | None = None,
    suffix: str = "",
) -> str:
    lines = [
        "I read every commit.",
        "",
        f"{VERDICT_BLOCK_START} nonce={request.nonce} tip={request.tip}",
        *(f"commit {sha} {decision}: scratch work" for sha in request.inventory.commits),
        *(f"path {path} {decision}: scratch file" for path in request.inventory.paths),
        f"overall {overall or decision}",
        VERDICT_BLOCK_END,
    ]
    return "\n".join(lines) + suffix


def _record(kind: str, **fields: Any) -> dict[str, Any]:
    return {"isSidechain": True, "agentId": AGENT, "sessionId": SESSION, "type": kind, **fields}


def _assistant(content: list[dict[str, Any]], model: Any = OPUS) -> dict[str, Any]:
    return _record("assistant", message={"role": "assistant", "model": model, "content": content})


def _transcript_records(
    prompt: str,
    reply: str,
    *,
    models: tuple[Any, ...] = (OPUS,),
    extra: tuple[dict[str, Any], ...] = (),
) -> list[dict[str, Any]]:
    """A real agent transcript's shape (checked against live ones, see the journal)."""
    records: list[dict[str, Any]] = [
        _record("user", promptId="p1", message={"role": "user", "content": prompt}),
        _record("attachment", attachment={"type": "skill_listing"}),
        _record("user", isMeta=True, message={"role": "user", "content": "[SYSTEM NOTIFICATION]"}),
        {
            "type": "api-request-blob",
            "agentId": AGENT,
            "message": {"role": "assistant", "model": "claude-haiku-4-5", "content": []},
        },
    ]
    for model in models:
        records.append(
            _assistant([{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}], model)
        )
        records.append(
            _record(
                "user",
                message={
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}],
                },
            )
        )
    records.extend(extra)
    records.append(_assistant([{"type": "text", "text": reply}], models[-1]))
    return records


def _write_transcript(path: Path, records: list[dict[str, Any]], tail: str = "") -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in records) + tail, encoding="utf-8")
    return path


def _facts(tmp_path: Path, prompt: str, reply: str, **kwargs: Any) -> TranscriptFacts:
    path = _write_transcript(tmp_path / "agent.jsonl", _transcript_records(prompt, reply, **kwargs))
    return read_review_transcript(path)


def _stop(reply: str, **overrides: Any) -> ReviewStop:
    stop = ReviewStop(
        session_id=SESSION,
        agent_id=AGENT,
        agent_type=REVIEWER_AGENT_TYPE,
        meta_agent_type=REVIEWER_AGENT_TYPE,
        meta_tool_use_id=TOOL_USE,
        stop_hook_active=False,
        reply=reply,
    )
    return replace(stop, **overrides)


def _verdict_files(store: RejectStore) -> list[Path]:
    return sorted((store.root / "verdicts").glob("*.json"))


def _keep_files(store: RejectStore) -> list[Path]:
    return sorted((store.root / "keeps").glob("*.json"))


# --- parsing the reply -----------------------------------------------------------------


class TestParseVerdictReply:
    def test_a_canonical_reply_parses(self, store: RejectStore) -> None:
        request, _ = _request(store)
        items, overall = parse_verdict_reply(_reply(request), request)
        assert overall == DECISION_NO_VALUE
        assert [(i.kind, i.ref, i.decision) for i in items] == [
            (KIND_COMMIT, SHA_A, DECISION_NO_VALUE),
            (KIND_PATH, "src/feature.py", DECISION_NO_VALUE),
        ]
        assert all(i.reason for i in items)

    def test_citations_are_parsed_bracketed_or_not(self, store: RejectStore) -> None:
        request, _ = _request(store)
        reply = _reply(request).replace(
            f"commit {SHA_A} no-value: scratch work",
            f"commit {SHA_A} no-value: redone [superseded-by: commit:{SHA_B} path:docs/a.md]",
        )
        reply = reply.replace(
            "path src/feature.py no-value: scratch file",
            "path src/feature.py no-value: moved superseded-by: path:src/new.py",
        )
        items, _ = parse_verdict_reply(reply, request)
        assert items[0].reason == "redone"
        assert items[0].superseded_by == (f"commit:{SHA_B}", "path:docs/a.md")
        assert items[1].reason == "moved"
        assert items[1].superseded_by == ("path:src/new.py",)

    def test_a_path_with_spaces_and_colons_matches_the_inventory(self, store: RejectStore) -> None:
        request, _ = _request(store, paths=("docs/a b: c.md",))
        items, _ = parse_verdict_reply(_reply(request), request)
        assert items[1].ref == "docs/a b: c.md"

    def test_any_keep_item_makes_the_overall_keep(self, store: RejectStore) -> None:
        request, _ = _request(store)
        reply = _reply(request).replace("path src/feature.py no-value", "path src/feature.py keep")
        _, overall = parse_verdict_reply(reply, request)
        assert overall == DECISION_KEEP

    def test_an_overall_keep_is_keep(self, store: RejectStore) -> None:
        request, _ = _request(store)
        _, overall = parse_verdict_reply(_reply(request, overall=DECISION_KEEP), request)
        assert overall == DECISION_KEEP

    def test_trailing_whitespace_after_the_block_is_allowed(self, store: RejectStore) -> None:
        request, _ = _request(store)
        assert parse_verdict_reply(_reply(request, suffix="\n  \n"), request)

    @pytest.mark.parametrize(
        "mutate",
        [
            pytest.param(lambda r, q: r + "\nthanks", id="text-after-the-block"),
            pytest.param(lambda r, q: r + "\n" + r, id="two-blocks"),
            pytest.param(lambda r, q: r.replace(VERDICT_BLOCK_END, "END"), id="no-end"),
            pytest.param(
                lambda r, q: r.replace(f"nonce={q.nonce}", f"nonce={'f' * 32}"), id="other-nonce"
            ),
            pytest.param(lambda r, q: r.replace(f"tip={q.tip}", f"tip={'9' * 40}"), id="other-tip"),
            pytest.param(
                lambda r, q: r.replace(f"commit {SHA_A}", f"commit {SHA_B}"), id="unknown-commit"
            ),
            pytest.param(
                lambda r, q: r.replace("path src/feature.py", "path src/other.py"),
                id="unknown-path",
            ),
            pytest.param(lambda r, q: r.replace("no-value: scratch work", "maybe: x"), id="bad-word"),
            pytest.param(
                lambda r, q: r.replace("overall no-value\n", "overall no-value\nextra line\n"),
                id="line-after-overall",
            ),
            pytest.param(lambda r, q: r.replace("overall no-value\n", ""), id="no-overall"),
            pytest.param(lambda r, q: r.replace("overall no-value", "overall maybe"), id="bad-all"),
            pytest.param(
                lambda r, q: r.replace(
                    "scratch work", f"x [superseded-by: sha:{SHA_B}]"
                ),
                id="bad-citation",
            ),
            pytest.param(
                lambda r, q: r.replace(f"{VERDICT_BLOCK_START} ", f"  {VERDICT_BLOCK_START} "),
                id="indented-start",
            ),
            pytest.param(
                lambda r, q: r.replace("overall", "\noverall"), id="blank-line-in-the-block"
            ),
        ],
    )
    def test_a_malformed_reply_is_refused(self, store: RejectStore, mutate: Any) -> None:
        request, _ = _request(store)
        with pytest.raises(RejectRefusedError):
            parse_verdict_reply(mutate(_reply(request), request), request)


# --- reading the transcript ------------------------------------------------------------


class TestReadReviewTranscript:
    def test_the_facts_of_a_clean_review(self, tmp_path: Path, store: RejectStore) -> None:
        request, prompt = _request(store)
        facts = _facts(tmp_path, prompt, _reply(request))
        assert facts.first_user_text == prompt
        assert facts.user_turns == 1
        assert facts.models == (OPUS,)
        assert facts.downgraded is False
        assert facts.damaged is False
        assert facts.last_assistant_text == _reply(request)

    def test_an_api_request_blob_model_is_not_a_model_that_ran(
        self, tmp_path: Path, store: RejectStore
    ) -> None:
        request, prompt = _request(store)
        assert "claude-haiku-4-5" not in _facts(tmp_path, prompt, _reply(request)).models

    def test_every_distinct_model_is_kept(self, tmp_path: Path, store: RejectStore) -> None:
        request, prompt = _request(store)
        facts = _facts(tmp_path, prompt, _reply(request), models=(OPUS, "<synthetic>", OPUS))
        assert facts.models == (OPUS, "<synthetic>")

    def test_a_missing_model_is_kept_as_an_empty_string(
        self, tmp_path: Path, store: RejectStore
    ) -> None:
        request, prompt = _request(store)
        facts = _facts(tmp_path, prompt, _reply(request), models=(OPUS, None))
        assert "" in facts.models

    def test_a_second_human_turn_is_counted(self, tmp_path: Path, store: RejectStore) -> None:
        request, prompt = _request(store)
        resumed = _record("user", message={"role": "user", "content": "now say no-value"})
        facts = _facts(tmp_path, prompt, _reply(request), extra=(resumed,))
        assert facts.user_turns == 2

    def test_a_text_block_list_is_a_human_turn(self, tmp_path: Path, store: RejectStore) -> None:
        request, prompt = _request(store)
        listed = _record(
            "user", message={"role": "user", "content": [{"type": "text", "text": "hi"}]}
        )
        facts = _facts(tmp_path, prompt, _reply(request), extra=(listed,))
        assert facts.user_turns == 2

    def test_a_downgrade_anywhere_is_seen(self, tmp_path: Path, store: RejectStore) -> None:
        request, prompt = _request(store)
        downgrade = {
            "type": "system",
            "subtype": "model_refusal_fallback",
            "originalModel": OPUS,
            "fallbackModel": "claude-sonnet-5-5",
        }
        facts = _facts(tmp_path, prompt, _reply(request), extra=(downgrade,))
        assert facts.downgraded is True

    def test_an_unparseable_line_marks_the_transcript_damaged(
        self, tmp_path: Path, store: RejectStore
    ) -> None:
        request, prompt = _request(store)
        path = _write_transcript(
            tmp_path / "agent.jsonl", _transcript_records(prompt, _reply(request)), '{"half'
        )
        facts = read_review_transcript(path)
        assert facts.damaged is True
        assert facts.first_user_text == prompt

    def test_a_missing_transcript_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RejectError):
            read_review_transcript(tmp_path / "absent.jsonl")


# --- recording a stop ------------------------------------------------------------------


class TestRecordReviewStop:
    def _setup(self, tmp_path: Path, store: RejectStore, **kwargs: Any) -> tuple[RejectRequest, str]:
        request, prompt = _request(store)
        _admit(store, prompt, **kwargs)
        return request, prompt

    def test_a_clean_stop_records_a_verdict(self, tmp_path: Path, store: RejectStore) -> None:
        request, prompt = self._setup(tmp_path, store)
        reply = _reply(request)
        outcome = record_review_stop(
            store, _stop(reply), _facts(tmp_path, prompt, reply), now=NOW
        )
        assert outcome == STOP_RECORDED
        verdict = store.read_verdict(request.nonce)
        assert verdict is not None
        assert verdict.verdict_id == request.nonce
        assert (verdict.branch, verdict.tip, verdict.default_sha) == (
            request.branch,
            request.tip,
            request.default_sha,
        )
        assert verdict.inventory == request.inventory
        assert verdict.issued_at == NOW
        assert verdict.overall == DECISION_NO_VALUE
        reviewer = verdict.reviewer
        assert (reviewer.session_id, reviewer.agent_id) == (SESSION, AGENT)
        assert reviewer.models == (OPUS,)
        assert (reviewer.downgraded, reviewer.fork, reviewer.user_turns) == (False, False, 1)
        assert reviewer.reply_sha256 == hashlib.sha256(reply.encode("utf-8")).hexdigest()
        assert _keep_files(store) == []

    def test_the_recorder_never_writes_the_agent_id(
        self, tmp_path: Path, store: RejectStore
    ) -> None:
        """Foreground order: SubagentStop before PostToolUse leaves the record unbound."""
        request, prompt = self._setup(tmp_path, store, bind=False)
        reply = _reply(request)
        assert (
            record_review_stop(store, _stop(reply), _facts(tmp_path, prompt, reply), now=NOW)
            == STOP_RECORDED
        )
        dispatch = store.read_dispatch(request.nonce)
        assert dispatch is not None and dispatch.agent_id == ""

    def test_a_keep_writes_a_keep_record(self, tmp_path: Path, store: RejectStore) -> None:
        request, prompt = self._setup(tmp_path, store)
        reply = _reply(request).replace(
            "path src/feature.py no-value: scratch file",
            "path src/feature.py keep: the only copy of the parser",
        )
        record_review_stop(store, _stop(reply), _facts(tmp_path, prompt, reply), now=NOW)
        verdict = store.read_verdict(request.nonce)
        assert verdict is not None and verdict.overall == DECISION_KEEP
        keeps = store.keeps()
        assert len(keeps) == 1
        assert keeps[0].verdict_id == request.nonce
        assert (keeps[0].branch, keeps[0].tip) == (request.branch, request.tip)
        assert keeps[0].commits == request.inventory.commits
        assert keeps[0].reasons == ("the only copy of the parser",)
        assert keeps[0].recorded_at == NOW

    def test_a_second_stop_withdraws_the_verdict(self, tmp_path: Path, store: RejectStore) -> None:
        request, prompt = self._setup(tmp_path, store)
        reply = _reply(request)
        facts = _facts(tmp_path, prompt, reply)
        assert record_review_stop(store, _stop(reply), facts, now=NOW) == STOP_RECORDED
        assert record_review_stop(store, _stop(reply), facts, now=NOW) == STOP_WITHDRAWN
        assert _verdict_files(store) == []
        assert record_review_stop(store, _stop(reply), facts, now=NOW) == STOP_WITHDRAWN
        assert _verdict_files(store) == []

    def test_a_stop_hook_active_stop_records_nothing(
        self, tmp_path: Path, store: RejectStore
    ) -> None:
        request, prompt = self._setup(tmp_path, store)
        reply = _reply(request)
        outcome = record_review_stop(
            store, _stop(reply, stop_hook_active=True), _facts(tmp_path, prompt, reply), now=NOW
        )
        assert outcome == STOP_WITHDRAWN
        assert _verdict_files(store) == []

    def test_withdrawal_leaves_other_nonces_and_keeps(
        self, tmp_path: Path, store: RejectStore
    ) -> None:
        other, other_prompt = _request(store)
        other_reply = _reply(other)
        _admit(store, other_prompt)
        record_review_stop(
            store,
            _stop(other_reply),
            _facts(tmp_path, other_prompt, other_reply),
            now=NOW,
        )
        request, prompt = _request(store)
        reply = _reply(request, decision=DECISION_KEEP)
        admit_dispatch(
            DispatchCall(SESSION, "toolu_2", REVIEWER_AGENT_TYPE, prompt, "opus", False, True),
            store,
        )
        facts = _facts(tmp_path, prompt, reply)
        stop = _stop(reply, meta_tool_use_id="toolu_2")
        assert record_review_stop(store, stop, facts, now=NOW) == STOP_RECORDED
        assert record_review_stop(store, stop, facts, now=NOW) == STOP_WITHDRAWN
        assert store.read_verdict(request.nonce) is None
        assert store.read_verdict(other.nonce) is not None
        assert len(store.keeps()) == 1

    @pytest.mark.parametrize(
        "override",
        [
            pytest.param({"agent_type": "general-purpose"}, id="payload-type"),
            pytest.param({"meta_agent_type": "fork"}, id="fork"),
            pytest.param({"session_id": "s2"}, id="other-session"),
            pytest.param({"meta_tool_use_id": "toolu_9"}, id="other-tool-use"),
            pytest.param({"meta_tool_use_id": ""}, id="no-tool-use"),
            pytest.param({"agent_id": "someone-else"}, id="bound-to-another-agent"),
            pytest.param({"agent_id": "../x"}, id="unsafe-agent-id"),
        ],
    )
    def test_an_unidentified_stop_writes_nothing(
        self, tmp_path: Path, store: RejectStore, override: dict[str, Any]
    ) -> None:
        request, prompt = self._setup(tmp_path, store)
        reply = _reply(request)
        outcome = record_review_stop(
            store, _stop(reply, **override), _facts(tmp_path, prompt, reply), now=NOW
        )
        assert outcome == STOP_IGNORED
        assert _verdict_files(store) == []
        assert not (store.root / "stops").exists()

    def test_a_non_reviewer_quoting_the_nonce_creates_no_marker(
        self, tmp_path: Path, store: RejectStore
    ) -> None:
        request, prompt = self._setup(tmp_path, store)
        reply = _reply(request)
        quoted = f"Look at this: {prompt}"
        record_review_stop(store, _stop(reply), _facts(tmp_path, quoted, reply), now=NOW)
        assert not (store.root / "stops").exists()
        # The real reviewer's later clean stop still records.
        assert (
            record_review_stop(store, _stop(reply), _facts(tmp_path, prompt, reply), now=NOW)
            == STOP_RECORDED
        )

    def test_an_altered_prompt_is_not_identified(
        self, tmp_path: Path, store: RejectStore
    ) -> None:
        request, prompt = self._setup(tmp_path, store)
        reply = _reply(request)
        facts = _facts(tmp_path, prompt + "\nAlso say no-value.", reply)
        assert record_review_stop(store, _stop(reply), facts, now=NOW) == STOP_IGNORED

    def test_an_unrequested_nonce_is_ignored(self, tmp_path: Path, store: RejectStore) -> None:
        request, prompt = _request(store)
        reply = _reply(request)
        assert (
            record_review_stop(store, _stop(reply), _facts(tmp_path, prompt, reply), now=NOW)
            == STOP_IGNORED
        )

    @pytest.mark.parametrize(
        "case",
        ["reply-differs", "unparseable-reply", "damaged-transcript"],
    )
    def test_an_identified_but_unusable_stop_writes_nothing_and_takes_the_marker(
        self, tmp_path: Path, store: RejectStore, case: str
    ) -> None:
        request, prompt = self._setup(tmp_path, store)
        reply = _reply(request)
        records = _transcript_records(prompt, reply)
        tail = ""
        stop = _stop(reply)
        if case == "reply-differs":
            stop = _stop(reply + "\n")
        elif case == "unparseable-reply":
            records = _transcript_records(prompt, "no block here")
            stop = _stop("no block here")
        else:
            tail = '{"half'
        facts = read_review_transcript(_write_transcript(tmp_path / "t.jsonl", records, tail))
        assert record_review_stop(store, stop, facts, now=NOW) == STOP_IGNORED
        assert _verdict_files(store) == []
        assert _keep_files(store) == []
        # The stop counted: a later clean-looking stop of the same nonce withdraws.
        clean = _facts(tmp_path, prompt, reply)
        assert record_review_stop(store, _stop(reply), clean, now=NOW) == STOP_WITHDRAWN
        assert _verdict_files(store) == []

    def test_the_recorder_never_touches_the_ledger_or_requests(
        self, tmp_path: Path, store: RejectStore
    ) -> None:
        request, prompt = self._setup(tmp_path, store)
        reply = _reply(request)
        before = sorted(p.name for p in (store.root / "requests").iterdir())
        record_review_stop(store, _stop(reply), _facts(tmp_path, prompt, reply), now=NOW)
        record_review_stop(store, _stop(reply), _facts(tmp_path, prompt, reply), now=NOW)
        assert sorted(p.name for p in (store.root / "requests").iterdir()) == before
        assert sorted(p.name for p in store.root.iterdir()) == [
            "dispatches",
            "requests",
            "stops",
            "verdicts",
        ]


# --- end to end on a real repository ----------------------------------------------------

_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "PATH": "/usr/bin:/bin",
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**_ENV, "HOME": str(repo)},
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "switch", "-q", "-c", "feat")
    (root / "src").mkdir()
    (root / "src" / "feature.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", "src/feature.py")
    _git(root, "commit", "-q", "-m", "add feature")
    _git(root, "switch", "-q", "main")
    _git(root, "config", "branch.feat.hooksDaemonCreator", "s0:creator")
    return root


class TestEndToEnd:
    @pytest.mark.parametrize("bind_first", [True, False], ids=["bind-then-stop", "stop-then-bind"])
    def test_a_recorded_verdict_validates(
        self, tmp_path: Path, repo: Path, bind_first: bool
    ) -> None:
        config = BranchRejectConfig()
        store = RejectStore(repo / config.state_dir)
        inventory = compute_inventory(repo, "feat", "main")
        request, prompt = _request(
            store,
            commits=inventory.commits,
            paths=inventory.paths,
            tip=_git(repo, "rev-parse", "refs/heads/feat").strip(),
            default_sha=_git(repo, "rev-parse", "refs/heads/main").strip(),
        )
        _admit(store, prompt, bind=bind_first)
        reply = _reply(request)
        facts = _facts(tmp_path, prompt, reply)
        assert record_review_stop(store, _stop(reply), facts, now=NOW) == STOP_RECORDED
        if not bind_first:
            assert bind_agent(
                store, request.nonce, session_id=SESSION, tool_use_id=TOOL_USE, agent_id=AGENT
            )
        verdict = store.read_verdict(request.nonce)
        assert verdict is not None
        assert (
            verdict_problems(
                verdict,
                repo=repo,
                store=store,
                default_ref="main",
                now=NOW + 60,
                consumed=frozenset(),
                config=config,
            )
            == []
        )
