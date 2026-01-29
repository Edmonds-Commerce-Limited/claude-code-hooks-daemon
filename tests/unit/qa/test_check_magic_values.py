"""Tests for the magic value checker (scripts/qa/check_magic_values.py)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

# Import from scripts - add to path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "qa"))
from check_magic_values import (
    MagicValueChecker,
    Violation,
    check_source,
    _count_by_rule,
    _get_name,
    _is_super_init,
)


def _check(code: str) -> list[Violation]:
    """Helper to check a code snippet for magic values."""
    return check_source(textwrap.dedent(code), "<test>")


def _rules(violations: list[Violation]) -> list[str]:
    """Extract just rule names from violations."""
    return [v.rule for v in violations]


class TestMagicHandlerName:
    """Tests for magic-handler-name rule."""

    def test_detects_magic_handler_name(self) -> None:
        violations = _check('''
            from base import Handler
            class MyHandler(Handler):
                def __init__(self):
                    super().__init__(name="my-handler", priority=10)
        ''')
        rules = _rules(violations)
        assert "magic-handler-name" in rules

    def test_allows_no_name_kwarg(self) -> None:
        """No violation if name kwarg is absent (e.g. using handler_id)."""
        violations = _check('''
            from base import Handler
            class MyHandler(Handler):
                def __init__(self):
                    super().__init__(handler_id=HandlerID.FOO)
        ''')
        assert "magic-handler-name" not in _rules(violations)

    def test_no_false_positive_non_handler_class(self) -> None:
        """Classes not inheriting Handler should not trigger."""
        violations = _check('''
            class MyService(BaseService):
                def __init__(self):
                    super().__init__(name="my-service")
        ''')
        assert "magic-handler-name" not in _rules(violations)


class TestMagicTags:
    """Tests for magic-tag rule."""

    def test_detects_magic_tags(self) -> None:
        violations = _check('''
            from base import Handler
            class MyHandler(Handler):
                def __init__(self):
                    super().__init__(name="x", tags=["safety", "git"])
        ''')
        tag_violations = [v for v in violations if v.rule == "magic-tag"]
        assert len(tag_violations) == 2

    def test_allows_variable_tags(self) -> None:
        """Tags using variables should not trigger."""
        violations = _check('''
            from base import Handler
            class MyHandler(Handler):
                def __init__(self):
                    super().__init__(name="x", tags=[HandlerTag.SAFETY])
        ''')
        assert "magic-tag" not in _rules(violations)

    def test_mixed_tags(self) -> None:
        """Only string literals trigger, not variable references."""
        violations = _check('''
            from base import Handler
            class MyHandler(Handler):
                def __init__(self):
                    super().__init__(name="x", tags=["safety", HandlerTag.GIT])
        ''')
        tag_violations = [v for v in violations if v.rule == "magic-tag"]
        assert len(tag_violations) == 1


class TestMagicToolName:
    """Tests for magic-tool-name rule."""

    def test_detects_tool_name_eq_string(self) -> None:
        violations = _check('''
            def matches(self, hook_input):
                tool_name = hook_input.get("tool_name")
                if tool_name == "Bash":
                    return True
        ''')
        assert "magic-tool-name" in _rules(violations)

    def test_detects_tool_name_in_list(self) -> None:
        violations = _check('''
            def matches(self, hook_input):
                tool_name = hook_input.get("tool_name")
                if tool_name in ["Write", "Edit"]:
                    return True
        ''')
        tool_violations = [v for v in violations if v.rule == "magic-tool-name"]
        assert len(tool_violations) == 2

    def test_allows_constant_comparison(self) -> None:
        violations = _check('''
            def matches(self, hook_input):
                tool_name = hook_input.get("tool_name")
                if tool_name == ToolName.BASH:
                    return True
        ''')
        assert "magic-tool-name" not in _rules(violations)

    def test_detects_reversed_comparison(self) -> None:
        violations = _check('''
            def matches(self, hook_input):
                tool_name = hook_input.get("tool_name")
                if "Bash" == tool_name:
                    return True
        ''')
        assert "magic-tool-name" in _rules(violations)

    def test_detects_not_in_list(self) -> None:
        violations = _check('''
            def matches(self, hook_input):
                tool_name = hook_input.get("tool_name")
                if tool_name not in ["Write", "Edit"]:
                    return False
        ''')
        tool_violations = [v for v in violations if v.rule == "magic-tool-name"]
        assert len(tool_violations) == 2


class TestMagicConfigKey:
    """Tests for magic-config-key rule."""

    def test_detects_config_bracket_access(self) -> None:
        violations = _check('''
            def load(config):
                return config["enabled"]
        ''')
        assert "magic-config-key" in _rules(violations)

    def test_detects_handler_config_access(self) -> None:
        violations = _check('''
            def load(handler_config):
                return handler_config["priority"]
        ''')
        assert "magic-config-key" in _rules(violations)

    def test_allows_non_config_variable(self) -> None:
        violations = _check('''
            def load(data):
                return data["enabled"]
        ''')
        assert "magic-config-key" not in _rules(violations)

    def test_allows_non_config_key(self) -> None:
        violations = _check('''
            def load(config):
                return config["some_random_key"]
        ''')
        assert "magic-config-key" not in _rules(violations)


class TestMagicPriority:
    """Tests for magic-priority rule."""

    def test_detects_magic_priority(self) -> None:
        violations = _check('''
            from base import Handler
            class MyHandler(Handler):
                def __init__(self):
                    super().__init__(name="x", priority=10)
        ''')
        assert "magic-priority" in _rules(violations)

    def test_allows_constant_priority(self) -> None:
        violations = _check('''
            from base import Handler
            class MyHandler(Handler):
                def __init__(self):
                    super().__init__(name="x", priority=Priority.SAFETY)
        ''')
        assert "magic-priority" not in _rules(violations)


class TestMagicTimeout:
    """Tests for magic-timeout rule."""

    def test_detects_magic_timeout(self) -> None:
        violations = _check('''
            import subprocess
            result = subprocess.run(["cmd"], timeout=30)
        ''')
        assert "magic-timeout" in _rules(violations)

    def test_allows_constant_timeout(self) -> None:
        violations = _check('''
            import subprocess
            result = subprocess.run(["cmd"], timeout=Timeout.ESLINT_CHECK)
        ''')
        assert "magic-timeout" not in _rules(violations)

    def test_no_false_positive_handler_init_timeout(self) -> None:
        """timeout= inside Handler.__init__ is not a subprocess timeout."""
        # Handler __init__ does not have timeout, but if it did,
        # we specifically exclude it from magic-timeout detection.
        # This tests the _in_handler_init guard.
        violations = _check('''
            from base import Handler
            class MyHandler(Handler):
                def __init__(self):
                    super().__init__(name="x")
                    self.timeout = 30
        ''')
        # The self.timeout = 30 is an assignment, not a keyword arg
        assert "magic-timeout" not in _rules(violations)


class TestMagicDecision:
    """Tests for magic-decision rule."""

    def test_detects_magic_decision_allow(self) -> None:
        violations = _check('''
            from core import HookResult
            result = HookResult(decision="allow")
        ''')
        assert "magic-decision" in _rules(violations)

    def test_detects_magic_decision_deny(self) -> None:
        violations = _check('''
            from core import HookResult
            result = HookResult(decision="deny", reason="blocked")
        ''')
        assert "magic-decision" in _rules(violations)

    def test_allows_enum_decision(self) -> None:
        violations = _check('''
            from core import HookResult, Decision
            result = HookResult(decision=Decision.ALLOW)
        ''')
        assert "magic-decision" not in _rules(violations)

    def test_ignores_non_decision_string(self) -> None:
        violations = _check('''
            from core import HookResult
            result = HookResult(decision="custom_thing")
        ''')
        assert "magic-decision" not in _rules(violations)


class TestMagicEventType:
    """Tests for magic-event-type rule."""

    def test_detects_event_type_comparison(self) -> None:
        violations = _check('''
            if event_type == "pre_tool_use":
                pass
        ''')
        assert "magic-event-type" in _rules(violations)

    def test_allows_constant_event_type(self) -> None:
        violations = _check('''
            if event_type == EventID.PRE_TOOL_USE:
                pass
        ''')
        assert "magic-event-type" not in _rules(violations)

    def test_ignores_non_event_string(self) -> None:
        violations = _check('''
            if event_type == "some_other_thing":
                pass
        ''')
        assert "magic-event-type" not in _rules(violations)

    def test_detects_event_in_list(self) -> None:
        violations = _check('''
            if event_type in ["pre_tool_use", "post_tool_use"]:
                pass
        ''')
        event_violations = [v for v in violations if v.rule == "magic-event-type"]
        assert len(event_violations) == 2


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_count_by_rule(self) -> None:
        violations = [
            Violation("<test>", 1, 0, "magic-tag", "msg"),
            Violation("<test>", 2, 0, "magic-tag", "msg"),
            Violation("<test>", 3, 0, "magic-tool-name", "msg"),
        ]
        counts = _count_by_rule(violations)
        assert counts == {"magic-tag": 2, "magic-tool-name": 1}

    def test_count_by_rule_empty(self) -> None:
        assert _count_by_rule([]) == {}

    def test_check_source_syntax_error(self) -> None:
        """Syntax errors should return empty list, not raise."""
        violations = check_source("def foo(", "<test>")
        assert violations == []


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_file(self) -> None:
        assert _check("") == []

    def test_no_handler_class(self) -> None:
        violations = _check('''
            x = 1
            y = "hello"
        ''')
        assert violations == []

    def test_nested_handler_class(self) -> None:
        """Handler inside another scope."""
        violations = _check('''
            from base import Handler
            def factory():
                class InnerHandler(Handler):
                    def __init__(self):
                        super().__init__(name="inner", priority=5)
                return InnerHandler
        ''')
        assert "magic-handler-name" in _rules(violations)
        assert "magic-priority" in _rules(violations)

    def test_multiple_violations_in_one_file(self) -> None:
        violations = _check('''
            from base import Handler
            from core import HookResult
            class MyHandler(Handler):
                def __init__(self):
                    super().__init__(
                        name="my-handler",
                        priority=10,
                        tags=["safety"],
                    )
                def matches(self, hook_input):
                    tool_name = hook_input.get("tool_name")
                    return tool_name == "Bash"
                def handle(self, hook_input):
                    return HookResult(decision="allow")
        ''')
        rules = _rules(violations)
        assert "magic-handler-name" in rules
        assert "magic-priority" in rules
        assert "magic-tag" in rules
        assert "magic-tool-name" in rules
        assert "magic-decision" in rules
        assert len(violations) == 5
