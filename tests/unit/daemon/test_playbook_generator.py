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


def test_generate_markdown_includes_plugin_handlers() -> None:
    """Test that plugin handlers are included in generated playbook."""
    # Create acceptance test for plugin
    plugin_test = AcceptanceTest(
        title="Plugin handler test",
        command="echo 'plugin test'",
        description="Test from a plugin handler",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=["plugin"],
        test_type=TestType.ADVISORY,
    )

    # Create a mock plugin handler
    class MockPluginHandler(Handler):
        def __init__(self) -> None:
            from claude_code_hooks_daemon.constants.handlers import HandlerIDMeta

            super().__init__(
                handler_id=HandlerIDMeta(
                    class_name="MockPluginHandler",
                    config_key="mock_plugin",
                    display_name="mock-plugin",
                ),
                priority=Priority.BRITISH_ENGLISH,  # Use existing advisory priority
                terminal=False,
            )

        def matches(self, hook_input: dict[str, Any]) -> bool:
            return True

        def handle(self, hook_input: dict[str, Any]) -> HookResult:
            return HookResult(decision=Decision.ALLOW)

        def get_acceptance_tests(self) -> list[AcceptanceTest]:
            return [plugin_test]

    # Create plugin instance
    plugin_handler = MockPluginHandler()

    # Create empty registry (no library handlers)
    registry = HandlerRegistry()
    config: dict[str, Any] = {}

    # Create generator with plugins parameter
    generator = PlaybookGenerator(config=config, registry=registry, plugins=[plugin_handler])

    markdown = generator.generate_markdown()

    # Verify plugin handler appears in playbook
    assert "Plugin handler test" in markdown
    assert "Test from a plugin handler" in markdown
    assert "echo 'plugin test'" in markdown
    assert "**Total Tests**: 1" in markdown
    assert "**Total Handlers**: 1" in markdown


def test_generate_markdown_combines_library_and_plugin_handlers() -> None:
    """Test that library and plugin handlers are combined and sorted by priority."""
    # Library handler test
    library_test = AcceptanceTest(
        title="Library handler test",
        command="echo 'library'",
        description="Test from library handler",
        expected_decision=Decision.DENY,
        expected_message_patterns=[],
    )

    # Plugin handler test
    plugin_test = AcceptanceTest(
        title="Plugin handler test",
        command="echo 'plugin'",
        description="Test from plugin handler",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=[],
    )

    # Create mock plugin with lower priority (should appear first)
    class MockPluginHandler(Handler):
        def __init__(self) -> None:
            from claude_code_hooks_daemon.constants.handlers import HandlerIDMeta

            super().__init__(
                handler_id=HandlerIDMeta(
                    class_name="MockPluginHandler",
                    config_key="mock_plugin",
                    display_name="mock-plugin",
                ),
                priority=Priority.HELLO_WORLD,  # Lower priority (5) than library handler (10)
                terminal=False,
            )

        def matches(self, hook_input: dict[str, Any]) -> bool:
            return True

        def handle(self, hook_input: dict[str, Any]) -> HookResult:
            return HookResult(decision=Decision.ALLOW)

        def get_acceptance_tests(self) -> list[AcceptanceTest]:
            return [plugin_test]

    plugin_handler = MockPluginHandler()

    # Setup library handler with higher priority
    MockHandlerWithTests.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.combined"

    registry = HandlerRegistry()
    registry._handlers["MockHandlerWithTests"] = MockHandlerWithTests

    config = {"pre_tool_use": {"mock_handler_with_tests": {"enabled": True, "priority": 10}}}

    # Create generator with both library and plugin handlers
    generator = PlaybookGenerator(config=config, registry=registry, plugins=[plugin_handler])

    with patch.object(MockHandlerWithTests, "get_acceptance_tests", return_value=[library_test]):
        markdown = generator.generate_markdown()

    # Both should appear
    assert "Library handler test" in markdown
    assert "Plugin handler test" in markdown

    # Plugin (priority 5) should appear before library (priority 10)
    plugin_pos = markdown.find("Plugin handler test")
    library_pos = markdown.find("Library handler test")
    assert plugin_pos < library_pos, "Plugin handler (lower priority) should appear first"

    assert "**Total Tests**: 2" in markdown
    assert "**Total Handlers**: 2" in markdown


