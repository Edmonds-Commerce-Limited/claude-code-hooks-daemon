"""Tests for playbook generator with project handler support.

Tests that project handler acceptance tests are included in the generated playbook.
"""

from typing import Any

from claude_code_hooks_daemon.constants import Priority
from claude_code_hooks_daemon.constants.tags import HandlerTag
from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult, TestType
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.daemon.playbook_generator import PlaybookGenerator
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry


class FakeProjectHandler(Handler):
    """Fake project handler for testing playbook generation."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="fake-project-handler",
            priority=Priority.PLAN_WORKFLOW,
            terminal=False,
            tags=[HandlerTag.PROJECT_SPECIFIC],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW, context=["Fake context"])

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return [
            AcceptanceTest(
                title="Fake project handler test",
                command="echo test",
                description="Test that fake project handler works",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"Fake context"],
                test_type=TestType.ADVISORY,
            ),
        ]


class FakeProjectHandlerWithAllFields(Handler):
    """Fake project handler with all optional fields populated."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="fake-full-handler",
            priority=Priority.PLAN_WORKFLOW,
            terminal=False,
            tags=[HandlerTag.PROJECT_SPECIFIC],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.DENY, context=["Blocked"])

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return [
            AcceptanceTest(
                title="Full fields test",
                command="echo full",
                description="Test with all optional fields",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Blocked"],
                test_type=TestType.BLOCKING,
                setup_commands=["mkdir -p /tmp/test-setup"],
                safety_notes="This test is safe to run",
                cleanup_commands=["rm -rf /tmp/test-setup"],
            ),
        ]


class FakeProjectHandlerNoTests(Handler):
    """Fake project handler that returns empty test list."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="fake-no-tests",
            priority=Priority.PLAN_WORKFLOW,
            terminal=False,
            tags=[HandlerTag.PROJECT_SPECIFIC],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW, context=[])

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return []


class TestPlaybookGeneratorProjectHandlers:
    """Tests for playbook generator with project handler support."""

    def test_includes_project_handlers_in_playbook(self) -> None:
        """Playbook includes project handler acceptance tests."""
        registry = HandlerRegistry()
        config: dict[str, Any] = {}

        project_handlers = [FakeProjectHandler()]

        generator = PlaybookGenerator(
            config=config,
            registry=registry,
            plugins=[],
            project_handlers=project_handlers,
        )

        markdown = generator.generate_markdown()

        assert "fake-project-handler" in markdown.lower() or "Fake project handler" in markdown
        assert "Project Handlers" in markdown

    def test_project_handlers_in_separate_section(self) -> None:
        """Project handlers appear in a separate section from built-in handlers."""
        registry = HandlerRegistry()
        config: dict[str, Any] = {}

        project_handlers = [FakeProjectHandler()]

        generator = PlaybookGenerator(
            config=config,
            registry=registry,
            plugins=[],
            project_handlers=project_handlers,
        )

        markdown = generator.generate_markdown()

        assert "## Project Handlers" in markdown or "### Project Handlers" in markdown

    def test_empty_project_handlers_no_section(self) -> None:
        """No project handlers section when no project handlers provided."""
        registry = HandlerRegistry()
        config: dict[str, Any] = {}

        generator = PlaybookGenerator(
            config=config,
            registry=registry,
            plugins=[],
            project_handlers=[],
        )

        markdown = generator.generate_markdown()

        # Should not have a project handlers section if there are none
        assert "Project Handlers" not in markdown

    def test_none_project_handlers_no_section(self) -> None:
        """No project handlers section when project_handlers is None."""
        registry = HandlerRegistry()
        config: dict[str, Any] = {}

        generator = PlaybookGenerator(
            config=config,
            registry=registry,
            plugins=[],
        )

        markdown = generator.generate_markdown()

        assert "Project Handlers" not in markdown

    def test_project_handler_acceptance_test_details(self) -> None:
        """Project handler acceptance test details are included."""
        registry = HandlerRegistry()
        config: dict[str, Any] = {}

        project_handlers = [FakeProjectHandler()]

        generator = PlaybookGenerator(
            config=config,
            registry=registry,
            plugins=[],
            project_handlers=project_handlers,
        )

        markdown = generator.generate_markdown()

        assert "Fake project handler test" in markdown
        assert "echo test" in markdown
        assert "PASS" in markdown
        assert "FAIL" in markdown

    def test_project_handler_with_all_optional_fields(self) -> None:
        """Project handler with setup, safety, and cleanup fields renders correctly."""
        registry = HandlerRegistry()
        config: dict[str, Any] = {}

        project_handlers = [FakeProjectHandlerWithAllFields()]

        generator = PlaybookGenerator(
            config=config,
            registry=registry,
            plugins=[],
            project_handlers=project_handlers,
        )

        markdown = generator.generate_markdown()

        assert "mkdir -p /tmp/test-setup" in markdown
        assert "This test is safe to run" in markdown
        assert "rm -rf /tmp/test-setup" in markdown
        assert "**Setup**:" in markdown
        assert "**Safety**:" in markdown
        assert "**Cleanup**:" in markdown

    def test_project_handler_empty_tests_skipped(self) -> None:
        """Project handler with empty test list is skipped in output."""
        registry = HandlerRegistry()
        config: dict[str, Any] = {}

        project_handlers = [FakeProjectHandlerNoTests(), FakeProjectHandler()]

        generator = PlaybookGenerator(
            config=config,
            registry=registry,
            plugins=[],
            project_handlers=project_handlers,
        )

        markdown = generator.generate_markdown()

        # The handler with no tests should not appear
        assert "fake-no-tests" not in markdown.lower()
        # The handler with tests should still appear
        assert "Fake project handler test" in markdown
