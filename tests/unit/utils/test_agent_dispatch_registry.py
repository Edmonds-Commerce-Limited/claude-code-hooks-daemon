"""Tests for the name -> definition-type record of dispatched sub-agents."""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.utils.agent_dispatch_registry import (
    effective_agent_type,
    record_dispatch,
)

_UNNAMED = "a57801934993f0485"
_NAMED = "aprobe-named-518-0123456789abcdef"


class TestAgentIdShape:
    def test_unnamed_id_ignores_a_stale_record(self, tmp_path: Path) -> None:
        record_dispatch(tmp_path, "s1", "qa-full-runner", "general-purpose")
        assert effective_agent_type(tmp_path, "s1", "qa-full-runner", _UNNAMED) == "qa-full-runner"

    def test_named_id_with_record_resolves_to_recorded_type(self, tmp_path: Path) -> None:
        record_dispatch(tmp_path, "s1", "probe-named", "qa-runner")
        assert effective_agent_type(tmp_path, "s1", "probe-named", _NAMED) == "qa-runner"

    def test_named_id_without_record_resolves_to_empty(self, tmp_path: Path) -> None:
        assert effective_agent_type(tmp_path, "s1", "qa-full-runner", _NAMED) == ""

    def test_unknown_id_format_fails_closed(self, tmp_path: Path) -> None:
        assert effective_agent_type(tmp_path, "s1", "qa-full-runner", "A57801934993F0485") == ""
        assert effective_agent_type(tmp_path, "s1", "qa-full-runner", "a1") == ""


class TestEffectiveAgentType:
    def test_unnamed_agent_type_is_trusted_as_its_type(self, tmp_path: Path) -> None:
        assert effective_agent_type(tmp_path, "s1", "qa-runner") == "qa-runner"

    def test_named_teammate_resolves_to_recorded_type(self, tmp_path: Path) -> None:
        record_dispatch(tmp_path, "s1", "probe-named", "qa-runner")
        assert effective_agent_type(tmp_path, "s1", "probe-named") == "qa-runner"

    def test_name_equal_to_another_type_resolves_to_its_real_type(self, tmp_path: Path) -> None:
        record_dispatch(tmp_path, "s1", "qa-full-runner", "python-developer")
        assert effective_agent_type(tmp_path, "s1", "qa-full-runner") == "python-developer"

    def test_record_without_type_resolves_to_empty(self, tmp_path: Path) -> None:
        record_dispatch(tmp_path, "s1", "worker", None)
        assert effective_agent_type(tmp_path, "s1", "worker") == ""

    def test_record_is_per_session(self, tmp_path: Path) -> None:
        record_dispatch(tmp_path, "s1", "worker", "qa-runner")
        assert effective_agent_type(tmp_path, "s2", "worker") == "worker"

    def test_later_dispatch_of_same_name_replaces_record(self, tmp_path: Path) -> None:
        record_dispatch(tmp_path, "s1", "worker", "qa-runner")
        record_dispatch(tmp_path, "s1", "worker", "code-reviewer")
        assert effective_agent_type(tmp_path, "s1", "worker") == "code-reviewer"

    def test_unsafe_session_id_and_name_are_contained(self, tmp_path: Path) -> None:
        record_dispatch(tmp_path, "../../etc", "../x", "qa-runner")
        assert effective_agent_type(tmp_path, "../../etc", "../x") == "qa-runner"
        assert all(tmp_path in p.parents for p in tmp_path.rglob("*.json"))

    def test_names_differing_only_in_unsafe_chars_do_not_collide(self, tmp_path: Path) -> None:
        record_dispatch(tmp_path, "s1", "a b", "qa-runner")
        assert effective_agent_type(tmp_path, "s1", "a_b") == "a_b"

    def test_garbled_record_fails_closed(self, tmp_path: Path) -> None:
        record_dispatch(tmp_path, "s1", "worker", "qa-runner")
        for path in tmp_path.rglob("*.json"):
            path.write_text("{not json", encoding="utf-8")
        assert effective_agent_type(tmp_path, "s1", "worker") == ""

    def test_record_of_a_different_name_fails_closed(self, tmp_path: Path) -> None:
        record_dispatch(tmp_path, "s1", "worker", "qa-runner")
        for path in tmp_path.rglob("*.json"):
            path.write_text('{"name": "other", "subagent_type": "x"}', encoding="utf-8")
        assert effective_agent_type(tmp_path, "s1", "worker") == ""
