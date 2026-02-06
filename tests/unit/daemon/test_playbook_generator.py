"""Unit tests for PlaybookGenerator."""

from typing import Any, Protocol
from unittest.mock import patch

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import AcceptanceTest, Decision, Handler
from claude_code_hooks_daemon.core.acceptance_test import TestType
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.daemon.playbook_generator import PlaybookGenerator
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry


class MockHandlerWithTests(Handler):
    """Mock handler for testing that has acceptance tests."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.DESTRUCTIVE_GIT, priority=Priority.DESTRUCTIVE_GIT, terminal=False
        )
        self._tests: list[AcceptanceTest] = []

    def set_tests(self, tests: list[AcceptanceTest]) -> None:
        """Set acceptance tests for this handler."""
        self._tests = tests

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Mock matches implementation."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Mock handle implementation."""
        return HookResult(decision=Decision.ALLOW)

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return mock acceptance tests."""
        return self._tests


class MockHandlerNoTests(Handler):
    """Mock handler with no acceptance tests."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SED_BLOCKER, priority=Priority.SED_BLOCKER, terminal=False
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Mock matches implementation."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Mock handle implementation."""
        return HookResult(decision=Decision.ALLOW)


class MockHandlerNoMethod(Handler):
    """Mock handler without get_acceptance_tests method."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.ABSOLUTE_PATH, priority=Priority.ABSOLUTE_PATH, terminal=False
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Mock matches implementation."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Mock handle implementation."""
        return HookResult(decision=Decision.ALLOW)


