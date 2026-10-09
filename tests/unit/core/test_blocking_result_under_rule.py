"""``BlockingResult.under_rule``: put a rule's ``BLOCKED [id]`` headline on a denial.

Plan 00484 G5. A handler whose deny reasons are built in several places files
them all under one rule by wrapping the verdict once, so every path prints the
identifier ``explain-rule`` resolves.
"""

from __future__ import annotations

from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.result_types import BlockingResult
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter

_RULE = Rule(
    rule_id="R-TEST-UNDER-RULE",
    blocked="a `thing`",
    why="why",
    fix="fix",
    verbose="verbose",
)


class TestUnderRule:
    def test_a_denial_gets_the_headline_above_its_own_reason(self) -> None:
        result = BlockingResult.deny("the specific reason").under_rule(_RULE)

        assert result.decision is Decision.DENY
        assert result.reason == f"{RuleFormatter().headline(_RULE)}\n\nthe specific reason"

    def test_an_allow_is_returned_unchanged(self) -> None:
        allowed = BlockingResult(decision=Decision.ALLOW)

        assert allowed.under_rule(_RULE) == allowed

    def test_the_context_survives(self) -> None:
        result = BlockingResult.deny("r", context=["note"]).under_rule(_RULE)

        assert result.context == ["note"]

    def test_the_original_is_not_mutated(self) -> None:
        original = BlockingResult.deny("r")
        original.under_rule(_RULE)

        assert original.reason == "r"
