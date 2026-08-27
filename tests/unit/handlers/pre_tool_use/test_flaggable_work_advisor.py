"""Unit tests for FlaggableWorkAdvisorHandler (Plan 00278 Phase 3).

Advisory-only PreToolUse handler (ships DISABLED). When a Read/Edit/Write/
Grep targets a path matching configured flaggable globs, a Bash command
mentions such a path, or the tool input text matches 2+ configured topic
terms, it advises delegating the WHOLE sub-task to the quarantine subagent
BEFORE opening the content. Rate-limited: once per session per matched key.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.flaggable_work_advisor import (
    FlaggableWorkAdvisorHandler,
)


def _read(path: str, session_id: str = "s1") -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "tool_name": "Read",
        "tool_input": {"file_path": path},
    }


def _bash(command: str, session_id: str = "s1") -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


def _write(path: str, content: str, session_id: str = "s1") -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "tool_name": "Write",
        "tool_input": {"file_path": path, "content": content},
    }


@pytest.fixture
def handler() -> FlaggableWorkAdvisorHandler:
    instance = FlaggableWorkAdvisorHandler()
    instance._flaggable_path_globs = ["firewall/**", "*.rules"]
    return instance


class TestInitialisation:
    def test_identity(self) -> None:
        instance = FlaggableWorkAdvisorHandler()
        assert instance.name == HandlerID.FLAGGABLE_WORK_ADVISOR.display_name
        assert instance.priority == Priority.FLAGGABLE_WORK_ADVISOR
        assert instance.terminal is False

    def test_ships_disabled(self) -> None:
        assert FlaggableWorkAdvisorHandler().get_default_enabled() is False


class TestPathGlobMatching:
    def test_read_of_flaggable_path_matches(self, handler: FlaggableWorkAdvisorHandler) -> None:
        assert handler.matches(_read("/project/firewall/edge/rules.yml")) is True

    def test_edit_of_flaggable_extension_matches(
        self, handler: FlaggableWorkAdvisorHandler
    ) -> None:
        payload = _read("/project/etc/edge.rules")
        payload["tool_name"] = "Edit"
        payload["tool_input"] = {"file_path": "/project/etc/edge.rules", "old_string": "a"}
        assert handler.matches(payload) is True

    def test_grep_path_option_matches(self, handler: FlaggableWorkAdvisorHandler) -> None:
        payload: dict[str, Any] = {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Grep",
            "tool_input": {"pattern": "drop", "path": "/project/firewall/edge"},
        }
        assert handler.matches(payload) is True

    def test_unrelated_path_does_not_match(self, handler: FlaggableWorkAdvisorHandler) -> None:
        assert handler.matches(_read("/project/src/app.py")) is False

    def test_bash_command_mentioning_flaggable_path_matches(
        self, handler: FlaggableWorkAdvisorHandler
    ) -> None:
        assert handler.matches(_bash("cat /project/firewall/edge/rules.yml")) is True

    def test_bash_without_flaggable_path_does_not_match(
        self, handler: FlaggableWorkAdvisorHandler
    ) -> None:
        assert handler.matches(_bash("ls /project/src")) is False

    def test_no_globs_configured_means_no_path_matches(self) -> None:
        instance = FlaggableWorkAdvisorHandler()
        assert instance.matches(_read("/project/firewall/edge/rules.yml")) is False


class TestTopicTermMatching:
    def test_two_seed_terms_in_content_match(self, handler: FlaggableWorkAdvisorHandler) -> None:
        payload = _write(
            "/project/docs/note.md",
            "This documents the exploit and the rootkit internals in depth.",
        )
        assert handler.matches(payload) is True

    def test_single_term_does_not_match(self, handler: FlaggableWorkAdvisorHandler) -> None:
        payload = _write("/project/docs/note.md", "We patched the exploit yesterday.")
        assert handler.matches(payload) is False

    def test_terms_are_case_insensitive(self, handler: FlaggableWorkAdvisorHandler) -> None:
        payload = _write("/project/docs/note.md", "Spoofing defence versus EVASION tricks.")
        assert handler.matches(payload) is True


class TestModeMerging:
    def test_additive_mode_extends_seed_terms(self) -> None:
        instance = FlaggableWorkAdvisorHandler()
        instance._flaggable_topic_terms = ["tarpit"]
        payload = _write("/p/doc.md", "tarpit plus rootkit analysis")
        assert instance.matches(payload) is True

    def test_replace_mode_discards_seed_terms(self) -> None:
        instance = FlaggableWorkAdvisorHandler()
        instance._mode = "replace"
        instance._flaggable_topic_terms = ["tarpit", "honeypot"]
        seed_only = _write("/p/doc.md", "exploit and rootkit analysis")
        assert instance.matches(seed_only) is False
        replaced = _write("/p/doc.md", "tarpit and honeypot analysis")
        assert instance.matches(replaced) is True


class TestRateLimiting:
    def test_same_path_advises_once_per_session(self, handler: FlaggableWorkAdvisorHandler) -> None:
        payload = _read("/project/firewall/edge/rules.yml")
        assert handler.matches(payload) is True
        first = handler.handle(payload)
        assert first.context
        assert handler.matches(payload) is False

    def test_different_path_advises_again(self, handler: FlaggableWorkAdvisorHandler) -> None:
        first = _read("/project/firewall/edge/rules.yml")
        handler.handle(first)
        second = _read("/project/firewall/tarpit/rules.yml")
        assert handler.matches(second) is True

    def test_different_session_advises_again(self, handler: FlaggableWorkAdvisorHandler) -> None:
        handler.handle(_read("/project/firewall/edge/rules.yml", session_id="a"))
        assert handler.matches(_read("/project/firewall/edge/rules.yml", session_id="b")) is True


class TestHandle:
    def test_never_denies_and_names_quarantine_agent(
        self, handler: FlaggableWorkAdvisorHandler
    ) -> None:
        result = handler.handle(_read("/project/firewall/edge/rules.yml"))
        assert result.decision == Decision.ALLOW
        text = "\n".join(result.context)
        assert "hooks-daemon-opus-security" in text
        assert "subagent_type" in text
        assert "BEFORE" in text
        assert "summary" in text.lower()

    def test_custom_quarantine_agent_is_named(self) -> None:
        instance = FlaggableWorkAdvisorHandler()
        instance._flaggable_path_globs = ["firewall/**"]
        instance._quarantine_agent = "my-quarantine"
        result = instance.handle(_read("/project/firewall/x.yml"))
        assert "my-quarantine" in "\n".join(result.context)


class TestGuidanceSurfaces:
    def test_get_claude_md(self) -> None:
        guidance = FlaggableWorkAdvisorHandler().get_claude_md()
        assert guidance is not None
        assert "flaggable_work_advisor" in guidance

    def test_get_acceptance_tests(self) -> None:
        tests = FlaggableWorkAdvisorHandler().get_acceptance_tests()
        assert tests
        for test in tests:
            assert test.title
            assert test.expected_decision == Decision.ALLOW


class TestEdgeBranches:
    def test_non_dict_hook_input_does_not_match(self, handler: FlaggableWorkAdvisorHandler) -> None:
        payload: Any = None
        assert handler.matches(payload) is False

    def test_non_dict_tool_input_does_not_match(self, handler: FlaggableWorkAdvisorHandler) -> None:
        payload: dict[str, Any] = {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Read",
            "tool_input": "not-a-dict",
        }
        assert handler.matches(payload) is False

    def test_replace_mode_with_single_term_disables_topic_route(self) -> None:
        instance = FlaggableWorkAdvisorHandler()
        instance._mode = "replace"
        instance._flaggable_topic_terms = ["tarpit"]
        payload = _write("/p/doc.md", "tarpit and tarpit again with exploit rootkit")
        assert instance.matches(payload) is False

    def test_unserialisable_tool_input_does_not_match_topic_route(
        self, handler: FlaggableWorkAdvisorHandler
    ) -> None:
        payload = _write("/p/doc.md", "exploit rootkit")
        payload["tool_input"]["weird"] = object()
        assert handler.matches(payload) is False

    def test_handle_with_nothing_pending_is_a_silent_allow(
        self, handler: FlaggableWorkAdvisorHandler
    ) -> None:
        payload = _read("/project/firewall/edge/rules.yml")
        handler.handle(payload)
        second = handler.handle(payload)
        assert second.decision == Decision.ALLOW
        assert not second.context

    def test_advised_state_is_bounded_fifo(self, handler: FlaggableWorkAdvisorHandler) -> None:
        for index in range(600):
            handler._record_advised(f"session-{index}", "key")
        assert len(handler._advised) <= 512
