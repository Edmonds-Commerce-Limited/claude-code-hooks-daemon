"""Tests for the dispatch-source and role classifier (Plan 00472 Task 3.2)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.utils.dispatch_tier import (
    TIER_TOKEN,
    DispatchFacts,
    DispatchRole,
    DispatchSource,
    classify,
    classify_role,
    has_tier_token,
    read_env_subagent_model,
    spawner_model,
    tier_reason,
)

_BASE = DispatchFacts(
    subagent_type="general-purpose",
    model_param="",
    definition_model="",
    definition_builtin=False,
    env_model="",
    main_model="claude-opus-5-5",
)


def facts(**overrides: Any) -> DispatchFacts:
    return replace(_BASE, **overrides)


class TestSourceMatrix:
    """472-B section 1.2: one row per resolution case."""

    @pytest.mark.parametrize(
        ("overrides", "source", "family"),
        [
            # fork always inherits, even with a model or env set
            ({"subagent_type": "fork", "model_param": "haiku"}, DispatchSource.FORK, "opus"),
            ({"model_param": "sonnet"}, DispatchSource.EXPLICIT, "sonnet"),
            # explicit wins over the definition and the env
            (
                {"model_param": "opus", "definition_model": "sonnet", "env_model": "haiku"},
                DispatchSource.EXPLICIT,
                "opus",
            ),
            ({"model_param": "inherit"}, DispatchSource.EXPLICIT, "opus"),
            ({"definition_model": "sonnet"}, DispatchSource.DEFINITION, "sonnet"),
            ({"definition_model": "claude-haiku-4-5"}, DispatchSource.DEFINITION, "haiku"),
            # `inherit` in the frontmatter falls through to the env, then main
            ({"definition_model": "inherit", "env_model": "sonnet"}, DispatchSource.ENV, "sonnet"),
            ({"definition_model": "inherit"}, DispatchSource.INHERITED, "opus"),
            ({"env_model": "sonnet"}, DispatchSource.ENV, "sonnet"),
            # built-in Explore: no env, capped at Opus
            (
                {"subagent_type": "Explore", "definition_builtin": True, "env_model": "sonnet"},
                DispatchSource.INHERITED_CAPPED,
                "opus",
            ),
            (
                {
                    "subagent_type": "Explore",
                    "definition_builtin": True,
                    "main_model": "claude-fable-5-1",
                },
                DispatchSource.INHERITED_CAPPED,
                "opus",
            ),
            # a project Explore with a model is a definition
            (
                {"subagent_type": "Explore", "definition_model": "sonnet"},
                DispatchSource.DEFINITION,
                "sonnet",
            ),
            # built-in Plan ignores the env too
            (
                {"subagent_type": "Plan", "definition_builtin": True, "env_model": "sonnet"},
                DispatchSource.INHERITED,
                "opus",
            ),
            # a built-in with its own model
            (
                {"subagent_type": "claude-code-guide", "definition_builtin": True},
                DispatchSource.DEFINITION,
                "haiku",
            ),
            ({}, DispatchSource.INHERITED, "opus"),
            ({"main_model": "claude-fable-5-1"}, DispatchSource.INHERITED, "fable"),
        ],
    )
    def test_row(self, overrides: dict[str, Any], source: DispatchSource, family: str) -> None:
        tier = classify(facts(**overrides), name="", description="")
        assert tier.source is source
        assert tier.predicted_family == family

    def test_unknown_main_predicts_nothing_for_an_inherited_dispatch(self) -> None:
        tier = classify(facts(main_model=""), name="", description="")
        assert tier.source is DispatchSource.INHERITED
        assert tier.predicted_family is None

    def test_explicit_does_not_need_the_main_model(self) -> None:
        tier = classify(facts(main_model="", model_param="haiku"), name="", description="")
        assert tier.predicted_family == "haiku"


class TestRole:
    @pytest.mark.parametrize(
        ("subagent_type", "name", "description", "role"),
        [
            ("python-developer", "", "Fix review findings on plan 00463", DispatchRole.FIX),
            ("python-developer", "n23-fixer-r5", "Resume the review fixes", DispatchRole.FIX),
            ("general-purpose", "review-n56-3", "Review the branch", DispatchRole.REVIEW),
            ("code-reviewer", "", "Re-review the fix", DispatchRole.REVIEW),
            ("security-reviewer", "", "Check it", DispatchRole.SECURITY),
            ("general-purpose", "sec-sweep-4", "Sweep the guards", DispatchRole.SECURITY),
            ("general-purpose", "", "Security review of the resolver", DispatchRole.SECURITY),
            ("general-purpose", "", "Adversarial review of the gate", DispatchRole.ADVERSARIAL),
            ("general-purpose", "", "Decide which option ships", DispatchRole.DECIDE),
            ("general-purpose", "", "Rule on the gate", DispatchRole.DECIDE),
            ("python-developer", "", "Implement Task 3.2", DispatchRole.IMPLEMENT),
            ("qa-runner", "", "Run it", DispatchRole.VERIFY),
            ("general-purpose", "", "Narrow verify of N47", DispatchRole.VERIFY),
            ("Explore", "", "Where is the router", DispatchRole.SCOUT),
            ("hooks-daemon-plan-dedupe-scout", "", "Check plans", DispatchRole.SCOUT),
            ("general-purpose", "", "Update the docs page", DispatchRole.DOCS),
            ("general-purpose", "", "Rename a variable", DispatchRole.OTHER),
        ],
    )
    def test_role(self, subagent_type: str, name: str, description: str, role: DispatchRole) -> None:
        assert classify_role(subagent_type, name, description) is role

    def test_classify_carries_the_role(self) -> None:
        tier = classify(
            facts(subagent_type="python-developer", definition_model="sonnet"),
            name="",
            description="Fix review findings",
        )
        assert tier.role is DispatchRole.FIX


class TestTierToken:
    def test_token_line(self) -> None:
        assert TIER_TOKEN == "tier:"
        assert has_tier_token("Do the work.\ntier: hardest fail-closed line\n")

    def test_token_must_carry_a_reason(self) -> None:
        assert not has_tier_token("tier:\n")

    def test_no_token(self) -> None:
        assert not has_tier_token("Pick the cheapest tier: sonnet")

    def test_reason_is_the_rest_of_the_line(self) -> None:
        assert tier_reason("x\n  tier: hardest fail-closed line  \ny") == "hardest fail-closed line"
        assert tier_reason("no token") == ""


class TestEnvModel:
    def test_reads_the_env_block(self, tmp_path: Path) -> None:
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir()
        settings.write_text(json.dumps({"env": {"CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"}}))
        assert read_env_subagent_model(tmp_path) == "sonnet"

    @pytest.mark.parametrize("content", ["{}", "not json", '{"env": []}', '{"env": {"X": "1"}}'])
    def test_absent_or_malformed_reads_as_unset(self, tmp_path: Path, content: str) -> None:
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir()
        settings.write_text(content)
        assert read_env_subagent_model(tmp_path) == ""

    def test_no_settings_file(self, tmp_path: Path) -> None:
        assert read_env_subagent_model(tmp_path) == ""


def assistant_line(model: str) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {"model": model, "usage": {"input_tokens": 10}, "stop_reason": "tool_use"},
        }
    )


class TestSpawnerModel:
    def test_main_thread_reads_its_own_transcript(self, tmp_path: Path) -> None:
        transcript = tmp_path / "s1.jsonl"
        transcript.write_text(assistant_line("claude-fable-5-1") + "\n")
        hook_input = {"session_id": "s1", "transcript_path": str(transcript)}
        assert spawner_model(hook_input, tmp_path) == "claude-fable-5-1"

    def test_subagent_reads_its_own_transcript(self, tmp_path: Path) -> None:
        main = tmp_path / "s1.jsonl"
        main.write_text(assistant_line("claude-fable-5-1") + "\n")
        agents = tmp_path / "s1" / "subagents"
        agents.mkdir(parents=True)
        (agents / "agent-a0123456789abcdef.jsonl").write_text(
            assistant_line("claude-sonnet-5-5") + "\n"
        )
        hook_input = {
            "session_id": "s1",
            "transcript_path": str(main),
            "agent_id": "a0123456789abcdef",
        }
        assert spawner_model(hook_input, tmp_path) == "claude-sonnet-5-5"

    def test_main_falls_back_to_the_context_sidecar(self, tmp_path: Path) -> None:
        sidecar = tmp_path / "context-sidecar" / "s1.json"
        sidecar.parent.mkdir()
        sidecar.write_text(json.dumps({"model_id": "claude-opus-5-5"}))
        hook_input = {"session_id": "s1", "transcript_path": str(tmp_path / "missing.jsonl")}
        assert spawner_model(hook_input, tmp_path) == "claude-opus-5-5"

    def test_unknown_when_nothing_reads(self, tmp_path: Path) -> None:
        assert spawner_model({"session_id": "s1"}, tmp_path) == ""

    def test_a_subagent_never_takes_the_main_sidecar(self, tmp_path: Path) -> None:
        sidecar = tmp_path / "context-sidecar" / "s1.json"
        sidecar.parent.mkdir()
        sidecar.write_text(json.dumps({"model_id": "claude-opus-5-5"}))
        hook_input = {"session_id": "s1", "transcript_path": "", "agent_id": "a0123456789abcdef"}
        assert spawner_model(hook_input, tmp_path) == ""
