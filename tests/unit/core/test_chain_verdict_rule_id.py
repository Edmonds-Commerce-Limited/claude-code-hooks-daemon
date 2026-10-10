"""The rule ID a handler's result carries reaches the verdict log (N393).

``HandlerVerdict.rule`` is read from ``HookResult.rule``; before this, nothing
set that field, so ``verdicts.jsonl`` held ``"rule": null`` on every record.
The ID comes from the result object or, when the result names none, from the
handler's declared rule when it declares exactly one -- never from the reason text.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.tags import HandlerTag
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.result_types import BlockingResult
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.daemon.verdict_log import append_verdicts


def _rule(rule_id: str) -> Rule:
    return Rule(rule_id=rule_id, blocked="b", why="w", fix="f", verbose="v")


class _Handler(Handler):
    def __init__(self, name: str, result: HookResult, rules: list[Rule]) -> None:
        super().__init__(name=name, priority=Priority.DEFAULT, terminal=False)
        self._result = result
        self._rules = rules

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return self._result

    def get_rules(self) -> list[Rule]:
        return self._rules

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        return []


def _decisions(handler: Handler) -> list[Any]:
    chain = HandlerChain()
    chain.add(handler)
    return chain.execute({"tool_name": "Bash"}).decisions


class TestUnderRuleSetsTheRuleField:
    def test_a_denial_filed_under_a_rule_carries_its_id(self) -> None:
        result = BlockingResult.deny("why").under_rule(_rule("R-TEST-ONE"))

        assert result.rule == "R-TEST-ONE"

    def test_an_allow_filed_under_a_rule_carries_none(self) -> None:
        result = BlockingResult(decision=Decision.ALLOW).under_rule(_rule("R-TEST-ONE"))

        assert result.rule is None


class TestChainRecordsTheRuleId:
    def test_a_rule_the_result_carries_is_recorded(self) -> None:
        result = HookResult(decision=Decision.DENY, reason="r", rule="R-FROM-RESULT")
        handler = _Handler("h", result, [_rule("R-A"), _rule("R-B")])

        assert _decisions(handler)[0].rule == "R-FROM-RESULT"

    def test_a_deny_from_a_single_rule_handler_records_that_rule(self) -> None:
        handler = _Handler("h", HookResult.deny(reason="r"), [_rule("R-ONLY")])

        assert _decisions(handler)[0].rule == "R-ONLY"

    def test_a_deny_from_a_multi_rule_handler_naming_none_records_none(self) -> None:
        handler = _Handler("h", HookResult.deny(reason="r"), [_rule("R-A"), _rule("R-B")])

        assert _decisions(handler)[0].rule is None

    def test_a_raising_rule_declaration_is_a_crash_with_no_half_recorded_match(self) -> None:
        class _Raising(_Handler):
            def get_rules(self) -> list[Rule]:
                raise RuntimeError("boom")

        handler = _Raising("h", HookResult.deny(reason="r"), [])
        handler.tags = [HandlerTag.SAFETY, HandlerTag.BLOCKING]
        chain = HandlerChain()
        chain.add(handler)

        executed = chain.execute({"tool_name": "Bash"})

        assert executed.result.decision == Decision.DENY
        assert executed.handlers_executed == ["h"]
        assert executed.decisions == []

    def test_an_allow_from_a_single_rule_handler_records_none(self) -> None:
        handler = _Handler("h", HookResult.allow(), [_rule("R-ONLY")])

        assert _decisions(handler)[0].rule is None


class TestVerdictLogLine:
    def test_a_deny_with_a_rule_id_ends_up_in_the_log_line(self, tmp_path: Path) -> None:
        handler = _Handler(
            "h",
            BlockingResult.deny("why").under_rule(_rule("R-LOGGED")),
            [_rule("R-A"), _rule("R-B")],
        )

        append_verdicts(
            enabled=True,
            decisions=_decisions(handler),
            hook_input={},
            event="UserPromptSubmit",
            tool_name="",
            session_id="s",
            log_dir=tmp_path,
            max_bytes=1_000_000,
        )

        line = json.loads((tmp_path / "verdicts.jsonl").read_text(encoding="utf-8"))
        assert line["rule"] == "R-LOGGED"