class BrokenHandler(Handler):
    """Mock handler that raises exception during instantiation."""

    def __init__(self) -> None:
        raise ValueError("Intentional initialization error")

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Mock matches implementation."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Mock handle implementation."""
        return HookResult(decision=Decision.ALLOW)

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return mock acceptance tests."""
        return []


class HandlerClassGetter(Protocol):
    """Protocol for handler class getter method."""

    def __call__(self, name: str) -> type[Handler] | None:
        """Get handler class by name."""
        ...


def test_playbook_generator_initialization() -> None:
    """Test PlaybookGenerator can be initialized."""
    config: dict[str, Any] = {}
    registry = HandlerRegistry()
    generator = PlaybookGenerator(config=config, registry=registry)
    assert generator is not None


def test_generate_markdown_empty_registry() -> None:
    """Test generating markdown with no handlers."""
    config: dict[str, Any] = {}
    registry = HandlerRegistry()
    generator = PlaybookGenerator(config=config, registry=registry)

    markdown = generator.generate_markdown()

    # Should still generate valid markdown structure
    assert "# Acceptance Testing Playbook" in markdown
    assert "## Prerequisites" in markdown
    assert "## Instructions" in markdown
    assert "## Tests" in markdown
    assert "## Summary" in markdown
    assert "**Total Tests**: 0" in markdown
    assert "**Total Handlers**: 0" in markdown


def test_generate_markdown_with_single_handler() -> None:
    """Test generating markdown with a handler that has acceptance tests."""
    # Create a test
    test = AcceptanceTest(
        title="Test destructive git command",
        command="git reset --hard",
        description="Should block destructive git reset",
        expected_decision=Decision.DENY,
        expected_message_patterns=["blocked", "destructive"],
        test_type=TestType.BLOCKING,
    )

    # Setup registry
    registry = HandlerRegistry()
    registry._handlers["MockHandlerWithTests"] = MockHandlerWithTests

    # Mock module path to match pre_tool_use event
    MockHandlerWithTests.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.mock"

    config = {"pre_tool_use": {"mock_handler_with_tests": {"enabled": True, "priority": 10}}}

    generator = PlaybookGenerator(config=config, registry=registry)

    # Mock get_acceptance_tests to return our test
    with patch.object(MockHandlerWithTests, "get_acceptance_tests", return_value=[test]):
        markdown = generator.generate_markdown()

    # Verify structure
    assert "# Acceptance Testing Playbook" in markdown
    assert "### Handler: MockHandlerWithTests" in markdown
    assert "**Event Type**: PreToolUse" in markdown
    assert "**Priority**: 10" in markdown
    assert "#### Test 1: Test destructive git command" in markdown
    assert "**Type**: Blocking" in markdown
    assert "**Expected Decision**: deny" in markdown
    assert "**Description**: Should block destructive git reset" in markdown
    assert "**Command**:" in markdown
    assert "git reset --hard" in markdown
    assert "**Expected Message Patterns**:" in markdown
    assert "`blocked`" in markdown
    assert "`destructive`" in markdown
    assert "**Result**: [ ] PASS [ ] FAIL" in markdown
    assert "**Total Tests**: 1" in markdown
    assert "**Total Handlers**: 1" in markdown


def test_generate_markdown_with_multiple_handlers_sorted_by_priority() -> None:
    """Test that handlers are sorted by priority (lower first)."""
    test1 = AcceptanceTest(
        title="High priority test",
        command="echo test1",
        description="High priority handler test",
        expected_decision=Decision.DENY,
        expected_message_patterns=[],
    )

    test2 = AcceptanceTest(
        title="Low priority test",
        command="echo test2",
        description="Low priority handler test",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=[],
    )

    # Setup registry with two different handler classes
    class HighPriorityHandler(MockHandlerWithTests):
        pass

    class LowPriorityHandler(MockHandlerWithTests):
        pass

    HighPriorityHandler.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.high"
    LowPriorityHandler.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.low"

    registry = HandlerRegistry()
    registry._handlers["LowPriorityHandler"] = LowPriorityHandler
    registry._handlers["HighPriorityHandler"] = HighPriorityHandler

    config = {
        "pre_tool_use": {
            "low_priority": {"enabled": True, "priority": 10},
            "high_priority": {"enabled": True, "priority": 50},
        }
    }

    generator = PlaybookGenerator(config=config, registry=registry)

    with patch.object(LowPriorityHandler, "__init__", return_value=None):
        with patch.object(LowPriorityHandler, "get_acceptance_tests", return_value=[test2]):
            with patch.object(LowPriorityHandler, "priority", 10):
                with patch.object(HighPriorityHandler, "__init__", return_value=None):
                    with patch.object(
                        HighPriorityHandler, "get_acceptance_tests", return_value=[test1]
                    ):
                        with patch.object(HighPriorityHandler, "priority", 50):
                            markdown = generator.generate_markdown()

    # Lower priority number should appear first
    low_pos = markdown.find("Low priority test")
    high_pos = markdown.find("High priority test")
    assert low_pos < high_pos, "Lower priority handler should appear first"


def test_generate_markdown_with_all_test_fields() -> None:
    """Test formatting with all optional AcceptanceTest fields populated."""
    test = AcceptanceTest(
        title="Complete test",
        command="echo 'test command'",
        description="Test with all fields populated",
        expected_decision=Decision.DENY,
        expected_message_patterns=["pattern1", "pattern2"],
        setup_commands=["echo 'setup 1'", "echo 'setup 2'"],
        cleanup_commands=["echo 'cleanup 1'", "echo 'cleanup 2'"],
        safety_notes="This test is safe because it uses echo",
        test_type=TestType.ADVISORY,
    )

    MockHandlerWithTests.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.complete"

    registry = HandlerRegistry()
    registry._handlers["MockHandlerWithTests"] = MockHandlerWithTests

    config = {"pre_tool_use": {"mock_handler_with_tests": {"enabled": True}}}

    generator = PlaybookGenerator(config=config, registry=registry)

    # Mock get_acceptance_tests to return our test
    with patch.object(MockHandlerWithTests, "get_acceptance_tests", return_value=[test]):
        markdown = generator.generate_markdown()

    # Verify all fields are present
    assert "**Type**: Advisory" in markdown
    assert "**Setup**:" in markdown
    assert "echo 'setup 1'" in markdown
    assert "echo 'setup 2'" in markdown
    assert "**Safety**: This test is safe because it uses echo" in markdown
    assert "**Cleanup**:" in markdown
    assert "echo 'cleanup 1'" in markdown
    assert "echo 'cleanup 2'" in markdown


def test_generate_markdown_multiple_tests_from_same_handler() -> None:
    """Test that multiple tests from same handler are numbered correctly."""
    test1 = AcceptanceTest(
        title="First test",
        command="echo test1",
        description="First test description",
        expected_decision=Decision.DENY,
        expected_message_patterns=[],
    )

    test2 = AcceptanceTest(
        title="Second test",
        command="echo test2",
        description="Second test description",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=[],
    )

    MockHandlerWithTests.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.multi"

    registry = HandlerRegistry()
    registry._handlers["MockHandlerWithTests"] = MockHandlerWithTests

    config = {"pre_tool_use": {"mock_handler_with_tests": {"enabled": True}}}

    generator = PlaybookGenerator(config=config, registry=registry)

    # Mock get_acceptance_tests to return both tests
    with patch.object(MockHandlerWithTests, "get_acceptance_tests", return_value=[test1, test2]):
        markdown = generator.generate_markdown()

    # Both tests should be numbered
    assert "#### Test 1: First test" in markdown
    assert "#### Test 2: Second test" in markdown
    assert "**Total Tests**: 2" in markdown


def test_generate_markdown_skips_disabled_handlers_by_default() -> None:
    """Test that disabled handlers are excluded by default."""
    test = AcceptanceTest(
        title="Disabled handler test",
        command="echo test",
        description="Should not appear",
        expected_decision=Decision.DENY,
        expected_message_patterns=[],
    )

    handler = MockHandlerWithTests()
    handler.set_tests([test])

    MockHandlerWithTests.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.disabled"

    registry = HandlerRegistry()
    registry._handlers["MockHandlerWithTests"] = MockHandlerWithTests

    config = {"pre_tool_use": {"mock_handler_with_tests": {"enabled": False}}}

    generator = PlaybookGenerator(config=config, registry=registry)
    markdown = generator.generate_markdown(include_disabled=False)

    # Handler should not appear
    assert "Disabled handler test" not in markdown
    assert "**Total Tests**: 0" in markdown


def test_generate_markdown_includes_disabled_handlers_when_requested() -> None:
    """Test that disabled handlers are included when include_disabled=True."""
    test = AcceptanceTest(
        title="Disabled handler test",
        command="echo test",
        description="Should appear when included",
        expected_decision=Decision.DENY,
        expected_message_patterns=[],
    )

    MockHandlerWithTests.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.disabled"

    registry = HandlerRegistry()
    registry._handlers["MockHandlerWithTests"] = MockHandlerWithTests

    config = {"pre_tool_use": {"mock_handler_with_tests": {"enabled": False}}}

    generator = PlaybookGenerator(config=config, registry=registry)

    # Mock get_acceptance_tests to return our test
    with patch.object(MockHandlerWithTests, "get_acceptance_tests", return_value=[test]):
        markdown = generator.generate_markdown(include_disabled=True)

    # Handler should appear
    assert "Disabled handler test" in markdown
    assert "**Total Tests**: 1" in markdown


def test_generate_markdown_handles_handler_without_get_acceptance_tests() -> None:
    """Test that handlers without get_acceptance_tests method are skipped gracefully."""
    MockHandlerNoMethod.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.nomethod"

    registry = HandlerRegistry()
    registry._handlers["MockHandlerNoMethod"] = MockHandlerNoMethod

    config = {"pre_tool_use": {"mock_handler_no_method": {"enabled": True}}}

    generator = PlaybookGenerator(config=config, registry=registry)
    markdown = generator.generate_markdown()

    # Should generate without errors, but no tests
    assert "# Acceptance Testing Playbook" in markdown
    assert "**Total Tests**: 0" in markdown


def test_generate_markdown_handles_handler_returning_empty_tests() -> None:
    """Test that handlers returning empty test lists are skipped."""
    handler = MockHandlerWithTests()
    handler.set_tests([])  # Empty list

    MockHandlerWithTests.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.empty"

    registry = HandlerRegistry()
    registry._handlers["MockHandlerWithTests"] = MockHandlerWithTests

    config = {"pre_tool_use": {"mock_handler_with_tests": {"enabled": True}}}

    generator = PlaybookGenerator(config=config, registry=registry)
    markdown = generator.generate_markdown()

    # Should generate without errors, but no tests
    assert "# Acceptance Testing Playbook" in markdown
    assert "**Total Tests**: 0" in markdown


def test_generate_markdown_handles_handler_instantiation_error() -> None:
    """Test that handler instantiation errors are logged and skipped."""
    BrokenHandler.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.broken"

    registry = HandlerRegistry()
    registry._handlers["BrokenHandler"] = BrokenHandler

    config = {"pre_tool_use": {"broken": {"enabled": True}}}

    generator = PlaybookGenerator(config=config, registry=registry)

    # Should not raise exception
    with patch("claude_code_hooks_daemon.daemon.playbook_generator.logger") as mock_logger:
        markdown = generator.generate_markdown()

        # Should log warning with handler name
        mock_logger.warning.assert_called()
        call_args = mock_logger.warning.call_args[0]
        assert "Failed to get tests from %s" in call_args[0]
        assert "BrokenHandler" in call_args[1]

    # Should still generate valid markdown
    assert "# Acceptance Testing Playbook" in markdown
    assert "**Total Tests**: 0" in markdown


def test_generate_markdown_uses_config_priority_over_handler_priority() -> None:
    """Test that priority from config overrides handler's default priority."""
    test = AcceptanceTest(
        title="Priority override test",
        command="echo test",
        description="Test priority override",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=[],
    )

    MockHandlerWithTests.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.priority"

    registry = HandlerRegistry()
    registry._handlers["MockHandlerWithTests"] = MockHandlerWithTests

    config = {"pre_tool_use": {"mock_handler_with_tests": {"enabled": True, "priority": 5}}}

    generator = PlaybookGenerator(config=config, registry=registry)

    # Mock get_acceptance_tests to return our test
    with patch.object(MockHandlerWithTests, "get_acceptance_tests", return_value=[test]):
        markdown = generator.generate_markdown()

    # Should show config priority, not handler priority
    assert "**Priority**: 5" in markdown
    assert "**Priority**: 100" not in markdown


