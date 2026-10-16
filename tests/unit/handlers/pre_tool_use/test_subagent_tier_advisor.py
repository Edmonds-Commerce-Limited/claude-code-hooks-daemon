"""Tests for SubagentTierAdvisorHandler (Plan 00472 Task 3.5, rulings D2-D4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.subagent_tier_advisor import (
    SubagentTierAdvisorHandler,
)
from claude_code_hooks_daemon.utils.spend_ledger import read_events

#: This repository's table (RULINGS-fable.md D2, D3).
REPO_TYPES = {
    "python-developer": {"ceiling": "sonnet"},
    "qa-fixer": {"ceiling": "sonnet"},
    "qa-runner": {"ceiling": "haiku"},
    "hooks-daemon-plan-dedupe-scout": {"ceiling": "haiku"},
    "Explore": {"ceiling": "sonnet"},
    "code-reviewer": {"floor": "opus"},
    "security-reviewer": {"floor": "opus"},
    "hooks-daemon-docs-qa": {"floor": "opus"},
}
REPO_ROLE_FLOORS = {"security": "opus", "adversarial": "opus", "decide": "opus"}


def _agent(root: Path, name: str, model: str) -> None:
    agents = root / ".claude" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    (agents / f"{name}.md").write_text(f"---\nname: {name}\nmodel: {model}\n---\nbody\n")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    _agent(tmp_path, "python-developer", "sonnet")
    _agent(tmp_path, "code-reviewer", "opus")
    return tmp_path


def make(root: Path, *, repo_config: bool = True) -> SubagentTierAdvisorHandler:
    handler = SubagentTierAdvisorHandler()
    handler._untracked_override = root
    handler._project_root_override = root
    if repo_config:
        handler._default_ceiling = "sonnet"
        handler._types = REPO_TYPES
        handler._role_floors = REPO_ROLE_FLOORS
    return handler


def dispatch(root: Path, main_model: str = "claude-opus-5-5", **tool_input: Any) -> dict:
    transcript = root / "s1.jsonl"
    if main_model:
        record = {"type": "assistant", "message": {"model": main_model, "usage": {"x": 1}}}
        transcript.write_text(json.dumps(record) + "\n")
    elif transcript.exists():
        transcript.unlink()
    tool_input.setdefault("subagent_type", "general-purpose")
    tool_input.setdefault("description", "Implement the parser")
    tool_input.setdefault("prompt", "Do it.")
    return {
        "tool_name": "Agent",
        "session_id": "s1",
        "transcript_path": str(transcript),
        "tool_input": tool_input,
    }


def advice(handler: SubagentTierAdvisorHandler, hook_input: dict) -> list[str]:
    result = handler.handle(hook_input)
    assert result.decision == Decision.ALLOW
    return list(result.context)


class TestFires:
    def test_inherited_top_tier(self, root: Path) -> None:
        (message,) = advice(make(root), dispatch(root))
        assert "general-purpose" in message
        assert "runs on opus" in message
        assert "model: sonnet" in message
        assert "tier:" in message
        assert message.count("\n") <= 1

    def test_fork_from_the_top_tier(self, root: Path) -> None:
        (message,) = advice(make(root), dispatch(root, "claude-fable-5-1", subagent_type="fork"))
        assert "runs on fable" in message
        assert "fork" in message

    def test_explicit_above_the_definition(self, root: Path) -> None:
        (message,) = advice(
            make(root), dispatch(root, subagent_type="python-developer", model="opus")
        )
        assert "runs on opus" in message
        assert "model: sonnet" in message

    def test_explicit_above_the_definition_with_no_table(self, root: Path) -> None:
        (message,) = advice(
            make(root, repo_config=False),
            dispatch(root, subagent_type="python-developer", model="opus"),
        )
        assert "model: sonnet" in message

    def test_inherited_top_tier_with_no_table_names_the_next_tier_down(self, root: Path) -> None:
        (message,) = advice(make(root, repo_config=False), dispatch(root, "claude-fable-5-1"))
        assert "runs on fable" in message
        assert "model: opus" in message

    def test_explore_is_named_capped(self, root: Path) -> None:
        (message,) = advice(
            make(root), dispatch(root, "claude-fable-5-1", subagent_type="Explore", description="")
        )
        assert "runs on opus" in message
        assert "model: sonnet" in message

    def test_floor_on_an_explicit_sonnet_code_reviewer(self, root: Path) -> None:
        (message,) = advice(
            make(root),
            dispatch(root, subagent_type="code-reviewer", model="sonnet", description="Review"),
        )
        assert "FLOOR" in message
        assert "below the opus floor" in message
        assert "model: opus" in message

    def test_role_floor_on_an_inherited_sonnet_security_check(self, root: Path) -> None:
        (message,) = advice(
            make(root),
            dispatch(root, "claude-sonnet-5-5", description="Security sweep of the guards"),
        )
        assert "below the opus floor" in message


class TestSilent:
    @pytest.mark.parametrize(
        "description",
        ["Security review of the resolver", "Adversarial pass", "Rule on the gate", "Review it"],
    )
    def test_top_tier_roles(self, root: Path, description: str) -> None:
        assert advice(make(root), dispatch(root, description=description)) == []

    def test_tier_token(self, root: Path) -> None:
        hook_input = dispatch(root, prompt="Do it.\ntier: hardest fail-closed line\n")
        assert advice(make(root), hook_input) == []

    def test_explicit_not_above_the_definition(self, root: Path) -> None:
        hook_input = dispatch(root, subagent_type="python-developer", model="sonnet")
        assert advice(make(root), hook_input) == []

    def test_explicit_with_no_definition_model_is_the_orchestrators_choice(
        self, root: Path
    ) -> None:
        assert advice(make(root), dispatch(root, model="opus")) == []

    def test_definition_source(self, root: Path) -> None:
        assert advice(make(root), dispatch(root, subagent_type="python-developer")) == []

    def test_unknown_main_model(self, root: Path) -> None:
        assert advice(make(root), dispatch(root, main_model="")) == []

    def test_inherited_at_or_under_the_ceiling(self, root: Path) -> None:
        assert advice(make(root), dispatch(root, "claude-sonnet-5-5")) == []

    def test_inherited_sonnet_with_no_table(self, root: Path) -> None:
        assert advice(make(root, repo_config=False), dispatch(root, "claude-sonnet-5-5")) == []

    def test_explicit_opus_code_reviewer_meets_its_floor(self, root: Path) -> None:
        hook_input = dispatch(root, subagent_type="code-reviewer", model="opus")
        assert advice(make(root), hook_input) == []

    def test_non_dict_tool_input(self, root: Path) -> None:
        hook_input = dispatch(root)
        hook_input["tool_input"] = "x"
        assert advice(make(root), hook_input) == []


class TestOncePerKey:
    def test_once_per_session_type_and_source(self, root: Path) -> None:
        handler = make(root)
        first = dispatch(root)
        assert advice(handler, first)
        handler.commit_side_effects(first, Decision.ALLOW)
        assert advice(handler, dispatch(root)) == []
        # a different source of the same type is a different key
        assert advice(handler, dispatch(root, "claude-fable-5-1", subagent_type="fork"))

    def test_the_key_is_not_spent_by_a_denied_dispatch(self, root: Path) -> None:
        handler = make(root)
        hook_input = dispatch(root)
        handler.commit_side_effects(hook_input, Decision.DENY)
        assert advice(handler, dispatch(root))

    def test_an_advisory_is_a_ledger_event(self, root: Path) -> None:
        handler = make(root)
        hook_input = dispatch(root)
        handler.commit_side_effects(hook_input, Decision.ALLOW)
        (event,) = read_events(root, "s1")
        assert event["kind"] == "tier-advisory"
        assert event["subagent_type"] == "general-purpose"
        assert event["source"] == "inherited"
        assert event["predicted_family"] == "opus"
        assert event["suggested"] == "sonnet"
        assert event["mode"] == "advise"

    def test_a_silent_dispatch_records_nothing(self, root: Path) -> None:
        handler = make(root)
        hook_input = dispatch(root, description="Review it")
        handler.commit_side_effects(hook_input, Decision.ALLOW)
        assert read_events(root, "s1") == []


class TestNeverDenies:
    """Criterion 05: allow across the whole matrix."""

    @pytest.mark.parametrize("main_model", ["", "claude-haiku-4-5", "claude-opus-5-5", "fable"])
    @pytest.mark.parametrize(
        "subagent_type", ["general-purpose", "fork", "Explore", "code-reviewer"]
    )
    @pytest.mark.parametrize("model", ["", "haiku", "sonnet", "opus", "fable"])
    def test_allow(self, root: Path, main_model: str, subagent_type: str, model: str) -> None:
        extra = {"model": model} if model else {}
        hook_input = dispatch(root, main_model, subagent_type=subagent_type, **extra)
        assert make(root).handle(hook_input).decision == Decision.ALLOW

    def test_a_failure_to_judge_allows(self, root: Path) -> None:
        handler = make(root)
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.subagent_tier_advisor.spawner_model",
            side_effect=RuntimeError("boom"),
        ):
            result = handler.handle(dispatch(root))
        assert result.decision == Decision.ALLOW
        assert result.context == []


class TestOptions:
    def test_valid_options(self) -> None:
        assert (
            SubagentTierAdvisorHandler.validate_options(
                {
                    "mode": "advise",
                    "default_ceiling": "sonnet",
                    "types": REPO_TYPES,
                    "role_floors": REPO_ROLE_FLOORS,
                }
            )
            == {}
        )

    def test_null_ceiling_and_empty_tables_are_valid(self) -> None:
        options = {"default_ceiling": None, "types": {}, "role_floors": {}}
        assert SubagentTierAdvisorHandler.validate_options(options) == {}

    @pytest.mark.parametrize(
        ("options", "key"),
        [
            ({"mode": "require_explicit"}, "mode"),
            ({"default_ceiling": "gpt"}, "default_ceiling"),
            ({"types": {"x": {"ceiling": "gpt"}}}, "types"),
            ({"types": {"x": {"cap": "sonnet"}}}, "types"),
            ({"types": ["x"]}, "types"),
            ({"role_floors": {"nonsense": "opus"}}, "role_floors"),
            ({"role_floors": {"security": "gpt"}}, "role_floors"),
        ],
    )
    def test_invalid_options(self, options: dict, key: str) -> None:
        assert key in SubagentTierAdvisorHandler.validate_options(options)


class TestMetadata:
    def test_non_terminal_advisory(self) -> None:
        handler = SubagentTierAdvisorHandler()
        assert handler.terminal is False
        assert handler.get_claude_md() is None
        fires, token = handler.get_acceptance_tests()
        assert fires.expected_decision == token.expected_decision == Decision.ALLOW
        assert fires.expected_message_patterns
        assert "tier:" in token.command
        assert token.expected_message_patterns == []

    def test_matches_dispatch_tools_only(self, root: Path) -> None:
        handler = make(root)
        assert handler.matches(dispatch(root))
        bash = dispatch(root)
        bash["tool_name"] = "Bash"
        assert not handler.matches(bash)
