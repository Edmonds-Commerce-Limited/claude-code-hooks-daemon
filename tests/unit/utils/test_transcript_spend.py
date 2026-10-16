"""Tests for the offset-cached cumulative spend reader (Plan 00471 Task 2.0)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.utils.transcript_spend import (
    SpendTotals,
    TranscriptSpendCache,
    plan_key_from,
)


def assistant(
    request_id: str,
    ctx_read: int,
    *,
    output: int = 10,
    model: str = "claude-opus-5-5",
    requested: str = "opus",
    branch: str = "worktree-p471-spend",
) -> str:
    record: dict[str, Any] = {
        "type": "assistant",
        "requestId": request_id,
        "requestedModel": requested,
        "gitBranch": branch,
        "message": {
            "model": model,
            "id": f"msg_{request_id}",
            "usage": {
                "input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": ctx_read,
                "output_tokens": output,
            },
        },
    }
    return json.dumps(record)


def teammate_message() -> str:
    return json.dumps(
        {
            "type": "user",
            "message": {"role": "user", "content": '<teammate-message teammate_id="lead">x'},
        }
    )


def compaction(pre: int) -> str:
    return json.dumps(
        {"type": "system", "subtype": "compact_boundary", "compactMetadata": {"preTokens": pre}}
    )


def write(path: Path, lines: list[str], *, mode: str = "w") -> None:
    with path.open(mode, encoding="utf-8") as handle:
        handle.write("".join(line + "\n" for line in lines))


@pytest.fixture
def transcript(tmp_path: Path) -> Path:
    return tmp_path / "agent-ax.jsonl"


class TestTotals:
    def test_counts_per_request_not_per_record(self, transcript: Path, tmp_path: Path) -> None:
        """Content-block records of one request count once, with the final output."""
        write(
            transcript,
            [
                assistant("r1", 1000, output=2),
                assistant("r1", 1000, output=50),
                assistant("r2", 3000, output=20),
            ],
        )
        totals = TranscriptSpendCache(tmp_path / "store").totals(transcript)
        assert totals.requests == 2
        assert totals.output_tokens == 70
        assert totals.cache_read_tokens == 4000
        assert totals.max_ctx == 3000
        assert totals.last_ctx == 3000
        assert totals.mean_ctx == 2000
        assert totals.ite == pytest.approx(400 + 350)

    def test_repeated_request_ids_across_generations_count_once(
        self, transcript: Path, tmp_path: Path
    ) -> None:
        write(transcript, [assistant("r1", 100), assistant("r2", 200), assistant("r1", 100)])
        assert TranscriptSpendCache(tmp_path / "s").totals(transcript).requests == 2

    def test_compactions_inbound_models_and_plan_key(
        self, transcript: Path, tmp_path: Path
    ) -> None:
        write(
            transcript,
            [
                teammate_message(),
                assistant("r1", 100),
                compaction(567_000),
                teammate_message(),
                assistant("r2", 100, model="claude-sonnet-5", requested="sonnet"),
                json.dumps({"type": "assistant", "message": {"model": "<synthetic>", "usage": {}}}),
            ],
        )
        totals = TranscriptSpendCache(tmp_path / "s").totals(transcript)
        assert totals.compactions == 1
        assert totals.compact_pre_tokens == [567_000]
        assert totals.inbound_messages == 2
        assert totals.per_model_requests == {"claude-opus-5-5": 1, "claude-sonnet-5": 1}
        assert totals.model_param == "opus"
        assert totals.resolved_model == "claude-sonnet-5"
        assert totals.plan_key == "471"
        assert totals.requests == 2


class TestOffsetCache:
    def test_append_parses_only_new_bytes(self, transcript: Path, tmp_path: Path) -> None:
        cache = TranscriptSpendCache(tmp_path / "s")
        write(transcript, [assistant("r1", 100)])
        assert cache.totals(transcript).requests == 1
        offset_after_first = cache.offset_of(transcript)
        write(transcript, [assistant("r2", 200)], mode="a")
        assert cache.totals(transcript).requests == 2
        assert cache.offset_of(transcript) > offset_after_first

    def test_partial_trailing_line_waits_for_its_newline(
        self, transcript: Path, tmp_path: Path
    ) -> None:
        cache = TranscriptSpendCache(tmp_path / "s")
        line = assistant("r1", 100)
        transcript.write_text(line[:20], encoding="utf-8")
        assert cache.totals(transcript).requests == 0
        transcript.write_text(line + "\n", encoding="utf-8")
        assert cache.totals(transcript).requests == 1

    def test_content_blocks_split_across_appends_still_count_once(
        self, transcript: Path, tmp_path: Path
    ) -> None:
        cache = TranscriptSpendCache(tmp_path / "s")
        write(transcript, [assistant("r1", 100, output=2)])
        cache.totals(transcript)
        write(transcript, [assistant("r1", 100, output=40)], mode="a")
        totals = cache.totals(transcript)
        assert totals.requests == 1
        assert totals.output_tokens == 40

    def test_truncate_resets(self, transcript: Path, tmp_path: Path) -> None:
        cache = TranscriptSpendCache(tmp_path / "s")
        write(transcript, [assistant("r1", 100), assistant("r2", 100), assistant("r3", 100)])
        assert cache.totals(transcript).requests == 3
        write(transcript, [assistant("r9", 100)])
        assert cache.totals(transcript).requests == 1

    def test_inode_replacement_resets(self, transcript: Path, tmp_path: Path) -> None:
        cache = TranscriptSpendCache(tmp_path / "s")
        write(transcript, [assistant("r1", 100)])
        assert cache.totals(transcript).requests == 1
        replacement = tmp_path / "new.jsonl"
        write(replacement, [assistant("r8", 500), assistant("r9", 500)])
        replacement.replace(transcript)
        totals = cache.totals(transcript)
        assert totals.requests == 2
        assert totals.max_ctx == 500

    def test_same_totals_as_a_fresh_full_scan(self, transcript: Path, tmp_path: Path) -> None:
        cache = TranscriptSpendCache(tmp_path / "s")
        lines = [assistant(f"r{i}", 100 * i, output=i) for i in range(1, 30)]
        for line in lines:
            write(transcript, [line], mode="a")
            cache.totals(transcript)
        incremental = cache.totals(transcript)
        fresh = TranscriptSpendCache(tmp_path / "fresh").totals(transcript)
        assert incremental == fresh

    def test_persists_across_instances(self, transcript: Path, tmp_path: Path) -> None:
        store = tmp_path / "s"
        write(transcript, [assistant("r1", 100)])
        first = TranscriptSpendCache(store)
        first.totals(transcript)
        second = TranscriptSpendCache(store)
        assert second.offset_of(transcript) == first.offset_of(transcript)
        write(transcript, [assistant("r1", 100)], mode="a")
        assert second.totals(transcript).requests == 1

    def test_corrupt_store_is_rebuilt(self, transcript: Path, tmp_path: Path) -> None:
        store = tmp_path / "s"
        write(transcript, [assistant("r1", 100)])
        TranscriptSpendCache(store).totals(transcript)
        for entry in store.iterdir():
            entry.write_text("{not json", encoding="utf-8")
        assert TranscriptSpendCache(store).totals(transcript).requests == 1

    def test_store_of_another_transcript_is_rebuilt_and_logged(
        self, transcript: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        store = tmp_path / "s"
        write(transcript, [assistant("r1", 100)])
        TranscriptSpendCache(store).totals(transcript)
        for entry in store.iterdir():
            data = json.loads(entry.read_text(encoding="utf-8"))
            data["path"] = "/elsewhere/agent-x.jsonl"
            entry.write_text(json.dumps(data), encoding="utf-8")
        with caplog.at_level(logging.DEBUG):
            assert TranscriptSpendCache(store).totals(transcript).requests == 1
        assert "offset sidecar" in caplog.text

    def test_non_json_line_is_skipped_and_logged(
        self, transcript: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        transcript.write_text("plain text output\n" + assistant("r1", 100) + "\n", encoding="utf-8")
        with caplog.at_level(logging.DEBUG):
            assert TranscriptSpendCache(None).totals(transcript).requests == 1
        assert "not a transcript record" in caplog.text

    def test_evict_drops_the_entry_and_the_sidecar_restores_it(
        self, transcript: Path, tmp_path: Path
    ) -> None:
        """Review S6: a stopped agent's request ids do not stay resident for the daemon's life."""
        store = tmp_path / "s"
        write(transcript, [assistant("r1", 100)])
        cache = TranscriptSpendCache(store)
        cache.totals(transcript)
        cache.evict(transcript)
        assert cache.resident() == 0
        write(transcript, [assistant("r1", 100), assistant("r2", 100)], mode="a")
        assert cache.totals(transcript).requests == 2

    def test_no_store_works_in_memory(self, transcript: Path) -> None:
        write(transcript, [assistant("r1", 100)])
        assert TranscriptSpendCache(None).totals(transcript).requests == 1

    def test_missing_transcript_raises(self, tmp_path: Path) -> None:
        with pytest.raises(OSError):
            TranscriptSpendCache(None).totals(tmp_path / "absent.jsonl")


class TestSpendTotals:
    def test_round_trip(self) -> None:
        totals = SpendTotals(requests=3, per_model_requests={"m": 3}, compact_pre_tokens=[5])
        assert SpendTotals.from_dict(totals.to_dict()) == totals

    def test_from_dict_ignores_junk(self) -> None:
        totals = SpendTotals.from_dict({"requests": "x", "per_model_requests": [1], "bogus": 1})
        assert totals == SpendTotals()

    def test_mean_of_nothing_is_zero(self) -> None:
        assert SpendTotals().mean_ctx == 0


@pytest.mark.parametrize(
    ("candidates", "expected"),
    [
        (("worktree-p471-spend-levers",), "471"),
        (("main", "/workspace", "plan464-impl"), "464"),
        (("worktree-00518-x",), "518"),
        (("CLAUDE/Plan/00472-subagent-model-tier-selection",), "472"),
        (("main", "/workspace", "qa-runner"), ""),
        (("feature-v3",), ""),
        (("/tmp/pytest-of-root/pytest-6185/x",), ""),
        (("main", "/workspace", "n464-reap-timeout"), "464"),
    ],
)
def test_plan_key_from(candidates: tuple[str, ...], expected: str) -> None:
    assert plan_key_from(*candidates) == expected
