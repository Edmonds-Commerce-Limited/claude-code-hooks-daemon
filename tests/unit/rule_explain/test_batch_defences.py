"""Batch-check rows of the defence enumeration (Plan 00484 batch 3.1e).

A batch checker that is the whole-tree form of a write-time handler is listed
beside the handler rows, marked with ``kind``. Membership, the handler each
checker mirrors and the rule IDs come from ``scripts/qa/qa-rules.json``; the
defect class is the one the ACTIVE handler's own row carries.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.constants.dbf import DefectClass
from claude_code_hooks_daemon.rule_explain.defences import (
    KIND_BATCH_CHECK,
    KIND_HANDLER,
    Defence,
    collect_batch_defences,
)

_DOCUMENT: dict[str, Any] = {
    "docs": "CLAUDE/QA.md",
    "batch_defences": {
        "check_a.py": {"step": "a_step", "handler": "handler_a"},
        "check_b.py": {"step": "b_step", "handler": "handler_b"},
    },
    "rules": {
        "rule-one": {"statement": "One.", "fix": "f", "checks": ["check_a.py"]},
        "rule-two": {"statement": "Two.", "fix": "f", "checks": ["check_a.py", "other.py"]},
        "rule-three": {"statement": "Three.", "fix": "f", "checks": ["check_b.py"]},
        "plumbing": {"statement": "P.", "fix": "f", "checks": ["check_b.py"], "meta": True},
        "unrelated": {"statement": "Nope.", "fix": "f", "checks": ["other.py"]},
    },
}
_ACTIVE: dict[str, DefectClass] = {
    "handler_a": DefectClass.QA_SUPPRESSION,
    "handler_b": DefectClass.ERROR_HIDING,
}


class TestCollectBatchDefences:
    def test_one_row_per_rule_each_declared_check_prints(self) -> None:
        records = collect_batch_defences(_DOCUMENT, _ACTIVE)
        assert [record.rule_id for record in records] == ["rule-one", "rule-two", "rule-three"]

    def test_checker_plumbing_rules_are_not_rows(self) -> None:
        records = collect_batch_defences(_DOCUMENT, _ACTIVE)
        assert "plumbing" not in {record.rule_id for record in records}

    def test_rows_are_marked_as_batch_checks(self) -> None:
        records = collect_batch_defences(_DOCUMENT, _ACTIVE)
        assert {record.kind for record in records} == {KIND_BATCH_CHECK}

    def test_handler_rows_default_to_the_handler_kind(self) -> None:
        record = Defence(
            rule_id=None,
            handler="h",
            handler_class="H",
            event="pre_tool_use",
            priority=1,
            behavior="BLOCKING",
            statement=None,
            defect_class=DefectClass.PLAN_DRIFT,
            docs="d",
            detector_entry_point=None,
        )
        assert record.kind == KIND_HANDLER

    def test_row_takes_its_defect_class_from_the_active_handler(self) -> None:
        records = collect_batch_defences(_DOCUMENT, _ACTIVE)
        assert records[0].defect_class is DefectClass.QA_SUPPRESSION
        record = records[2]
        assert record.defect_class is DefectClass.ERROR_HIDING
        assert record.statement == "Three."
        assert record.handler == "b_step"
        assert record.handler_class == "check_b.py"
        assert record.docs == "./scripts/qa/llm_qa.py --explain rule-three"
        assert record.detector_entry_point == "./scripts/qa/llm_qa.py b_step"

    def test_a_disabled_or_absent_handler_removes_its_batch_rows(self) -> None:
        records = collect_batch_defences(_DOCUMENT, {"handler_b": DefectClass.ERROR_HIDING})
        assert {record.handler_class for record in records} == {"check_b.py"}
        assert collect_batch_defences(_DOCUMENT, {}) == []

    def test_a_document_without_batch_defences_yields_no_rows(self) -> None:
        assert collect_batch_defences({"rules": {}}, _ACTIVE) == []

    def test_a_declared_check_that_prints_no_rule_fails_fast(self) -> None:
        document = {
            "batch_defences": {"check_a.py": {"step": "s", "handler": "handler_a"}},
            "rules": {"x": {"statement": "s", "fix": "f", "checks": ["other.py"]}},
        }
        with pytest.raises(ValueError, match="check_a.py"):
            collect_batch_defences(document, _ACTIVE)

    def test_a_declared_check_that_prints_only_plumbing_rules_fails_fast(self) -> None:
        document = {
            "batch_defences": {"check_a.py": {"step": "s", "handler": "handler_a"}},
            "rules": {"x": {"statement": "s", "fix": "f", "checks": ["check_a.py"], "meta": True}},
        }
        with pytest.raises(ValueError, match="check_a.py"):
            collect_batch_defences(document, _ACTIVE)