def test_generate_markdown_with_empty_plugins_list() -> None:
    """Test that empty plugins list works (backward compatibility)."""
    config: dict[str, Any] = {}
    registry = HandlerRegistry()

    # Explicitly pass empty plugins list
    generator = PlaybookGenerator(config=config, registry=registry, plugins=[])

    markdown = generator.generate_markdown()

    # Should generate valid markdown with no errors
    assert "# Acceptance Testing Playbook" in markdown
    assert "**Total Tests**: 0" in markdown


def test_generate_markdown_plugins_parameter_defaults_to_empty() -> None:
    """Test that plugins parameter is optional and defaults to empty list."""
    config: dict[str, Any] = {}
    registry = HandlerRegistry()

    # Don't pass plugins parameter at all (backward compatibility)
    generator = PlaybookGenerator(config=config, registry=registry)

    markdown = generator.generate_markdown()

    # Should work without plugins parameter
    assert "# Acceptance Testing Playbook" in markdown
    assert "**Total Tests**: 0" in markdown


# Tests for generate_json() and _collect_tests()


def test_collect_tests_returns_correct_structure() -> None:
    """Test that _collect_tests returns tuples with source field."""
    test = AcceptanceTest(
        title="Test collect",
        command="echo test",
        description="Test _collect_tests structure",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=[],
    )

    MockHandlerWithTests.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.collect"

    registry = HandlerRegistry()
    registry._handlers["MockHandlerWithTests"] = MockHandlerWithTests

    config = {"pre_tool_use": {"mock_handler_with_tests": {"enabled": True, "priority": 10}}}

    generator = PlaybookGenerator(config=config, registry=registry)

    with patch.object(MockHandlerWithTests, "get_acceptance_tests", return_value=[test]):
        library_tests, project_tests = generator._collect_tests()

    # Should return library tests with source field
    assert len(library_tests) == 1
    assert len(project_tests) == 0

    handler_name, event_type, priority, tests, source = library_tests[0]
    assert handler_name == "MockHandlerWithTests"
    assert event_type == "PreToolUse"
    assert priority == 10
    assert len(tests) == 1
    assert source == "library"


def test_generate_json_empty_registry() -> None:
    """Test generating JSON with no handlers."""
    config: dict[str, Any] = {}
    registry = HandlerRegistry()
    generator = PlaybookGenerator(config=config, registry=registry)

    json_tests = generator.generate_json()

    # Should return empty list
    assert isinstance(json_tests, list)
    assert len(json_tests) == 0


def test_generate_json_single_handler() -> None:
    """Test generating JSON with a single handler."""
    test = AcceptanceTest(
        title="JSON test",
        command="echo 'json test'",
        description="Test JSON generation",
        expected_decision=Decision.DENY,
        expected_message_patterns=["blocked", "denied"],
        test_type=TestType.BLOCKING,
        setup_commands=["echo 'setup'"],
        cleanup_commands=["echo 'cleanup'"],
        safety_notes="Safe test",
    )

    MockHandlerWithTests.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.json"

    registry = HandlerRegistry()
    registry._handlers["MockHandlerWithTests"] = MockHandlerWithTests

    config = {"pre_tool_use": {"mock_handler_with_tests": {"enabled": True, "priority": 10}}}

    generator = PlaybookGenerator(config=config, registry=registry)

    with patch.object(MockHandlerWithTests, "get_acceptance_tests", return_value=[test]):
        json_tests = generator.generate_json()

    # Should return list with one test
    assert len(json_tests) == 1

    test_dict = json_tests[0]
    assert test_dict["test_number"] == 1
    assert test_dict["handler_name"] == "MockHandlerWithTests"
    assert test_dict["event_type"] == "PreToolUse"
    assert test_dict["priority"] == 10
    assert test_dict["source"] == "library"
    assert test_dict["title"] == "JSON test"
    assert test_dict["command"] == "echo 'json test'"
    assert test_dict["description"] == "Test JSON generation"
    assert test_dict["expected_decision"] == "deny"
    assert test_dict["expected_message_patterns"] == ["blocked", "denied"]
    assert test_dict["test_type"] == "blocking"
    assert test_dict["setup_commands"] == ["echo 'setup'"]
    assert test_dict["cleanup_commands"] == ["echo 'cleanup'"]
    assert test_dict["safety_notes"] == "Safe test"
    assert test_dict["requires_event"] is None


