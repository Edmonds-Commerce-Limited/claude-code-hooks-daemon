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

from claude_code_hooks_daemon.constants import Priority, ToolName
from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult, TestType
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest as AcceptanceTestClass
from claude_code_hooks_daemon.core.acceptance_test import ToolPayload
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


_PAYLOAD_PATH = "/repo/probe.py"
_PAYLOAD_PROSE = f"Use the Write tool to create {_PAYLOAD_PATH} with a guarded annotation"


class _DeclaredPayloadHandler(Handler):
    """Declares one test whose `command` is prose and whose payload is stated."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="declared-payload-fixture",
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
                title="Declared payload probe",
                command=_PAYLOAD_PROSE,
                description="A test a harness must dispatch as a Write, not as bash",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"blocked"],
                test_type=TestType.BLOCKING,
                tool_payload=ToolPayload(
                    tool_name=ToolName.WRITE,
                    tool_input={"file_path": _PAYLOAD_PATH, "content": "x = 1\n"},
                ),
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

    def test_tool_payload_is_emitted_as_the_hook_events_own_field_names(self) -> None:
        """The harness copies these into its probe rather than rebuilding them.

        Naming them `tool_name`/`tool_input` is the point: a harness that has
        to translate is a harness that can translate wrongly, which is exactly
        how the prototype turned 49 declared tests into false failures.
        """
        tests = _generator_with(_DeclaredPayloadHandler()).generate_json()

        assert tests, "fixture handler produced no tests — the fixture is broken"
        payload = tests[0].get("tool_payload")
        assert payload is not None, (
            "the JSON playbook omits tool_payload, so a harness must go back to "
            "regexing the prose command it was added to replace"
        )
        assert payload["tool_name"] == ToolName.WRITE
        assert payload["tool_input"]["file_path"] == _PAYLOAD_PATH

    def test_tool_payload_is_none_when_the_command_is_already_a_shell_command(self) -> None:
        """Most tests need no payload; the key must still be present.

        A harness distinguishes "no payload declared" from "field absent"
        only if the key is always emitted.
        """
        tests = _generator_with(_UnproducibleHandler()).generate_json()

        assert "tool_payload" in tests[0]
        assert tests[0]["tool_payload"] is None

    def test_the_prose_command_survives_alongside_the_payload(self) -> None:
        """The playbook is still read by a human, who follows the sentence."""
        tests = _generator_with(_DeclaredPayloadHandler()).generate_json()

        assert tests[0]["command"] == _PAYLOAD_PROSE


class TestMarkdownShowsTheDeclaredPayload:
    """A human tester must see the same payload the harness dispatches.

    `_skip_block` is shared between the built-in and project-handler renderers
    precisely so a test is never skipped in one section and demanded in the
    other. The payload block carries the same risk in reverse: a tester told
    only "use the Write tool to create X" has to invent the content, and will
    invent something the assertion does not match.
    """

    def test_markdown_renders_the_tool_and_its_input(self) -> None:
        markdown = _generator_with(_DeclaredPayloadHandler()).generate_markdown()

        assert "**Tool call**" in markdown
        assert "`Write`" in markdown
        assert _PAYLOAD_PATH in markdown

    def test_markdown_keeps_the_prose_command_too(self) -> None:
        markdown = _generator_with(_DeclaredPayloadHandler()).generate_markdown()

        assert _PAYLOAD_PROSE in markdown

    def test_a_test_without_a_payload_renders_no_payload_block(self) -> None:
        """The block must cost nothing for the ordinary shell-command case."""
        markdown = _generator_with(_UnproducibleHandler()).generate_markdown()

        assert "**Tool call**" not in markdown
