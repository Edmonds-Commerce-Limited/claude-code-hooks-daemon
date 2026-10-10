"""Batch-check rows of the defence enumeration (Plan 00484 batch 3.1e).

A batch checker that is the whole-tree form of a write-time handler is listed
beside the handler rows, marked with ``kind``. Membership and the rule IDs both
come from ``scripts/qa/qa-rules.json``; nothing is declared a second time here.
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
        "check_a.py": {"step": "a_step", "defect_class": "qa-suppression", "path_form": True},
        "check_b.py": {"step": "b_step", "defect_class": "error-hiding"},
    },
    "rules": {
        "rule-one": {"statement": "One.", "fix": "f", "checks": ["check_a.py"]},
        "rule-two": {"statement": "Two.", "fix": "f", "checks": ["check_a.py", "other.py"]},
        "rule-three": {"statement": "Three.", "fix": "f", "checks": ["check_b.py"]},
        "unrelated": {"statement": "Nope.", "fix": "f", "checks": ["other.py"]},
    },
}


class TestCollectBatchDefences:
    def test_one_row_per_rule_each_declared_check_prints(self) -> None:
        records = collect_batch_defences(_DOCUMENT)
        assert [record.rule_id for record in records] == ["rule-one", "rule-two", "rule-three"]

    def test_rows_are_marked_as_batch_checks(self) -> None:
        assert {record.kind for record in collect_batch_defences(_DOCUMENT)} == {KIND_BATCH_CHECK}

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

    def test_row_carries_defect_class_statement_docs_and_step_entry_point(self) -> None:
        record = collect_batch_defences(_DOCUMENT)[2]
        assert record.defect_class is DefectClass.ERROR_HIDING
        assert record.statement == "Three."
        assert record.handler == "b_step"
        assert record.handler_class == "check_b.py"
        assert record.docs == "./scripts/qa/llm_qa.py --explain rule-three"
        assert record.detector_entry_point == "./scripts/qa/llm_qa.py b_step"

    def test_a_check_with_a_path_form_names_it_as_the_entry_point(self) -> None:
        record = collect_batch_defences(_DOCUMENT)[0]
        assert record.detector_entry_point == "./scripts/qa/check_a.py --path <file>"

    def test_a_document_without_batch_defences_yields_no_rows(self) -> None:
        assert collect_batch_defences({"rules": {}}) == []

    def test_an_unknown_defect_class_fails_fast(self) -> None:
        document = {
            "batch_defences": {"check_a.py": {"step": "s", "defect_class": "made-up"}},
            "rules": {},
        }
        with pytest.raises(ValueError):
            collect_batch_defences(document)

    def test_a_declared_check_that_prints_no_rule_fails_fast(self) -> None:
        document = {
            "batch_defences": {"check_a.py": {"step": "s", "defect_class": "qa-suppression"}},
            "rules": {"x": {"statement": "s", "fix": "f", "checks": ["other.py"]}},
        }
        with pytest.raises(ValueError, match="check_a.py"):
            collect_batch_defences(document)