def test_generate_markdown_filters_by_event_type() -> None:
    """Test that handlers are only included for their correct event type."""
    test = AcceptanceTest(
        title="Event type test",
        command="echo test",
        description="Test event type filtering",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=[],
    )

    # Handler in pre_tool_use
    handler = MockHandlerWithTests()
    handler.set_tests([test])

    MockHandlerWithTests.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.event"

    registry = HandlerRegistry()
    registry._handlers["MockHandlerWithTests"] = MockHandlerWithTests

    # Config for post_tool_use (different event type)
    config = {"post_tool_use": {"mock_handler_with_tests": {"enabled": True}}}

    generator = PlaybookGenerator(config=config, registry=registry)
    markdown = generator.generate_markdown()

    # Handler should not appear because event type doesn't match
    assert "Event type test" not in markdown
    assert "**Total Tests**: 0" in markdown


def test_generate_markdown_with_handler_no_config() -> None:
    """Test handler with no config entry uses default enabled=True."""
    test = AcceptanceTest(
        title="No config test",
        command="echo test",
        description="Handler with no config",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=[],
    )

    MockHandlerWithTests.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.noconfig"

    registry = HandlerRegistry()
    registry._handlers["MockHandlerWithTests"] = MockHandlerWithTests

    # Config with pre_tool_use but no entry for this handler
    config = {"pre_tool_use": {}}

    generator = PlaybookGenerator(config=config, registry=registry)

    # Mock get_acceptance_tests to return our test
    with patch.object(MockHandlerWithTests, "get_acceptance_tests", return_value=[test]):
        markdown = generator.generate_markdown()

    # Handler should be included (default enabled=True)
    assert "No config test" in markdown
    assert "**Total Tests**: 1" in markdown


