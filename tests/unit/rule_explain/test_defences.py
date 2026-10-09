"""Tests for the machine-readable defence enumeration (Plan 00484 Task 3.2, 3.1a).

Owner ruling C1: the action guards are outside the Defence set; the content and
commit gates are the set. A handler is in the set exactly when it declares a
``defect_class``, so that property is also the ``defect_class`` column.
"""

from __future__ import annotations

from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.daemon.docs_generator import CollectedHandler
from claude_code_hooks_daemon.rule_explain.defences import (
    Defence,
    collect_active_defences,
)
from claude_code_hooks_daemon.rule_explain.lookup import HandlerRules

_CLASS = "some-defect-class"


def _rule(rule_id: str, blocked: str = "`thing`") -> Rule:
    return Rule(rule_id=rule_id, blocked=blocked, why="why", fix="fix", verbose="verbose")


def _handler_rules(
    class_name: str, config_key: str, *rules: Rule, defect_class: str | None = _CLASS
) -> HandlerRules:
    return HandlerRules(
        config_key=config_key,
        class_name=class_name,
        rules=tuple(rules),
        claude_md=None,
        defect_class=defect_class,
    )


def _collected(
    class_name: str,
    config_key: str,
    event: str = "pre_tool_use",
    priority: int = 10,
    behavior: str = "BLOCKING",
) -> CollectedHandler:
    return (class_name, config_key, event, priority, behavior, "desc", True)


class TestCollectActiveDefences:
    def test_one_record_per_rule_of_an_active_handler(self) -> None:
        handlers = [_handler_rules("AHandler", "a", _rule("R-A-ONE"), _rule("R-A-TWO"))]
        records = collect_active_defences([_collected("AHandler", "a")], handlers)
        assert [record.rule_id for record in records] == ["R-A-ONE", "R-A-TWO"]

    def test_record_carries_handler_event_statement_and_docs_route(self) -> None:
        handlers = [_handler_rules("AHandler", "a", _rule("R-A-ONE", blocked="`git x`"))]
        (record,) = collect_active_defences(
            [_collected("AHandler", "a", event="pre_tool_use", priority=7)], handlers
        )
        assert record.handler == "a"
        assert record.handler_class == "AHandler"
        assert record.event == "pre_tool_use"
        assert record.priority == 7
        assert record.statement == "`git x`"
        assert record.docs == "hooks-daemon explain-rule R-A-ONE"
        assert record.detector_entry_point == "hooks-daemon probe pre_tool_use --json <payload>"

    def test_defect_class_is_the_handlers_declared_class(self) -> None:
        handlers = [_handler_rules("AHandler", "a", _rule("R-A-ONE"), defect_class="error-hiding")]
        (record,) = collect_active_defences([_collected("AHandler", "a")], handlers)
        assert record.defect_class == "error-hiding"
        assert record.to_dict()["defect_class"] == "error-hiding"

    def test_action_guard_is_not_a_defence(self) -> None:
        handlers = [_handler_rules("GuardHandler", "guard", _rule("R-G-ONE"), defect_class=None)]
        assert collect_active_defences([_collected("GuardHandler", "guard")], handlers) == []

    def test_inactive_handler_is_not_listed(self) -> None:
        handlers = [
            _handler_rules("AHandler", "a", _rule("R-A-ONE")),
            _handler_rules("BHandler", "b", _rule("R-B-ONE")),
        ]
        records = collect_active_defences([_collected("BHandler", "b")], handlers)
        assert [record.rule_id for record in records] == ["R-B-ONE"]

    def test_blocking_defence_without_rules_is_listed_with_null_rule_id(self) -> None:
        handlers = [_handler_rules("ProjHandler", "proj_handler")]
        (record,) = collect_active_defences([_collected("ProjHandler", "proj_handler")], handlers)
        assert record.rule_id is None
        assert record.statement is None
        assert record.defect_class == _CLASS
        assert record.docs == "hooks-daemon explain-handler proj_handler"

    def test_advisory_handler_without_rules_is_not_a_defence(self) -> None:
        handlers = [_handler_rules("AdvHandler", "adv")]
        records = collect_active_defences(
            [_collected("AdvHandler", "adv", behavior="ADVISORY")], handlers
        )
        assert records == []

    def test_active_handler_unknown_to_the_rule_index_declares_no_class_so_is_not_listed(
        self,
    ) -> None:
        assert collect_active_defences([_collected("PluginHandler", "PluginHandler")], []) == []

    def test_output_is_ordered_by_event_priority_then_handler(self) -> None:
        handlers = [
            _handler_rules("AHandler", "a", _rule("R-A")),
            _handler_rules("BHandler", "b", _rule("R-B")),
            _handler_rules("CHandler", "c", _rule("R-C")),
        ]
        active = [
            _collected("CHandler", "c", event="stop", priority=1),
            _collected("BHandler", "b", priority=20),
            _collected("AHandler", "a", priority=20),
        ]
        records = collect_active_defences(active, handlers)
        assert [record.rule_id for record in records] == ["R-A", "R-B", "R-C"]

    def test_to_dict_has_exactly_the_documented_keys(self) -> None:
        record = Defence(
            rule_id="R-X",
            handler="x",
            handler_class="XHandler",
            event="stop",
            priority=1,
            behavior="BLOCKING",
            statement="s",
            defect_class="c",
            docs="d",
            detector_entry_point="e",
        )
        assert set(record.to_dict()) == {
            "rule_id",
            "handler",
            "handler_class",
            "event",
            "priority",
            "behavior",
            "statement",
            "defect_class",
            "docs",
            "detector_entry_point",
        }
