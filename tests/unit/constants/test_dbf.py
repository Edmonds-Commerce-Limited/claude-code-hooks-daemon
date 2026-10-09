"""Tests for the Defence Before Fix constants."""

from __future__ import annotations

import re

from claude_code_hooks_daemon.constants.dbf import DefectClass, DefenceBeforeFix


def _defect_class_values() -> dict[str, str]:
    return {
        name: value
        for name, value in vars(DefectClass).items()
        if not name.startswith("_") and isinstance(value, str)
    }


class TestDefenceBeforeFix:
    def test_url_is_the_published_home(self) -> None:
        assert DefenceBeforeFix.URL == "https://defence-before-fix.github.io"

    def test_explain_line_is_one_line_naming_the_method_and_link(self) -> None:
        assert "\n" not in DefenceBeforeFix.EXPLAIN_LINE
        assert "Defence Before Fix" in DefenceBeforeFix.EXPLAIN_LINE
        assert DefenceBeforeFix.URL in DefenceBeforeFix.EXPLAIN_LINE

    def test_explain_line_does_not_call_every_rule_a_defence(self) -> None:
        """Owner ruling C1: the action guards are outside the Defence set."""
        assert "is a defence" not in DefenceBeforeFix.EXPLAIN_LINE.lower()

    def test_guardrail_line_says_it_is_outside_the_defence_set(self) -> None:
        assert "\n" not in DefenceBeforeFix.GUARDRAIL_LINE
        assert "guardrail" in DefenceBeforeFix.GUARDRAIL_LINE.lower()
        assert "not a defence" in DefenceBeforeFix.GUARDRAIL_LINE.lower()

    def test_defence_line_names_the_defect_class(self) -> None:
        line = DefenceBeforeFix.defence_line("error-hiding")
        assert "error-hiding" in line
        assert "\n" not in line


class TestDefectClass:
    def test_values_are_unique_kebab_case(self) -> None:
        values = list(_defect_class_values().values())
        assert values
        assert len(values) == len(set(values))
        assert all(re.fullmatch(r"[a-z]+(-[a-z]+)*", value) for value in values)
