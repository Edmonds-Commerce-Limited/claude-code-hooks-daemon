"""Unit tests for ModelFallbackDetectorHandler (Plan 00278 Phase 3/3b).

The handler scans the session transcript JSONL for platform-written
``model_refusal_fallback`` records (and assistant-message ``fallback``
content blocks as corroboration), injects a loud PROTECTION-DEGRADED-style
advisory, and writes a redacted diagnostic snapshot of the fallback record
plus a bounded window of preceding transcript records.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.session_start.model_fallback_detector import (
    ModelFallbackDetectorHandler,
)

_SESSION_START = "SessionStart"


def _fallback_record(
    timestamp: str = "2026-08-27T06:51:11Z",
    original: str = "claude-fable-5",
    fallback: str = "claude-opus-4-8",
    category: str = "cyber",
) -> dict[str, Any]:
    return {
        "type": "system",
        "subtype": "model_refusal_fallback",
        "level": "warning",
        "trigger": "refusal",
        "direction": "retry",
        "scope": "session",
        "timestamp": timestamp,
        "originalModel": original,
        "fallbackModel": fallback,
        "apiRefusalCategory": category,
        "content": "Safeguards flagged this message.",
    }


def _corroboration_record() -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "model": "claude-opus-4-8",
            "content": [
                {
                    "type": "fallback",
                    "from": {"model": "claude-fable-5"},
                    "to": {"model": "claude-opus-4-8"},
                }
            ],
        },
    }


def _prose_record(text: str = "hello") -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def _write_transcript(path: Path, records: list[Any]) -> None:
    lines = []
    for record in records:
        lines.append(record if isinstance(record, str) else json.dumps(record))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _hook_input(transcript: Path, session_id: str = "session-1") -> dict[str, Any]:
    return {
        "hook_event_name": _SESSION_START,
        "session_id": session_id,
        "transcript_path": str(transcript),
    }


@pytest.fixture
def handler(tmp_path: Path) -> ModelFallbackDetectorHandler:
    instance = ModelFallbackDetectorHandler()
    instance._snapshot_dir = str(tmp_path / "reports")
    return instance


class TestInitialisation:
    def test_identity(self) -> None:
        instance = ModelFallbackDetectorHandler()
        assert instance.name == HandlerID.MODEL_FALLBACK_DETECTOR.display_name
        assert instance.priority == Priority.MODEL_FALLBACK_DETECTOR
        assert instance.terminal is False

    def test_default_enabled(self) -> None:
        assert ModelFallbackDetectorHandler().get_default_enabled() is True


class TestMatches:
    def test_matches_session_start_with_transcript(
        self, handler: ModelFallbackDetectorHandler, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [_prose_record()])
        assert handler.matches(_hook_input(transcript)) is True

    def test_no_match_without_transcript_path(self, handler: ModelFallbackDetectorHandler) -> None:
        assert handler.matches({"hook_event_name": _SESSION_START, "session_id": "s"}) is False

    def test_no_match_wrong_event(
        self, handler: ModelFallbackDetectorHandler, tmp_path: Path
    ) -> None:
        payload = _hook_input(tmp_path / "t.jsonl")
        payload["hook_event_name"] = "Stop"
        assert handler.matches(payload) is False

    def test_no_match_non_dict(self, handler: ModelFallbackDetectorHandler) -> None:
        payload: Any = None
        assert handler.matches(payload) is False


class TestDetection:
    def test_clean_transcript_is_silent(
        self, handler: ModelFallbackDetectorHandler, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [_prose_record(), _prose_record("more")])
        result = handler.handle(_hook_input(transcript))
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_fallback_record_triggers_loud_advisory(
        self, handler: ModelFallbackDetectorHandler, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [_prose_record(), _fallback_record()])
        result = handler.handle(_hook_input(transcript))
        text = "\n".join(result.context)
        assert "MODEL FALLBACK DETECTED" in text
        assert "claude-fable-5" in text
        assert "claude-opus-4-8" in text
        assert "cyber" in text
        assert "restart" in text.lower()
        assert "scope" in text.lower()

    def test_corroboration_only_record_is_detected(
        self, handler: ModelFallbackDetectorHandler, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [_prose_record(), _corroboration_record()])
        result = handler.handle(_hook_input(transcript))
        text = "\n".join(result.context)
        assert "MODEL FALLBACK DETECTED" in text
        assert "claude-fable-5" in text

    def test_missing_transcript_is_silent(
        self, handler: ModelFallbackDetectorHandler, tmp_path: Path
    ) -> None:
        result = handler.handle(_hook_input(tmp_path / "absent.jsonl"))
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_malformed_lines_are_skipped_fail_silent(
        self, handler: ModelFallbackDetectorHandler, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        _write_transcript(
            transcript,
            ["{not json", "[]", _fallback_record(), "another bad line"],
        )
        result = handler.handle(_hook_input(transcript))
        assert "MODEL FALLBACK DETECTED" in "\n".join(result.context)


class TestOncePerSessionPerRecord:
    def test_same_session_does_not_repeat(
        self, handler: ModelFallbackDetectorHandler, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [_fallback_record()])
        first = handler.handle(_hook_input(transcript))
        second = handler.handle(_hook_input(transcript))
        assert first.context
        assert second.context == []

    def test_new_distinct_record_fires_again(
        self, handler: ModelFallbackDetectorHandler, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [_fallback_record(timestamp="2026-08-27T01:02:27Z")])
        handler.handle(_hook_input(transcript))
        _write_transcript(
            transcript,
            [
                _fallback_record(timestamp="2026-08-27T01:02:27Z"),
                _fallback_record(timestamp="2026-08-27T06:42:07Z"),
            ],
        )
        result = handler.handle(_hook_input(transcript))
        assert "MODEL FALLBACK DETECTED" in "\n".join(result.context)

    def test_different_session_fires_again(
        self, handler: ModelFallbackDetectorHandler, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [_fallback_record()])
        handler.handle(_hook_input(transcript, session_id="a"))
        result = handler.handle(_hook_input(transcript, session_id="b"))
        assert result.context


class TestSnapshot:
    def test_snapshot_written_with_record_and_window(
        self, handler: ModelFallbackDetectorHandler, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        _write_transcript(
            transcript,
            [_prose_record("alpha"), _prose_record("beta"), _fallback_record()],
        )
        handler.handle(_hook_input(transcript))
        snapshots = list((tmp_path / "reports").glob("*.md"))
        assert len(snapshots) == 1
        body = snapshots[0].read_text(encoding="utf-8")
        assert "model_refusal_fallback" in body
        assert "alpha" in body
        assert "beta" in body

    def test_snapshot_window_is_bounded(
        self, handler: ModelFallbackDetectorHandler, tmp_path: Path
    ) -> None:
        handler._snapshot_window_records = 2
        transcript = tmp_path / "t.jsonl"
        _write_transcript(
            transcript,
            [
                _prose_record("first-record"),
                _prose_record("second-record"),
                _prose_record("third-record"),
                _fallback_record(),
            ],
        )
        handler.handle(_hook_input(transcript))
        body = next((tmp_path / "reports").glob("*.md")).read_text(encoding="utf-8")
        assert "first-record" not in body
        assert "second-record" in body
        assert "third-record" in body

    def test_snapshot_disabled_still_advises(
        self, handler: ModelFallbackDetectorHandler, tmp_path: Path
    ) -> None:
        handler._snapshot_enabled = False
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [_fallback_record()])
        result = handler.handle(_hook_input(transcript))
        assert result.context
        assert not (tmp_path / "reports").exists()

    def test_snapshot_is_redacted(
        self,
        handler: ModelFallbackDetectorHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.session_start.model_fallback_detector."
            "get_active_secret_terms",
            lambda: ("hunter2",),
        )
        transcript = tmp_path / "t.jsonl"
        _write_transcript(
            transcript, [_prose_record("the password is hunter2"), _fallback_record()]
        )
        handler.handle(_hook_input(transcript))
        body = next((tmp_path / "reports").glob("*.md")).read_text(encoding="utf-8")
        assert "hunter2" not in body
        assert "[REDACTED]" in body

    def test_snapshot_failure_degrades_to_advisory_mention(
        self, handler: ModelFallbackDetectorHandler, tmp_path: Path
    ) -> None:
        blocker = tmp_path / "reports"
        blocker.write_text("a file where the dir should be", encoding="utf-8")
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [_fallback_record()])
        result = handler.handle(_hook_input(transcript))
        text = "\n".join(result.context)
        assert "MODEL FALLBACK DETECTED" in text
        assert "snapshot" in text.lower()


class TestGuidanceSurfaces:
    def test_get_claude_md(self) -> None:
        guidance = ModelFallbackDetectorHandler().get_claude_md()
        assert guidance is not None
        assert "model_fallback_detector" in guidance

    def test_get_acceptance_tests(self) -> None:
        tests = ModelFallbackDetectorHandler().get_acceptance_tests()
        assert tests
        for test in tests:
            assert test.title
            assert test.expected_decision == Decision.ALLOW