def test_generate_json_filter_by_type_blocking() -> None:
    """Test filtering JSON output by test type (blocking)."""
    blocking_test = AcceptanceTest(
        title="Blocking test",
        command="echo blocking",
        description="Blocking type",
        expected_decision=Decision.DENY,
        expected_message_patterns=[],
        test_type=TestType.BLOCKING,
    )

    advisory_test = AcceptanceTest(
        title="Advisory test",
        command="echo advisory",
        description="Advisory type",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=[],
        test_type=TestType.ADVISORY,
    )

    MockHandlerWithTests.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.filter_type"

    registry = HandlerRegistry()
    registry._handlers["MockHandlerWithTests"] = MockHandlerWithTests

    config = {"pre_tool_use": {"mock_handler_with_tests": {"enabled": True}}}

    generator = PlaybookGenerator(config=config, registry=registry)

    with patch.object(
        MockHandlerWithTests, "get_acceptance_tests", return_value=[blocking_test, advisory_test]
    ):
        # Filter for blocking only
        json_tests = generator.generate_json(filter_type="blocking")

    # Should only return blocking test
    assert len(json_tests) == 1
    assert json_tests[0]["title"] == "Blocking test"
    assert json_tests[0]["test_type"] == "blocking"


def test_generate_json_filter_by_type_advisory() -> None:
    """Test filtering JSON output by test type (advisory)."""
    blocking_test = AcceptanceTest(
        title="Blocking test",
        command="echo blocking",
        description="Blocking type",
        expected_decision=Decision.DENY,
        expected_message_patterns=[],
        test_type=TestType.BLOCKING,
    )

    advisory_test = AcceptanceTest(
        title="Advisory test",
        command="echo advisory",
        description="Advisory type",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=[],
        test_type=TestType.ADVISORY,
    )

    MockHandlerWithTests.__module__ = (
        "claude_code_hooks_daemon.handlers.pre_tool_use.filter_advisory"
    )

    registry = HandlerRegistry()
    registry._handlers["MockHandlerWithTests"] = MockHandlerWithTests

    config = {"pre_tool_use": {"mock_handler_with_tests": {"enabled": True}}}

    generator = PlaybookGenerator(config=config, registry=registry)

    with patch.object(
        MockHandlerWithTests, "get_acceptance_tests", return_value=[blocking_test, advisory_test]
    ):
        # Filter for advisory only
        json_tests = generator.generate_json(filter_type="advisory")

    # Should only return advisory test
    assert len(json_tests) == 1
    assert json_tests[0]["title"] == "Advisory test"
    assert json_tests[0]["test_type"] == "advisory"


