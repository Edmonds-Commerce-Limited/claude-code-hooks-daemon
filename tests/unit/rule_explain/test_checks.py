"""Tests for the plan-QA / docs-QA check lookup (Plan 00484 G15).

A deny reason from ``plan_qa_edit``, ``plan_qa_commit_gate``, ``docs_qa_edit`` or
``docs_qa_commit_gate`` names a ``CHECK_ID`` (for example ``plan-doc-size``), not
the umbrella rule ID. These tests pin that every such ID resolves to its umbrella
rule through the same lookup ``explain-rule`` uses, and that no ``CHECK_ID``
constant in either check package can be added without being resolvable.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.daemon.cli import cmd_explain_rule
from claude_code_hooks_daemon.rule_explain.checks import (
    collect_check_entries,
    find_check,
    near_check_matches,
)

_CHECK_ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _rule_args(**overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {
        "rule_id": None,
        "list_rules": False,
        "project_root": Path(__file__).resolve().parents[3],
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class TestCheckLookup:
    def test_discovery_is_not_vacuous(self) -> None:
        assert len(collect_check_entries()) > 40

    def test_plan_doc_size_resolves_to_the_plan_edit_umbrella(self) -> None:
        entry = find_check(collect_check_entries(), "plan-doc-size")
        assert entry is not None
        assert entry.umbrella_rule_ids == (RuleID.PLAN_QA_EDIT,)
        assert entry.statement

    def test_a_check_in_both_gates_names_both_umbrella_rules(self) -> None:
        entry = find_check(collect_check_entries(), "header-body-coherence")
        assert entry is not None
        assert entry.umbrella_rule_ids == (RuleID.PLAN_QA_EDIT, RuleID.PLAN_QA_COMMIT)

    def test_a_docs_check_resolves_to_the_docs_umbrellas(self) -> None:
        entry = find_check(collect_check_entries(), "pointer-resolves")
        assert entry is not None
        assert entry.umbrella_rule_ids == (RuleID.DOCS_QA_EDIT, RuleID.DOCS_QA_COMMIT)

    def test_a_sweep_only_check_resolves_with_no_umbrella_rule(self) -> None:
        entry = find_check(collect_check_entries(), "staleness-nag")
        assert entry is not None
        assert entry.umbrella_rule_ids == ()

    def test_lookup_is_case_tolerant(self) -> None:
        assert find_check(collect_check_entries(), " Plan-Doc-Size ") is not None

    def test_unknown_id_is_none_and_has_near_matches(self) -> None:
        entries = collect_check_entries()
        assert find_check(entries, "plan-doc-sizes") is None
        assert "plan-doc-size" in near_check_matches(entries, "plan-doc-sizes")

    def test_ids_are_unique_and_well_formed(self) -> None:
        ids = [entry.check_id for entry in collect_check_entries()]
        assert len(ids) == len(set(ids))
        assert all(_CHECK_ID_PATTERN.match(check_id) for check_id in ids)


class TestEveryRegisteredCheckExplainsItself:
    """The release guard over the ``CHECK_ID`` constants lives in ``tests/unit/test_rule_parity.py``."""

    def test_every_registered_check_has_a_statement(self) -> None:
        missing = [entry.check_id for entry in collect_check_entries() if not entry.statement]
        assert not missing, f"checks with no statement to print: {missing}"


class TestExplainRuleResolvesACheckId:
    def test_check_id_prints_statement_and_umbrella_rule(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cmd_explain_rule(_rule_args(rule_id="plan-doc-size")) == 0
        out = capsys.readouterr().out
        assert "Check: plan-doc-size" in out
        assert RuleID.PLAN_QA_EDIT in out
        assert "explain-rule R-PLAN-QA-EDIT" in out

    def test_unknown_check_id_still_exits_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cmd_explain_rule(_rule_args(rule_id="no-such-check-zzz")) == 1
        assert "unknown rule ID" in capsys.readouterr().err