def test_generate_markdown_formats_all_decision_types() -> None:
    """Test that all Decision types are formatted correctly."""
    decisions = [
        (Decision.ALLOW, "allow"),
        (Decision.DENY, "deny"),
        (Decision.CONTINUE, "continue"),
    ]

    for decision, expected_str in decisions:
        test = AcceptanceTest(
            title=f"Test {decision.value}",
            command="echo test",
            description=f"Test decision {decision.value}",
            expected_decision=decision,
            expected_message_patterns=[],
        )

        MockHandlerWithTests.__module__ = (
            f"claude_code_hooks_daemon.handlers.pre_tool_use.{decision.value}"
        )

        registry = HandlerRegistry()
        registry._handlers["MockHandlerWithTests"] = MockHandlerWithTests

        config = {"pre_tool_use": {"mock_handler_with_tests": {"enabled": True}}}

        generator = PlaybookGenerator(config=config, registry=registry)

        # Mock get_acceptance_tests to return our test
        with patch.object(MockHandlerWithTests, "get_acceptance_tests", return_value=[test]):
            markdown = generator.generate_markdown()

        assert f"**Expected Decision**: {expected_str}" in markdown


def test_generate_markdown_formats_all_test_types() -> None:
    """Test that all TestType values are formatted correctly."""
    test_types = [
        (TestType.BLOCKING, "Blocking"),
        (TestType.ADVISORY, "Advisory"),
        (TestType.CONTEXT, "Context"),
    ]

    for test_type, expected_str in test_types:
        test = AcceptanceTest(
            title=f"Test {test_type.value}",
            command="echo test",
            description=f"Test type {test_type.value}",
            expected_decision=Decision.ALLOW,
            expected_message_patterns=[],
            test_type=test_type,
        )

        MockHandlerWithTests.__module__ = (
            f"claude_code_hooks_daemon.handlers.pre_tool_use.{test_type.value}"
        )

        registry = HandlerRegistry()
        registry._handlers["MockHandlerWithTests"] = MockHandlerWithTests

        config = {"pre_tool_use": {"mock_handler_with_tests": {"enabled": True}}}

        generator = PlaybookGenerator(config=config, registry=registry)

        # Mock get_acceptance_tests to return our test
        with patch.object(MockHandlerWithTests, "get_acceptance_tests", return_value=[test]):
            markdown = generator.generate_markdown()

        assert f"**Type**: {expected_str}" in markdown