def test_generate_json_filter_by_handler_name() -> None:
    """Test filtering JSON output by handler name substring."""
    test1 = AcceptanceTest(
        title="Git test",
        command="echo git",
        description="Git handler test",
        expected_decision=Decision.DENY,
        expected_message_patterns=[],
    )

    test2 = AcceptanceTest(
        title="Npm test",
        command="echo npm",
        description="Npm handler test",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=[],
    )

    class GitHandler(MockHandlerWithTests):
        pass

    class NpmHandler(MockHandlerWithTests):
        pass

    GitHandler.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.git"
    NpmHandler.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.npm"

    registry = HandlerRegistry()
    registry._handlers["GitHandler"] = GitHandler
    registry._handlers["NpmHandler"] = NpmHandler

    config = {
        "pre_tool_use": {
            "git": {"enabled": True},
            "npm": {"enabled": True},
        }
    }

    generator = PlaybookGenerator(config=config, registry=registry)

    with patch.object(GitHandler, "__init__", return_value=None):
        with patch.object(GitHandler, "get_acceptance_tests", return_value=[test1]):
            with patch.object(GitHandler, "priority", 10):
                with patch.object(NpmHandler, "__init__", return_value=None):
                    with patch.object(NpmHandler, "get_acceptance_tests", return_value=[test2]):
                        with patch.object(NpmHandler, "priority", 20):
                            # Filter for Git handler only
                            json_tests = generator.generate_json(filter_handler="Git")

    # Should only return Git handler test
    assert len(json_tests) == 1
    assert json_tests[0]["handler_name"] == "GitHandler"
    assert json_tests[0]["title"] == "Git test"


def test_generate_json_filter_handler_case_insensitive() -> None:
    """Test that handler name filtering is case-insensitive."""
    test = AcceptanceTest(
        title="Test",
        command="echo test",
        description="Test case insensitive filtering",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=[],
    )

    MockHandlerWithTests.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.case"

    registry = HandlerRegistry()
    registry._handlers["MockHandlerWithTests"] = MockHandlerWithTests

    config = {"pre_tool_use": {"mock_handler_with_tests": {"enabled": True}}}

    generator = PlaybookGenerator(config=config, registry=registry)

    with patch.object(MockHandlerWithTests, "get_acceptance_tests", return_value=[test]):
        # Filter with lowercase substring
        json_tests = generator.generate_json(filter_handler="mock")

    # Should match "MockHandlerWithTests"
    assert len(json_tests) == 1
    assert json_tests[0]["handler_name"] == "MockHandlerWithTests"


def test_generate_json_combined_filters() -> None:
    """Test using both filter_type and filter_handler together."""
    blocking_test = AcceptanceTest(
        title="Git blocking",
        command="echo git blocking",
        description="Git blocking test",
        expected_decision=Decision.DENY,
        expected_message_patterns=[],
        test_type=TestType.BLOCKING,
    )

    advisory_test = AcceptanceTest(
        title="Git advisory",
        command="echo git advisory",
        description="Git advisory test",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=[],
        test_type=TestType.ADVISORY,
    )

    blocking_test2 = AcceptanceTest(
        title="Npm blocking",
        command="echo npm blocking",
        description="Npm blocking test",
        expected_decision=Decision.DENY,
        expected_message_patterns=[],
        test_type=TestType.BLOCKING,
    )

    class GitHandler(MockHandlerWithTests):
        pass

    class NpmHandler(MockHandlerWithTests):
        pass

    GitHandler.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.git_combined"
    NpmHandler.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.npm_combined"

    registry = HandlerRegistry()
    registry._handlers["GitHandler"] = GitHandler
    registry._handlers["NpmHandler"] = NpmHandler

    config = {
        "pre_tool_use": {
            "git": {"enabled": True},
            "npm": {"enabled": True},
        }
    }

    generator = PlaybookGenerator(config=config, registry=registry)

    with patch.object(GitHandler, "__init__", return_value=None):
        with patch.object(
            GitHandler, "get_acceptance_tests", return_value=[blocking_test, advisory_test]
        ):
            with patch.object(GitHandler, "priority", 10):
                with patch.object(NpmHandler, "__init__", return_value=None):
                    with patch.object(
                        NpmHandler, "get_acceptance_tests", return_value=[blocking_test2]
                    ):
                        with patch.object(NpmHandler, "priority", 20):
                            # Filter for Git handler AND blocking type
                            json_tests = generator.generate_json(
                                filter_type="blocking", filter_handler="Git"
                            )

    # Should only return Git blocking test
    assert len(json_tests) == 1
    assert json_tests[0]["handler_name"] == "GitHandler"
    assert json_tests[0]["title"] == "Git blocking"
    assert json_tests[0]["test_type"] == "blocking"


