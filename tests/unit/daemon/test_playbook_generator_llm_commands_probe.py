"""The generator must probe llm:-script availability like it probes rustc.

Plan 00295 Task 3.9: ``validate_eslint_on_write``'s acceptance test declares
its command runs real ESLint only when the project's ``package.json``
declares an ``llm:``-prefixed script -- otherwise the handler takes its
advisory branch. The playbook rendered this test as fully runnable even in
a checkout with no ``package.json`` at all (this daemon's own self-install
checkout, notably), the same gap ``required_tools`` closes for a missing
toolchain binary (e.g. ``rustc``). ``requires_llm_commands`` is the
analogous declaration, checked via
:func:`claude_code_hooks_daemon.utils.npm.has_llm_commands_in_package_json`
rather than ``shutil.which``.
"""

from typing import Any

from claude_code_hooks_daemon.constants import Priority
from claude_code_hooks_daemon.core import AcceptanceTest, Decision, Handler, HookResult, TestType
from claude_code_hooks_daemon.daemon import playbook_generator as playbook_generator_module
from claude_code_hooks_daemon.daemon.playbook_generator import PlaybookGenerator
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry


class _LlmCommandsProbeHandler(Handler):
    """Declares one test that requires an llm:-prefixed package.json script."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="llm-commands-probe-fixture",
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
                title="ESLint probe",
                command="echo probe",
                description="Only exercises real ESLint when llm: scripts exist",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"ESLint"],
                test_type=TestType.ADVISORY,
                requires_llm_commands=True,
            ),
        ]


class _NoProbeHandler(Handler):
    """Declares one ordinary test with no llm:-commands precondition."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="no-probe-fixture",
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
                title="Ordinary probe",
                command="echo probe",
                description="No llm:-commands precondition at all",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"ok"],
                test_type=TestType.ADVISORY,
            ),
        ]


def _generator_with(handler: Handler) -> PlaybookGenerator:
    return PlaybookGenerator(config={}, registry=HandlerRegistry(), project_handlers=[handler])


class TestMarkdownSkipsWhenLlmCommandsAreRequiredButUnavailable:
    def test_skip_block_rendered_when_unavailable(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(
            playbook_generator_module, "has_llm_commands_in_package_json", lambda root: False
        )
        markdown = _generator_with(_LlmCommandsProbeHandler()).generate_markdown()

        assert "SKIP" in markdown
        assert "llm:" in markdown

    def test_no_skip_block_when_available(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(
            playbook_generator_module, "has_llm_commands_in_package_json", lambda root: True
        )
        markdown = _generator_with(_LlmCommandsProbeHandler()).generate_markdown()

        assert "⚠️ SKIP" not in markdown

    def test_untouched_test_never_probes(self, monkeypatch: Any) -> None:
        """A test that never declared the precondition is unaffected either way."""
        monkeypatch.setattr(
            playbook_generator_module, "has_llm_commands_in_package_json", lambda root: False
        )
        markdown = _generator_with(_NoProbeHandler()).generate_markdown()

        assert "⚠️ SKIP" not in markdown


class TestJsonExposesTheProbeAndItsResult:
    def test_requires_llm_commands_and_availability_reach_json(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(
            playbook_generator_module, "has_llm_commands_in_package_json", lambda root: False
        )
        tests = _generator_with(_LlmCommandsProbeHandler()).generate_json()

        assert tests, "fixture handler produced no tests — the fixture is broken"
        assert tests[0]["requires_llm_commands"] is True
        assert tests[0]["llm_commands_available"] is False

    def test_availability_true_when_the_probe_finds_llm_commands(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(
            playbook_generator_module, "has_llm_commands_in_package_json", lambda root: True
        )
        tests = _generator_with(_LlmCommandsProbeHandler()).generate_json()

        assert tests[0]["llm_commands_available"] is True
