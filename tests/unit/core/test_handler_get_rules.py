"""Tests for Handler.get_rules() — Phase 2 of Plan 00116.

Design contract (Task 2.2 from PLAN.md):
  - Handler base class has get_rules() -> list[Rule] method
  - Default implementation returns []
  - Legacy handlers that don't override get_rules() degrade gracefully
  - The method is NOT abstract (so existing handlers don't break)
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.rule import Rule


# ---------------------------------------------------------------------------
# Concrete test handlers
# ---------------------------------------------------------------------------


class _LegacyHandler(Handler):
    """Handler that does NOT override get_rules() — simulates legacy handlers."""

    def __init__(self) -> None:
        super().__init__(name="legacy-handler", priority=50)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        return []


class _RuleAwareHandler(Handler):
    """Handler that overrides get_rules() with actual Rule objects."""

    def __init__(self) -> None:
        super().__init__(name="rule-aware-handler", priority=50)
        self._rules = [
            Rule(
                rule_id="R-TEST-RULE-ONE",
                blocked="`dangerous command`",
                why="Causes data loss",
                fix="Use safe-command instead",
                verbose="Full explanation of why dangerous-command is blocked.",
            ),
            Rule(
                rule_id="R-TEST-RULE-TWO",
                blocked="`another bad thing`",
                why="Security risk",
                fix="Don't do that",
                verbose="Full explanation of the security risk.",
            ),
        ]

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        return "## rule-aware-handler guidance"

    def get_acceptance_tests(self) -> list[Any]:
        return []

    def get_rules(self) -> list[Rule]:
        """Override to return real rules."""
        return list(self._rules)


# ---------------------------------------------------------------------------
# Tests for default get_rules() behaviour
# ---------------------------------------------------------------------------


class TestHandlerGetRulesDefault:
    """Handler.get_rules() has a default implementation returning []."""

    @pytest.fixture()
    def legacy_handler(self) -> _LegacyHandler:
        return _LegacyHandler()

    def test_get_rules_method_exists_on_base(self) -> None:
        """Handler base class has get_rules method."""
        assert hasattr(Handler, "get_rules")
        assert callable(Handler.get_rules)

    def test_legacy_handler_has_get_rules(self, legacy_handler: _LegacyHandler) -> None:
        """Legacy handler (no override) has get_rules attribute."""
        assert hasattr(legacy_handler, "get_rules")

    def test_legacy_handler_get_rules_returns_list(
        self, legacy_handler: _LegacyHandler
    ) -> None:
        """Legacy handler's get_rules() returns a list."""
        result = legacy_handler.get_rules()
        assert isinstance(result, list)

    def test_legacy_handler_get_rules_returns_empty_list(
        self, legacy_handler: _LegacyHandler
    ) -> None:
        """Legacy handler's get_rules() returns empty list (graceful degradation)."""
        result = legacy_handler.get_rules()
        assert result == []

    def test_get_rules_not_abstract(self) -> None:
        """get_rules() is NOT abstract — legacy handlers must not be forced to implement it."""
        # _LegacyHandler does not override get_rules() and can still be instantiated
        handler = _LegacyHandler()
        assert handler is not None

    def test_get_rules_default_does_not_raise(self, legacy_handler: _LegacyHandler) -> None:
        """Calling get_rules() on a legacy handler does not raise."""
        result = legacy_handler.get_rules()
        assert result is not None


# ---------------------------------------------------------------------------
# Tests for overriding get_rules()
# ---------------------------------------------------------------------------


class TestHandlerGetRulesOverride:
    """Handler subclasses can override get_rules() to return Rule objects."""

    @pytest.fixture()
    def rule_aware_handler(self) -> _RuleAwareHandler:
        return _RuleAwareHandler()

    def test_override_returns_list(self, rule_aware_handler: _RuleAwareHandler) -> None:
        """Overriding get_rules() can return a non-empty list."""
        result = rule_aware_handler.get_rules()
        assert isinstance(result, list)
        assert len(result) > 0

    def test_override_returns_rule_objects(self, rule_aware_handler: _RuleAwareHandler) -> None:
        """Each item returned by get_rules() is a Rule instance."""
        result = rule_aware_handler.get_rules()
        for item in result:
            assert isinstance(item, Rule), f"Expected Rule, got {type(item)}"

    def test_override_rule_ids_are_strings(self, rule_aware_handler: _RuleAwareHandler) -> None:
        """Each Rule in the list has a non-empty string rule_id."""
        for rule in rule_aware_handler.get_rules():
            assert isinstance(rule.rule_id, str)
            assert len(rule.rule_id) > 0

    def test_override_returns_correct_rules(
        self, rule_aware_handler: _RuleAwareHandler
    ) -> None:
        """The rules returned match what was configured."""
        rules = rule_aware_handler.get_rules()
        rule_ids = {r.rule_id for r in rules}
        assert "R-TEST-RULE-ONE" in rule_ids
        assert "R-TEST-RULE-TWO" in rule_ids

    def test_get_rules_returns_copy(self, rule_aware_handler: _RuleAwareHandler) -> None:
        """get_rules() returns a fresh list each call (not shared mutable state)."""
        rules_a = rule_aware_handler.get_rules()
        rules_b = rule_aware_handler.get_rules()
        assert rules_a is not rules_b  # Different list objects
        assert rules_a == rules_b  # But same content


# ---------------------------------------------------------------------------
# Tests for type annotation correctness
# ---------------------------------------------------------------------------


class TestHandlerGetRulesTypeAnnotation:
    """get_rules() has the correct return type annotation."""

    def test_get_rules_annotation_returns_list_of_rule(self) -> None:
        """Handler.get_rules is annotated as returning list[Rule]."""
        import inspect

        hints = {}
        try:
            hints = Handler.get_rules.__annotations__
        except AttributeError:
            # No annotations — check via inspect
            try:
                sig = inspect.signature(Handler.get_rules)
                ret = sig.return_annotation
                if ret is not inspect.Parameter.empty:
                    hints["return"] = ret
            except (ValueError, TypeError):
                pass

        # The return annotation should mention 'Rule' or 'list'
        return_hint = str(hints.get("return", ""))
        assert "Rule" in return_hint or "list" in return_hint, (
            f"get_rules() return annotation does not mention Rule or list: {return_hint!r}"
        )
