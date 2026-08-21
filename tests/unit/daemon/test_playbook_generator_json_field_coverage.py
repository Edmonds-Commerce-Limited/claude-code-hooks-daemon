"""``generate_json`` must expose every field an ``AcceptanceTest`` declares.

The markdown renderer shows ``harness_cannot_produce`` as a SKIP block; the JSON
renderer silently dropped it. That asymmetry matters because a machine-driven
harness reads the JSON: a test the playbook tells a *human* to skip would be
executed by the harness anyway, fail, and be reported as a daemon defect. A
harness that reports false failures gets switched off — which is the risk this
plan exists to avoid.

Asserting the one missing key would have fixed the instance and left the class
of defect intact: the JSON dict is hand-built, so the NEXT field added to the
dataclass would be dropped exactly the same way, just as silently. The test
therefore derives the expectation from the dataclass, so adding a field to
``AcceptanceTest`` without exposing it fails here on the same commit.
"""

import dataclasses
from typing import Any

from claude_code_hooks_daemon.constants import Priority
from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult, TestType
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest as AcceptanceTestClass
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.daemon.playbook_generator import PlaybookGenerator
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

_SKIP_REASON = "Claude Code normalises this input before the daemon sees it"


class _UnproducibleHandler(Handler):
    """Declares one test the harness provably cannot produce."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="unproducible-fixture",
            priority=Priority.PLAN_WORKFLOW,
            terminal=False,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return [
            AcceptanceTest(
                title="Unproducible probe",
                command="echo unreachable",
                description="A test only a human in a real session can run",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"unreachable"],
                test_type=TestType.BLOCKING,
                harness_cannot_produce=_SKIP_REASON,
            ),
        ]


def _generator_with(handler: Handler) -> PlaybookGenerator:
    """A generator carrying exactly one project handler and nothing else."""
    return PlaybookGenerator(
        config={},
        registry=HandlerRegistry(),
        project_handlers=[handler],
    )


class TestJsonExposesEveryAcceptanceTestField:
    """The JSON payload is the harness's only view of a test."""

    def test_harness_cannot_produce_is_present_in_json(self) -> None:
        """A SKIP marker the markdown shows must not vanish from the JSON."""
        tests = _generator_with(_UnproducibleHandler()).generate_json()

        assert tests, "fixture handler produced no tests — the fixture is broken"
        assert tests[0].get("harness_cannot_produce") == _SKIP_REASON, (
            "the JSON playbook omits harness_cannot_produce, so a harness reading "
            "it cannot tell a must-skip test from an ordinary one"
        )

    def test_every_dataclass_field_appears_in_the_json_payload(self) -> None:
        """The property — no field of AcceptanceTest may be silently dropped.

        This is the guard that holds. The dict in ``generate_json`` is written
        out by hand, so nothing but this test connects it to the dataclass it
        claims to serialise.
        """
        tests = _generator_with(_UnproducibleHandler()).generate_json()

        declared = {field.name for field in dataclasses.fields(AcceptanceTestClass)}
        missing = sorted(declared - set(tests[0]))

        assert not missing, (
            f"AcceptanceTest field(s) {missing} are declared but never emitted by "
            "generate_json, so any harness reading the JSON cannot see them"
        )
