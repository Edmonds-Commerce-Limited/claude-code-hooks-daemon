"""Unit tests for the ModelDowngradeRecorderHandler (Plan 00328 Task 2.2).

RED-first TDD file. The handler reads the transcript tail on each PostToolUse,
recognises Claude Code's automatic model-downgrade record, and publishes it as
a per-session signal file the ccy supervisor reads. It never blocks and never
speaks — the whole point is a silent, positively-attributed fact that lets the
supervisor arm its model auto-restore without guessing at human intent.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.post_tool_use.model_downgrade_recorder import (
    _SIGNAL_SUBDIR,
    _SIGNAL_SUFFIX,
    ModelDowngradeRecorderHandler,
)

_SESSION = "sess-abc-123"


def _subtype_line(
    *,
    original: str = "claude-fable-5",
    fallback: str = "claude-opus-4-8",
    category: str = "cyber",
    scope: str = "session",
    timestamp: str = "2026-08-27T09:34:10.341Z",
) -> str:
    return json.dumps(
        {
            "subtype": "model_refusal_fallback",
            "originalModel": original,
            "fallbackModel": fallback,
            "apiRefusalCategory": category,
            "scope": scope,
            "timestamp": timestamp,
        }
    )


def _ordinary_line() -> str:
    return json.dumps({"type": "user", "message": {"role": "user", "content": "hello"}})


@pytest.fixture
def handler() -> ModelDowngradeRecorderHandler:
    return ModelDowngradeRecorderHandler()


@pytest.fixture
def untracked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "untracked"
    target.mkdir()
    monkeypatch.setattr(
        ProjectContext,
        "daemon_untracked_dir",
        classmethod(lambda cls: target),
    )
    return target


def _hook_input(transcript: Path, session_id: str = _SESSION) -> dict[str, Any]:
    return {
        "hook_event_name": "PostToolUse",
        "session_id": session_id,
        "transcript_path": str(transcript),
        "tool_name": "Bash",
    }


def _signal_path(untracked_dir: Path, session_id: str = _SESSION) -> Path:
    return untracked_dir / _SIGNAL_SUBDIR / f"{session_id}{_SIGNAL_SUFFIX}"


class TestRegistration:
    def test_handler_identity_and_priority_are_declared(
        self, handler: ModelDowngradeRecorderHandler
    ) -> None:
        assert handler.handler_id == HandlerID.MODEL_DOWNGRADE_RECORDER
        assert handler.priority == Priority.MODEL_DOWNGRADE_RECORDER
        assert handler.terminal is False

    def test_it_ships_enabled(self, handler: ModelDowngradeRecorderHandler) -> None:
        """The supervisor's auto-restore is wrong without it, so it is not opt-in.

        Writing one small file per downgraded session is the entire cost, and a
        session that never downgrades never gets a file at all.
        """
        assert handler.get_default_enabled() is True

    def test_it_documents_itself_for_claude_md(
        self, handler: ModelDowngradeRecorderHandler
    ) -> None:
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert guidance.strip()

    def test_it_declares_acceptance_tests_that_expect_allow(
        self, handler: ModelDowngradeRecorderHandler
    ) -> None:
        tests = handler.get_acceptance_tests()
        assert tests
        for test in tests:
            assert test.title
            assert test.expected_decision == Decision.ALLOW


class TestMatching:
    def test_a_post_tool_use_with_a_transcript_matches(
        self, handler: ModelDowngradeRecorderHandler, tmp_path: Path
    ) -> None:
        assert handler.matches(_hook_input(tmp_path / "t.jsonl")) is True

    @pytest.mark.parametrize(
        "overrides",
        [
            {"transcript_path": ""},
            {"session_id": ""},
        ],
        ids=["no-transcript", "no-session"],
    )
    def test_an_input_missing_what_it_needs_does_not_match(
        self,
        handler: ModelDowngradeRecorderHandler,
        tmp_path: Path,
        overrides: dict[str, str],
    ) -> None:
        hook_input = _hook_input(tmp_path / "t.jsonl") | overrides
        assert handler.matches(hook_input) is False


class TestRecording:
    def test_a_downgrade_record_is_published_for_the_session(
        self, handler: ModelDowngradeRecorderHandler, tmp_path: Path, untracked: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        transcript.write_text(f"{_ordinary_line()}\n{_subtype_line()}\n", encoding="utf-8")

        handler.handle(_hook_input(transcript))

        payload = json.loads(_signal_path(untracked).read_text(encoding="utf-8"))
        assert payload["session_id"] == _SESSION
        assert payload["original_model"] == "claude-fable-5"
        assert payload["fallback_model"] == "claude-opus-4-8"
        assert payload["category"] == "cyber"
        assert payload["scope"] == "session"
        assert payload["record_ts"] == "2026-08-27T09:34:10.341Z"

    def test_the_signal_resolves_model_ids_to_families(
        self, handler: ModelDowngradeRecorderHandler, tmp_path: Path, untracked: Path
    ) -> None:
        """The supervisor reasons in families; resolving here keeps it thin."""
        transcript = tmp_path / "t.jsonl"
        transcript.write_text(f"{_subtype_line()}\n", encoding="utf-8")

        handler.handle(_hook_input(transcript))

        payload = json.loads(_signal_path(untracked).read_text(encoding="utf-8"))
        assert payload["original_family"] == "fable"
        assert payload["fallback_family"] == "opus"

    def test_an_unrecognised_model_id_yields_a_null_family_not_a_guess(
        self, handler: ModelDowngradeRecorderHandler, tmp_path: Path, untracked: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        transcript.write_text(f"{_subtype_line(original='claude-zebra-9')}\n", encoding="utf-8")

        handler.handle(_hook_input(transcript))

        payload = json.loads(_signal_path(untracked).read_text(encoding="utf-8"))
        assert payload["original_family"] is None
        assert payload["fallback_family"] == "opus"

    def test_a_transcript_with_no_downgrade_writes_nothing(
        self, handler: ModelDowngradeRecorderHandler, tmp_path: Path, untracked: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        transcript.write_text(f"{_ordinary_line()}\n", encoding="utf-8")

        handler.handle(_hook_input(transcript))

        assert not _signal_path(untracked).exists()

    def test_the_handler_never_speaks(
        self, handler: ModelDowngradeRecorderHandler, tmp_path: Path, untracked: Path
    ) -> None:
        """A recorder that advises would fire on every tool call of a long session."""
        transcript = tmp_path / "t.jsonl"
        transcript.write_text(f"{_subtype_line()}\n", encoding="utf-8")

        result = handler.handle(_hook_input(transcript))

        assert result.decision == Decision.ALLOW
        assert not getattr(result, "additional_context", None)

    def test_each_session_gets_its_own_signal(
        self, handler: ModelDowngradeRecorderHandler, tmp_path: Path, untracked: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        transcript.write_text(f"{_subtype_line()}\n", encoding="utf-8")

        handler.handle(_hook_input(transcript, session_id="sess-one"))
        handler.handle(_hook_input(transcript, session_id="sess-two"))

        assert _signal_path(untracked, "sess-one").exists()
        assert _signal_path(untracked, "sess-two").exists()

    def test_a_session_id_with_path_separators_cannot_escape_the_directory(
        self, handler: ModelDowngradeRecorderHandler, tmp_path: Path, untracked: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        transcript.write_text(f"{_subtype_line()}\n", encoding="utf-8")

        handler.handle(_hook_input(transcript, session_id="../../escape"))

        written = list((untracked / _SIGNAL_SUBDIR).glob(f"*{_SIGNAL_SUFFIX}"))
        assert len(written) == 1
        assert written[0].parent == untracked / _SIGNAL_SUBDIR


class TestRewriteDiscipline:
    def test_an_unchanged_record_does_not_rewrite_the_signal(
        self, handler: ModelDowngradeRecorderHandler, tmp_path: Path, untracked: Path
    ) -> None:
        """PostToolUse fires constantly; churning the file would destroy its mtime."""
        transcript = tmp_path / "t.jsonl"
        transcript.write_text(f"{_subtype_line()}\n", encoding="utf-8")
        handler.handle(_hook_input(transcript))
        first = _signal_path(untracked).read_bytes()
        first_mtime = _signal_path(untracked).stat().st_mtime_ns

        handler.handle(_hook_input(transcript))

        assert _signal_path(untracked).read_bytes() == first
        assert _signal_path(untracked).stat().st_mtime_ns == first_mtime

    def test_a_later_different_record_replaces_the_signal(
        self, handler: ModelDowngradeRecorderHandler, tmp_path: Path, untracked: Path
    ) -> None:
        transcript = tmp_path / "t.jsonl"
        transcript.write_text(f"{_subtype_line()}\n", encoding="utf-8")
        handler.handle(_hook_input(transcript))

        with transcript.open("a", encoding="utf-8") as stream:
            stream.write(f"{_subtype_line(timestamp='2026-08-27T11:00:00.000Z')}\n")
        handler.handle(_hook_input(transcript))

        payload = json.loads(_signal_path(untracked).read_text(encoding="utf-8"))
        assert payload["record_ts"] == "2026-08-27T11:00:00.000Z"


class TestFailureModes:
    def test_a_missing_transcript_is_silently_tolerated(
        self, handler: ModelDowngradeRecorderHandler, tmp_path: Path, untracked: Path
    ) -> None:
        result = handler.handle(_hook_input(tmp_path / "gone.jsonl"))

        assert result.decision == Decision.ALLOW
        assert not _signal_path(untracked).exists()

    def test_an_unavailable_project_context_does_not_raise(
        self,
        handler: ModelDowngradeRecorderHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A hook dispatch must survive a daemon started outside a project."""
        transcript = tmp_path / "t.jsonl"
        transcript.write_text(f"{_subtype_line()}\n", encoding="utf-8")

        def _boom(cls: type[ProjectContext]) -> Path:
            raise RuntimeError("no project context")

        monkeypatch.setattr(ProjectContext, "daemon_untracked_dir", classmethod(_boom))

        assert handler.handle(_hook_input(transcript)).decision == Decision.ALLOW