def test_generate_markdown_includes_generated_date() -> None:
    """Test that generated date is included in markdown."""
    config: dict[str, Any] = {}
    registry = HandlerRegistry()
    generator = PlaybookGenerator(config=config, registry=registry)

    markdown = generator.generate_markdown()

    assert "**Version**: Generated" in markdown
    # Date should be in YYYY-MM-DD format
    import re

    assert re.search(r"\*\*Version\*\*: Generated \d{4}-\d{2}-\d{2}", markdown)


def test_generate_markdown_includes_all_sections() -> None:
    """Test that all required sections are present in markdown."""
    config: dict[str, Any] = {}
    registry = HandlerRegistry()
    generator = PlaybookGenerator(config=config, registry=registry)

    markdown = generator.generate_markdown()

    # Verify all major sections
    assert "# Acceptance Testing Playbook" in markdown
    assert "## Prerequisites" in markdown
    assert "$PYTHON -m claude_code_hooks_daemon.daemon.cli restart" in markdown
    assert "$PYTHON -m claude_code_hooks_daemon.daemon.cli status" in markdown
    assert "## Instructions" in markdown
    assert "## Tests" in markdown
    assert "## Summary" in markdown
    assert "**Total Tests**:" in markdown
    assert "**Total Handlers**:" in markdown
    assert "**Completion Criteria**:" in markdown
    assert "[ ] All tests marked PASS" in markdown