def test_generate_json_test_numbering() -> None:
    """Test that test numbers are sequential across handlers."""
    test1 = AcceptanceTest(
        title="Test 1",
        command="echo 1",
        description="First test",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=[],
    )

    test2 = AcceptanceTest(
        title="Test 2",
        command="echo 2",
        description="Second test",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=[],
    )

    class Handler1(MockHandlerWithTests):
        pass

    class Handler2(MockHandlerWithTests):
        pass

    Handler1.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.h1"
    Handler2.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.h2"

    registry = HandlerRegistry()
    registry._handlers["Handler1"] = Handler1
    registry._handlers["Handler2"] = Handler2

    config = {
        "pre_tool_use": {
            "h1": {"enabled": True, "priority": 10},
            "h2": {"enabled": True, "priority": 20},
        }
    }

    generator = PlaybookGenerator(config=config, registry=registry)

    with patch.object(Handler1, "__init__", return_value=None):
        with patch.object(Handler1, "get_acceptance_tests", return_value=[test1]):
            with patch.object(Handler1, "priority", 10):
                with patch.object(Handler2, "__init__", return_value=None):
                    with patch.object(Handler2, "get_acceptance_tests", return_value=[test2]):
                        with patch.object(Handler2, "priority", 20):
                            json_tests = generator.generate_json()

    # Should have sequential test numbers
    assert len(json_tests) == 2
    assert json_tests[0]["test_number"] == 1
    assert json_tests[1]["test_number"] == 2


def test_generate_json_includes_plugin_handlers() -> None:
    """Test that plugin handlers are included in JSON output with source=plugin."""
    plugin_test = AcceptanceTest(
        title="Plugin JSON test",
        command="echo plugin",
        description="Plugin test in JSON",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=[],
    )

    class MockPluginHandler(Handler):
        def __init__(self) -> None:
            from claude_code_hooks_daemon.constants.handlers import HandlerIDMeta

            super().__init__(
                handler_id=HandlerIDMeta(
                    class_name="MockPluginHandler",
                    config_key="mock_plugin",
                    display_name="mock-plugin",
                ),
                priority=Priority.HELLO_WORLD,
                terminal=False,
            )

        def matches(self, hook_input: dict[str, Any]) -> bool:
            return True

        def handle(self, hook_input: dict[str, Any]) -> HookResult:
            return HookResult(decision=Decision.ALLOW)

        def get_acceptance_tests(self) -> list[AcceptanceTest]:
            return [plugin_test]

    plugin_handler = MockPluginHandler()

    registry = HandlerRegistry()
    config: dict[str, Any] = {}

    generator = PlaybookGenerator(config=config, registry=registry, plugins=[plugin_handler])

    json_tests = generator.generate_json()

    # Should include plugin test with source=plugin
    assert len(json_tests) == 1
    assert json_tests[0]["handler_name"] == "MockPluginHandler"
    assert json_tests[0]["source"] == "plugin"
    assert json_tests[0]["title"] == "Plugin JSON test"


