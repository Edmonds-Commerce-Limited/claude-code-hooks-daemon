"""Tests for IdleHousekeepingAdvisoryHandler (Plan 00161).

The handler watches for repeated no-op failsafe-recovery ticks and, once the
session is demonstrably idle-and-caught-up, injects guidance to dispatch
specialist housekeeping sub-agents that produce shareable markdown reports.

Beta: opt-in (off by default), report-only.
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.transcript_reader import ContentBlock, TranscriptMessage
from claude_code_hooks_daemon.handlers.user_prompt_submit.idle_housekeeping_advisor import (
    _RECOVERY_MARKER,
    IdleHousekeepingAdvisoryHandler,
    count_trailing_noop_recovery_ticks,
)

_TICK = f"{_RECOVERY_MARKER} (automated hourly safety net). Resume if interrupted."


def _user(text: str) -> TranscriptMessage:
    return TranscriptMessage(role="user", content=text, raw={})


def _assistant_text(text: str) -> TranscriptMessage:
    return TranscriptMessage(
        role="assistant",
        content=text,
        raw={},
        content_blocks=(ContentBlock(block_type="text", text=text),),
    )


def _assistant_tool(tool: str = "Bash") -> TranscriptMessage:
    return TranscriptMessage(
        role="assistant",
        content="",
        raw={},
        content_blocks=(ContentBlock(block_type="tool_use", tool_name=tool),),
    )


class TestCountTrailingNoopRecoveryTicks:
    """The pure transcript-tail counter."""

    def test_empty_transcript_is_zero(self) -> None:
        assert count_trailing_noop_recovery_ticks([], _RECOVERY_MARKER) == 0

    def test_single_prior_tick_with_text_stop(self) -> None:
        messages = [
            _user(_TICK),
            _assistant_text("STOPPING BECAUSE: nothing to resume."),
        ]
        assert count_trailing_noop_recovery_ticks(messages, _RECOVERY_MARKER) == 1

    def test_multiple_consecutive_noop_ticks(self) -> None:
        messages = [
            _user(_TICK),
            _assistant_text("STOPPING BECAUSE: nothing to resume."),
            _user(_TICK),
            _assistant_text("STOPPING BECAUSE: nothing to resume."),
            _user(_TICK),
            _assistant_text("STOPPING BECAUSE: nothing to resume."),
        ]
        assert count_trailing_noop_recovery_ticks(messages, _RECOVERY_MARKER) == 3

    def test_tool_use_in_tail_breaks_the_run(self) -> None:
        """A tool_use means work happened - the session is NOT idle."""
        messages = [
            _user(_TICK),
            _assistant_text("resuming work"),
            _assistant_tool("Edit"),
            _user(_TICK),
            _assistant_text("STOPPING BECAUSE: nothing to resume."),
        ]
        # Newest run: user(tick) then assistant_text then assistant_tool -> break at tool
        assert count_trailing_noop_recovery_ticks(messages, _RECOVERY_MARKER) == 1

    def test_real_user_prompt_is_a_boundary(self) -> None:
        messages = [
            _user("please implement feature X"),
            _assistant_text("done"),
            _user(_TICK),
            _assistant_text("STOPPING BECAUSE: nothing to resume."),
        ]
        assert count_trailing_noop_recovery_ticks(messages, _RECOVERY_MARKER) == 1

    def test_real_prompt_at_tail_resets_to_zero(self) -> None:
        messages = [
            _user(_TICK),
            _assistant_text("STOPPING BECAUSE: nothing to resume."),
            _user("new task please"),
        ]
        assert count_trailing_noop_recovery_ticks(messages, _RECOVERY_MARKER) == 0


class TestInitialization:
    def test_handler_identity(self) -> None:
        handler = IdleHousekeepingAdvisoryHandler()
        assert handler.handler_id == HandlerID.IDLE_HOUSEKEEPING_ADVISORY
        assert handler.priority == Priority.IDLE_HOUSEKEEPING_ADVISORY
        assert handler.terminal is False

    def test_is_opt_in_off_by_default(self) -> None:
        """Beta: ships OFF by default (opt-in)."""
        assert (
            IdleHousekeepingAdvisoryHandler.get_default_enabled(
                IdleHousekeepingAdvisoryHandler.__new__(IdleHousekeepingAdvisoryHandler)
            )
            is False
        )

    def test_get_claude_md_documents_mode(self) -> None:
        md = IdleHousekeepingAdvisoryHandler().get_claude_md()
        assert md is not None
        assert "housekeeping" in md.lower()
        assert "report" in md.lower()


class TestMatches:
    def test_matches_any_string_prompt(self) -> None:
        handler = IdleHousekeepingAdvisoryHandler()
        assert handler.matches({"prompt": "anything"}) is True

    def test_does_not_match_non_string_prompt(self) -> None:
        handler = IdleHousekeepingAdvisoryHandler()
        assert handler.matches({"prompt": None}) is False
        assert handler.matches({}) is False


def _handle_with_messages(
    handler: IdleHousekeepingAdvisoryHandler,
    hook_input: dict[str, Any],
    messages: list[TranscriptMessage],
) -> Any:
    """Run handle() with the transcript reader stubbed to return `messages`."""
    with patch(
        "claude_code_hooks_daemon.handlers.user_prompt_submit.idle_housekeeping_advisor.TranscriptReader"
    ) as mock_reader_cls:
        instance = mock_reader_cls.return_value
        instance.load.return_value = None
        instance.get_messages.return_value = messages
        return handler.handle(hook_input)


class TestHandle:
    def _tick_input(self) -> dict[str, Any]:
        return {
            "prompt": _TICK,
            "session_id": "sess-1",
            "transcript_path": "/tmp/t.jsonl",
        }

    def test_non_recovery_prompt_allows_silently(self) -> None:
        handler = IdleHousekeepingAdvisoryHandler()
        result = handler.handle({"prompt": "do some work", "session_id": "s"})
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_below_threshold_does_not_fire(self) -> None:
        handler = IdleHousekeepingAdvisoryHandler()
        # Only the current tick, no prior no-op ticks in transcript -> count 0 < 2
        result = _handle_with_messages(handler, self._tick_input(), [])
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_at_threshold_injects_housekeeping_guidance(self) -> None:
        handler = IdleHousekeepingAdvisoryHandler()
        messages = [
            _user(_TICK),
            _assistant_text("STOPPING BECAUSE: nothing to resume."),
            _user(_TICK),
            _assistant_text("STOPPING BECAUSE: nothing to resume."),
        ]
        result = _handle_with_messages(handler, self._tick_input(), messages)
        assert result.decision == Decision.ALLOW
        assert result.context
        blob = " ".join(result.context).lower()
        assert "housekeeping" in blob
        assert "sub-agent" in blob or "subagent" in blob
        assert "report" in blob
        assert "markdown" in blob

    def test_tool_use_in_tail_suppresses_firing(self) -> None:
        handler = IdleHousekeepingAdvisoryHandler()
        messages = [
            _user(_TICK),
            _assistant_tool("Edit"),
            _user(_TICK),
            _assistant_text("stop"),
        ]
        result = _handle_with_messages(handler, self._tick_input(), messages)
        assert not result.context

    def test_pass_cap_prevents_refiring(self) -> None:
        handler = IdleHousekeepingAdvisoryHandler()
        messages = [
            _user(_TICK),
            _assistant_text("stop"),
            _user(_TICK),
            _assistant_text("stop"),
        ]
        first = _handle_with_messages(handler, self._tick_input(), messages)
        assert first.context  # fired once
        second = _handle_with_messages(handler, self._tick_input(), messages)
        assert not second.context  # capped

    def test_real_prompt_resets_pass_budget(self) -> None:
        handler = IdleHousekeepingAdvisoryHandler()
        messages = [
            _user(_TICK),
            _assistant_text("stop"),
            _user(_TICK),
            _assistant_text("stop"),
        ]
        assert _handle_with_messages(handler, self._tick_input(), messages).context
        # A real user prompt in the same session resets the budget
        handler.handle({"prompt": "new work", "session_id": "sess-1"})
        assert _handle_with_messages(handler, self._tick_input(), messages).context

    def test_missing_transcript_path_allows_silently(self) -> None:
        handler = IdleHousekeepingAdvisoryHandler()
        result = handler.handle({"prompt": _TICK, "session_id": "s"})
        assert result.decision == Decision.ALLOW
        assert not result.context


class TestCustomGuidanceDoc:
    """Projects can point the handler at a custom guidance doc (additive/replace)."""

    _MESSAGES = [
        _user(_TICK),
        _assistant_text("stop"),
        _user(_TICK),
        _assistant_text("stop"),
    ]

    def _fire(self, handler: IdleHousekeepingAdvisoryHandler) -> str:
        result = _handle_with_messages(
            handler,
            {"prompt": _TICK, "session_id": "s", "transcript_path": "/tmp/t.jsonl"},
            self._MESSAGES,
        )
        assert result.context
        return " ".join(result.context)

    def test_default_when_no_custom_doc(self) -> None:
        handler = IdleHousekeepingAdvisoryHandler()
        blob = self._fire(handler)
        assert "HOUSEKEEPING MODE" in blob

    def test_additive_appends_custom_doc(self, tmp_path: Path) -> None:
        doc = tmp_path / "housekeeping.md"
        doc.write_text("PROJECT-SPECIFIC: also run the widget audit.")
        handler = IdleHousekeepingAdvisoryHandler()
        handler._custom_guidance_doc = str(doc)
        handler._custom_guidance_mode = "additive"

        blob = self._fire(handler)
        assert "HOUSEKEEPING MODE" in blob  # default retained
        assert "PROJECT-SPECIFIC: also run the widget audit." in blob  # custom appended

    def test_replace_uses_only_custom_doc(self, tmp_path: Path) -> None:
        doc = tmp_path / "housekeeping.md"
        doc.write_text("ONLY DO THIS: run the widget audit and report.")
        handler = IdleHousekeepingAdvisoryHandler()
        handler._custom_guidance_doc = str(doc)
        handler._custom_guidance_mode = "replace"

        blob = self._fire(handler)
        assert "ONLY DO THIS: run the widget audit and report." in blob
        # The default's dispatch-subagents wording is gone in replace mode.
        assert "specialist housekeeping SUB-AGENTS" not in blob

    def test_missing_custom_doc_falls_back_to_default(self, tmp_path: Path) -> None:
        handler = IdleHousekeepingAdvisoryHandler()
        handler._custom_guidance_doc = str(tmp_path / "does-not-exist.md")
        handler._custom_guidance_mode = "replace"

        blob = self._fire(handler)
        assert "HOUSEKEEPING MODE" in blob  # fail-safe: default guidance

    def test_relative_path_resolved_against_project_root(self, tmp_path: Path) -> None:
        doc = tmp_path / "docs" / "hk.md"
        doc.parent.mkdir()
        doc.write_text("REL PATH GUIDANCE")
        handler = IdleHousekeepingAdvisoryHandler()
        handler._custom_guidance_doc = "docs/hk.md"
        handler._custom_guidance_mode = "replace"

        with patch(
            "claude_code_hooks_daemon.handlers.user_prompt_submit."
            "idle_housekeeping_advisor.ProjectContext"
        ) as mock_pc:
            mock_pc.project_root.return_value = tmp_path
            blob = self._fire(handler)
        assert "REL PATH GUIDANCE" in blob