def test_generate_markdown_handles_none_handler_class() -> None:
    """Test that None handler classes are skipped gracefully."""

    # Create a custom registry subclass that returns a handler name but no class
    class MockRegistry(HandlerRegistry):
        def list_handlers(self) -> list[str]:
            return ["NonexistentHandler"]

        def get_handler_class(self, name: str) -> type[Handler] | None:
            # Always return None to simulate missing handler
            return None

    registry = MockRegistry()
    config = {"pre_tool_use": {"nonexistent_handler": {"enabled": True}}}
    generator = PlaybookGenerator(config=config, registry=registry)
    markdown = generator.generate_markdown()

    # Should generate without errors
    assert "# Acceptance Testing Playbook" in markdown
    assert "**Total Tests**: 0" in markdown


def test_generate_markdown_iterates_all_event_types() -> None:
    """Test that all event types in EVENT_TYPE_MAPPING are processed."""
    # Create handlers for multiple event types
    test1 = AcceptanceTest(
        title="PreToolUse test",
        command="echo pre",
        description="Pre tool use",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=[],
    )

    test2 = AcceptanceTest(
        title="PostToolUse test",
        command="echo post",
        description="Post tool use",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=[],
    )

    class PreHandler(MockHandlerWithTests):
        pass

    class PostHandler(MockHandlerWithTests):
        pass

    PreHandler.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.pre"
    PostHandler.__module__ = "claude_code_hooks_daemon.handlers.post_tool_use.post"

    registry = HandlerRegistry()
    registry._handlers["PreHandler"] = PreHandler
    registry._handlers["PostHandler"] = PostHandler

    config = {
        "pre_tool_use": {"pre": {"enabled": True}},
        "post_tool_use": {"post": {"enabled": True}},
    }

    generator = PlaybookGenerator(config=config, registry=registry)

    with patch.object(PreHandler, "__init__", return_value=None):
        with patch.object(PreHandler, "get_acceptance_tests", return_value=[test1]):
            with patch.object(PreHandler, "priority", 10):
                with patch.object(PostHandler, "__init__", return_value=None):
                    with patch.object(PostHandler, "get_acceptance_tests", return_value=[test2]):
                        with patch.object(PostHandler, "priority", 20):
                            markdown = generator.generate_markdown()

    # Both event types should be processed
    assert "PreToolUse test" in markdown
    assert "PostToolUse test" in markdown
    assert "**Total Tests**: 2" in markdown


def test_generate_markdown_with_no_message_patterns() -> None:
    """Test that tests with empty message patterns are formatted correctly."""
    test = AcceptanceTest(
        title="No patterns test",
        command="echo test",
        description="Test with no message patterns",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=[],
    )

    MockHandlerWithTests.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.nopatterns"

    registry = HandlerRegistry()
    registry._handlers["MockHandlerWithTests"] = MockHandlerWithTests

    config = {"pre_tool_use": {"mock_handler_with_tests": {"enabled": True}}}

    generator = PlaybookGenerator(config=config, registry=registry)

    # Mock get_acceptance_tests to return our test
    with patch.object(MockHandlerWithTests, "get_acceptance_tests", return_value=[test]):
        markdown = generator.generate_markdown()

    # Should not include message patterns section
    assert "No patterns test" in markdown
    # The pattern section should not appear since list is empty
    lines = markdown.split("\n")
    test_section_started = False
    for line in lines:
        if "No patterns test" in line:
            test_section_started = True
        if test_section_started and "**Expected Message Patterns**:" in line:
            # This shouldn't happen for empty patterns
            raise AssertionError("Expected Message Patterns should not appear for empty list")