def test_generate_json_includes_project_handlers() -> None:
    """Test that project handlers are included in JSON output with source=project."""
    project_test = AcceptanceTest(
        title="Project JSON test",
        command="echo project",
        description="Project handler test",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=[],
    )

    class MockProjectHandler(Handler):
        def __init__(self) -> None:
            from claude_code_hooks_daemon.constants.handlers import HandlerIDMeta

            super().__init__(
                handler_id=HandlerIDMeta(
                    class_name="MockProjectHandler",
                    config_key="mock_project",
                    display_name="mock-project",
                ),
                priority=Priority.HELLO_WORLD,
                terminal=False,
            )

        def matches(self, hook_input: dict[str, Any]) -> bool:
            return True

        def handle(self, hook_input: dict[str, Any]) -> HookResult:
            return HookResult(decision=Decision.ALLOW)

        def get_acceptance_tests(self) -> list[AcceptanceTest]:
            return [project_test]

    project_handler = MockProjectHandler()

    registry = HandlerRegistry()
    config: dict[str, Any] = {}

    generator = PlaybookGenerator(
        config=config, registry=registry, project_handlers=[project_handler]
    )

    json_tests = generator.generate_json()

    # Should include project test with source=project
    assert len(json_tests) == 1
    assert json_tests[0]["handler_name"] == "MockProjectHandler"
    assert json_tests[0]["source"] == "project"
    assert json_tests[0]["title"] == "Project JSON test"


def test_generate_json_all_sources_combined() -> None:
    """Test that library, plugin, and project handlers are all combined in JSON."""
    library_test = AcceptanceTest(
        title="Library test",
        command="echo library",
        description="From library",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=[],
    )

    plugin_test = AcceptanceTest(
        title="Plugin test",
        command="echo plugin",
        description="From plugin",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=[],
    )

    project_test = AcceptanceTest(
        title="Project test",
        command="echo project",
        description="From project",
        expected_decision=Decision.ALLOW,
        expected_message_patterns=[],
    )

    # Library handler
    MockHandlerWithTests.__module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.all_sources"

    # Plugin handler
    class MockPluginHandler(Handler):
        def __init__(self) -> None:
            from claude_code_hooks_daemon.constants.handlers import HandlerIDMeta

            super().__init__(
                handler_id=HandlerIDMeta(
                    class_name="PluginHandler",
                    config_key="plugin",
                    display_name="plugin",
                ),
                priority=Priority.BRITISH_ENGLISH,
                terminal=False,
            )

        def matches(self, hook_input: dict[str, Any]) -> bool:
            return True

        def handle(self, hook_input: dict[str, Any]) -> HookResult:
            return HookResult(decision=Decision.ALLOW)

        def get_acceptance_tests(self) -> list[AcceptanceTest]:
            return [plugin_test]

    # Project handler
    class MockProjectHandler(Handler):
        def __init__(self) -> None:
            from claude_code_hooks_daemon.constants.handlers import HandlerIDMeta

            super().__init__(
                handler_id=HandlerIDMeta(
                    class_name="ProjectHandler",
                    config_key="project",
                    display_name="project",
                ),
                priority=Priority.PLAN_WORKFLOW,  # Workflow range priority
                terminal=False,
            )

        def matches(self, hook_input: dict[str, Any]) -> bool:
            return True

        def handle(self, hook_input: dict[str, Any]) -> HookResult:
            return HookResult(decision=Decision.ALLOW)

        def get_acceptance_tests(self) -> list[AcceptanceTest]:
            return [project_test]

    registry = HandlerRegistry()
    registry._handlers["MockHandlerWithTests"] = MockHandlerWithTests

    config = {"pre_tool_use": {"mock_handler_with_tests": {"enabled": True}}}

    generator = PlaybookGenerator(
        config=config,
        registry=registry,
        plugins=[MockPluginHandler()],
        project_handlers=[MockProjectHandler()],
    )

    with patch.object(MockHandlerWithTests, "get_acceptance_tests", return_value=[library_test]):
        json_tests = generator.generate_json()

    # Should have all three tests
    assert len(json_tests) == 3

    sources = {test["source"] for test in json_tests}
    assert sources == {"library", "plugin", "project"}

    titles = {test["title"] for test in json_tests}
    assert titles == {"Library test", "Plugin test", "Project test"}
