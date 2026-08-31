"""Tests for rule_explain.lookup — Plan 00116 Task 6.1 (RED first).

``collect_handler_rules`` is exercised against small in-test handler
classes (no daemon, no filesystem discovery) so the lookup/matching logic
is tested in isolation from ``HandlerRegistry`` scanning. A separate
integration test exercises ``discover_handler_rules`` against the REAL
``claude_code_hooks_daemon.handlers`` package to prove enumeration finds
``destructive_git``'s real, already-migrated rules with zero bespoke
wiring — new rules from sibling migrations appear automatically.
"""

from __future__ import annotations

from typing import Any

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.rule_explain.lookup import (
    HandlerRules,
    collect_handler_rules,
    discover_handler_rules,
    find_handler,
    find_rule,
    near_handler_matches,
    near_rule_matches,
)


class FixtureNoRulesHandler(Handler):
    """A legacy handler with no declared rules."""

    def __init__(self) -> None:
        super().__init__(handler_id=HandlerID.TEST_SERVER, priority=Priority.TEST_HANDLER)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        return "## no-rules-handler guidance"

    def get_acceptance_tests(self) -> list[Any]:
        return []


class FixtureTwoRuleHandler(Handler):
    """A handler declaring two rules, for lookup/matching tests."""

    def __init__(self) -> None:
        super().__init__(handler_id=HandlerID.TEST_SERVER, priority=Priority.TEST_HANDLER)
        self._rules = [
            Rule(
                rule_id="R-TEST-ALPHA",
                blocked="`alpha command`",
                why="Alpha is unsafe",
                fix="Use safe-alpha instead",
                verbose="Full alpha rationale text.",
            ),
            Rule(
                rule_id="R-TEST-BETA",
                blocked="`beta command`",
                why="Beta is unsafe",
                fix="Use safe-beta instead",
                verbose="Full beta rationale text.",
            ),
        ]

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        return "## two-rule-handler guidance"

    def get_acceptance_tests(self) -> list[Any]:
        return []

    def get_rules(self) -> list[Rule]:
        return list(self._rules)


class FixtureBrokenHandler(Handler):
    """A handler whose get_rules() raises — must not abort enumeration."""

    def __init__(self) -> None:
        super().__init__(handler_id=HandlerID.TEST_SERVER, priority=Priority.TEST_HANDLER)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        return []

    def get_rules(self) -> list[Rule]:
        raise RuntimeError("boom")


class TestCollectHandlerRules:
    def test_collects_config_key_class_name_rules_and_claude_md(self) -> None:
        collected = collect_handler_rules([FixtureTwoRuleHandler])
        assert len(collected) == 1
        entry = collected[0]
        assert entry.class_name == "FixtureTwoRuleHandler"
        assert entry.config_key == "fixture_two_rule"
        assert entry.claude_md == "## two-rule-handler guidance"
        assert [rule.rule_id for rule in entry.rules] == ["R-TEST-ALPHA", "R-TEST-BETA"]

    def test_handler_with_no_rules_yields_empty_rules_tuple(self) -> None:
        collected = collect_handler_rules([FixtureNoRulesHandler])
        assert collected[0].rules == ()

    def test_broken_get_rules_is_skipped_not_raised(self) -> None:
        collected = collect_handler_rules([FixtureBrokenHandler, FixtureTwoRuleHandler])
        config_keys = {entry.config_key for entry in collected}
        assert "fixture_two_rule" in config_keys
        assert "fixture_broken" not in config_keys

    def test_sorted_by_config_key(self) -> None:
        collected = collect_handler_rules([FixtureTwoRuleHandler, FixtureNoRulesHandler])
        keys = [entry.config_key for entry in collected]
        assert keys == sorted(keys)


class TestFindRule:
    def test_finds_exact_id(self) -> None:
        collected = collect_handler_rules([FixtureTwoRuleHandler])
        found = find_rule(collected, "R-TEST-ALPHA")
        assert found is not None
        handler, rule = found
        assert handler.class_name == "FixtureTwoRuleHandler"
        assert rule.verbose == "Full alpha rationale text."

    def test_case_insensitive(self) -> None:
        collected = collect_handler_rules([FixtureTwoRuleHandler])
        found = find_rule(collected, "r-test-alpha")
        assert found is not None

    def test_tolerates_missing_r_prefix(self) -> None:
        collected = collect_handler_rules([FixtureTwoRuleHandler])
        found = find_rule(collected, "TEST-ALPHA")
        assert found is not None
        _, rule = found
        assert rule.rule_id == "R-TEST-ALPHA"

    def test_unknown_id_returns_none(self) -> None:
        collected = collect_handler_rules([FixtureTwoRuleHandler])
        assert find_rule(collected, "R-DOES-NOT-EXIST") is None


class TestNearRuleMatches:
    def test_suggests_close_spelling(self) -> None:
        collected = collect_handler_rules([FixtureTwoRuleHandler])
        suggestions = near_rule_matches(collected, "R-TEST-ALFA")
        assert "R-TEST-ALPHA" in suggestions

    def test_no_suggestions_for_wildly_different_input(self) -> None:
        collected = collect_handler_rules([FixtureTwoRuleHandler])
        suggestions = near_rule_matches(collected, "R-COMPLETELY-UNRELATED-ZZZZZ")
        assert suggestions == []


class TestFindHandler:
    def test_finds_by_config_key(self) -> None:
        collected = collect_handler_rules([FixtureTwoRuleHandler])
        found = find_handler(collected, "fixture_two_rule")
        assert found is not None
        assert found.class_name == "FixtureTwoRuleHandler"

    def test_finds_by_class_name_case_insensitively(self) -> None:
        collected = collect_handler_rules([FixtureTwoRuleHandler])
        found = find_handler(collected, "FixtureTwoRuleHandler".lower())
        assert found is not None
        assert found.class_name == "FixtureTwoRuleHandler"

    def test_unknown_handler_returns_none(self) -> None:
        collected = collect_handler_rules([FixtureTwoRuleHandler])
        assert find_handler(collected, "nonexistent_handler") is None


class TestNearHandlerMatches:
    def test_suggests_close_spelling(self) -> None:
        collected = collect_handler_rules([FixtureTwoRuleHandler])
        suggestions = near_handler_matches(collected, "fixture_two_rulee")
        assert "fixture_two_rule" in suggestions


class TestDiscoverHandlerRulesIntegration:
    """Integration test against the REAL handlers package (no fixtures)."""

    def test_finds_destructive_git_real_rules(self) -> None:
        collected = discover_handler_rules()
        handler = find_handler(collected, "destructive_git")
        assert handler is not None
        rule_ids = {rule.rule_id for rule in handler.rules}
        assert "R-GIT-RESET-HARD" in rule_ids

    def test_find_rule_returns_full_verbose_text_for_reset_hard(self) -> None:
        collected = discover_handler_rules()
        found = find_rule(collected, "R-GIT-RESET-HARD")
        assert found is not None
        handler, rule = found
        assert handler.config_key == "destructive_git"
        assert len(rule.verbose) > 0

    def test_returns_a_handler_rules_instance(self) -> None:
        collected = discover_handler_rules()
        assert all(isinstance(entry, HandlerRules) for entry in collected)
