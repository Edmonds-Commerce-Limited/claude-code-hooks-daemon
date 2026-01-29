"""Comprehensive tests for Handler base class."""

import pytest

from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult

# Test Fixtures


class ConcreteHandler(Handler):
    """Concrete handler implementation for testing."""

    def matches(self, hook_input: dict) -> bool:
        """Simple match implementation."""
        return bool(hook_input.get("should_match", False))

    def handle(self, hook_input: dict) -> HookResult:
        """Simple handle implementation."""
        return HookResult(decision="allow", context="Concrete handler executed")


class TerminalHandler(Handler):
    """Terminal handler for testing."""

    def matches(self, hook_input: dict) -> bool:
        """Match implementation."""
        return True

    def handle(self, hook_input: dict) -> HookResult:
        """Handle implementation."""
        return HookResult(decision="deny", reason="Terminal handler blocked")


class NonTerminalHandler(Handler):
    """Non-terminal handler for testing."""

    def __init__(self) -> None:
        """Initialize non-terminal handler."""
        super().__init__(name="non-terminal-test", priority=20, terminal=False)

    def matches(self, hook_input: dict) -> bool:
        """Match implementation."""
        return True

    def handle(self, hook_input: dict) -> HookResult:
        """Handle implementation."""
        return HookResult(decision="allow", context="Non-terminal context")


@pytest.fixture
def concrete_handler():
    """Create concrete handler instance."""
    return ConcreteHandler(name="test-handler", priority=10)


@pytest.fixture
def terminal_handler():
    """Create terminal handler instance."""
    return TerminalHandler(name="terminal-test", priority=15)


@pytest.fixture
def non_terminal_handler():
    """Create non-terminal handler instance."""
    return NonTerminalHandler()


# Initialization Tests


class TestHandlerInit:
    """Test Handler initialization."""

    def test_init_with_required_parameters(self):
        """Should initialize with required name parameter."""
        handler = ConcreteHandler(name="test-handler")
        assert handler.name == "test-handler"
        assert handler.priority == 50  # Default
        assert handler.terminal is True  # Default
        assert handler.tags == []  # Default

    def test_init_with_all_parameters(self):
        """Should initialize with all parameters."""
        handler = ConcreteHandler(
            name="custom-handler", priority=25, terminal=False, tags=["safety", "git"]
        )
        assert handler.name == "custom-handler"
        assert handler.priority == 25
        assert handler.terminal is False
        assert handler.tags == ["safety", "git"]

    def test_init_sets_default_priority(self):
        """Should set default priority to 50."""
        handler = ConcreteHandler(name="test")
        assert handler.priority == 50

    def test_init_sets_default_terminal_true(self):
        """Should set default terminal to True."""
        handler = ConcreteHandler(name="test")
        assert handler.terminal is True

    def test_init_custom_priority(self):
        """Should accept custom priority."""
        priorities = [5, 10, 20, 30, 40, 50, 60]
        for priority in priorities:
            handler = ConcreteHandler(name="test", priority=priority)
            assert handler.priority == priority

    def test_init_terminal_false(self):
        """Should accept terminal=False."""
        handler = ConcreteHandler(name="test", terminal=False)
        assert handler.terminal is False

    def test_init_terminal_true_explicit(self):
        """Should accept explicit terminal=True."""
        handler = ConcreteHandler(name="test", terminal=True)
        assert handler.terminal is True

    def test_init_sets_default_tags_empty_list(self):
        """Should set default tags to empty list."""
        handler = ConcreteHandler(name="test")
        assert handler.tags == []
        assert isinstance(handler.tags, list)

    def test_init_with_single_tag(self):
        """Should accept single tag in list."""
        handler = ConcreteHandler(name="test", tags=["safety"])
        assert handler.tags == ["safety"]

    def test_init_with_multiple_tags(self):
        """Should accept multiple tags."""
        tags = ["safety", "git", "blocking", "terminal"]
        handler = ConcreteHandler(name="test", tags=tags)
        assert handler.tags == tags

    def test_init_with_empty_tags_list(self):
        """Should accept empty tags list."""
        handler = ConcreteHandler(name="test", tags=[])
        assert handler.tags == []

    def test_init_tags_none_creates_empty_list(self):
        """Should convert tags=None to empty list."""
        handler = ConcreteHandler(name="test", tags=None)
        assert handler.tags == []


# Property Tests


class TestHandlerProperties:
    """Test Handler properties."""

    def test_name_property(self, concrete_handler):
        """Should have accessible name property."""
        assert concrete_handler.name == "test-handler"

    def test_priority_property(self, concrete_handler):
        """Should have accessible priority property."""
        assert concrete_handler.priority == 10

    def test_terminal_property(self, concrete_handler):
        """Should have accessible terminal property."""
        assert concrete_handler.terminal is True

    def test_tags_property(self, concrete_handler):
        """Should have accessible tags property."""
        assert hasattr(concrete_handler, "tags")
        assert isinstance(concrete_handler.tags, list)

    def test_properties_are_instance_attributes(self, concrete_handler):
        """Properties should be instance attributes."""
        assert hasattr(concrete_handler, "name")
        assert hasattr(concrete_handler, "priority")
        assert hasattr(concrete_handler, "terminal")
        assert hasattr(concrete_handler, "tags")

    def test_properties_can_be_modified(self, concrete_handler):
        """Properties should be modifiable (no read-only enforcement)."""
        concrete_handler.name = "modified-name"
        concrete_handler.priority = 99
        concrete_handler.terminal = False
        concrete_handler.tags = ["modified", "tags"]

        assert concrete_handler.name == "modified-name"
        assert concrete_handler.priority == 99
        assert concrete_handler.terminal is False
        assert concrete_handler.tags == ["modified", "tags"]


# Abstract Method Tests


class TestHandlerAbstractMethods:
    """Test Handler abstract methods."""

    def test_matches_not_implemented_raises_error(self):
        """Handler with missing matches() cannot be instantiated (ABC)."""

        class IncompleteHandler(Handler):
            """Handler without matches implementation."""

            def handle(self, hook_input: dict) -> HookResult:
                """Handle implementation."""
                return HookResult(decision="allow")

        # ABC prevents instantiation of incomplete subclasses
        with pytest.raises(TypeError, match="abstract"):
            IncompleteHandler(name="incomplete")

    def test_handle_not_implemented_raises_error(self):
        """Handler with missing handle() cannot be instantiated (ABC)."""

        class IncompleteHandler(Handler):
            """Handler without handle implementation."""

            def matches(self, hook_input: dict) -> bool:
                """Matches implementation."""
                return True

        # ABC prevents instantiation of incomplete subclasses
        with pytest.raises(TypeError, match="abstract"):
            IncompleteHandler(name="incomplete")

    def test_both_methods_not_implemented_raises_error(self):
        """Handler without both methods cannot be instantiated (ABC)."""

        class EmptyHandler(Handler):
            """Handler with no implementations."""

            pass

        # ABC prevents instantiation of incomplete subclasses
        with pytest.raises(TypeError, match="abstract"):
            EmptyHandler(name="empty")


# Subclass Behavior Tests


class TestHandlerSubclass:
    """Test Handler subclass behavior."""

    def test_concrete_handler_matches_implementation(self, concrete_handler):
        """Concrete handler should implement matches()."""
        # Should match when should_match is True
        assert concrete_handler.matches({"should_match": True}) is True

        # Should not match when should_match is False
        assert concrete_handler.matches({"should_match": False}) is False

    def test_concrete_handler_handle_implementation(self, concrete_handler):
        """Concrete handler should implement handle()."""
        result = concrete_handler.handle({})

        assert isinstance(result, HookResult)
        assert result.decision == "allow"
        assert result.context == ["Concrete handler executed"]  # Now a list

    def test_terminal_handler_behavior(self, terminal_handler):
        """Terminal handler should have terminal=True."""
        assert terminal_handler.terminal is True
        assert terminal_handler.matches({}) is True

        result = terminal_handler.handle({})
        assert result.decision == "deny"

    def test_non_terminal_handler_behavior(self, non_terminal_handler):
        """Non-terminal handler should have terminal=False."""
        assert non_terminal_handler.terminal is False
        assert non_terminal_handler.matches({}) is True

        result = non_terminal_handler.handle({})
        assert result.decision == "allow"
        assert result.context == ["Non-terminal context"]  # Now a list

    def test_multiple_handlers_with_different_priorities(self):
        """Multiple handlers should maintain different priorities."""
        handler1 = ConcreteHandler(name="handler1", priority=10)
        handler2 = ConcreteHandler(name="handler2", priority=20)
        handler3 = ConcreteHandler(name="handler3", priority=30)

        assert handler1.priority < handler2.priority < handler3.priority

    def test_handlers_can_have_same_priority(self):
        """Multiple handlers can have same priority."""
        handler1 = ConcreteHandler(name="handler1", priority=20)
        handler2 = ConcreteHandler(name="handler2", priority=20)

        assert handler1.priority == handler2.priority


# matches() Method Tests


class TestMatchesMethod:
    """Test matches() method behavior."""

    def test_matches_receives_hook_input(self, concrete_handler):
        """matches() should receive hook_input dict."""
        hook_input = {"tool_name": "Bash", "should_match": True}
        result = concrete_handler.matches(hook_input)
        assert result is True

    def test_matches_returns_boolean(self, concrete_handler):
        """matches() should return boolean."""
        result = concrete_handler.matches({"should_match": True})
        assert isinstance(result, bool)

    def test_matches_with_empty_dict(self, concrete_handler):
        """matches() should handle empty dict."""
        result = concrete_handler.matches({})
        assert isinstance(result, bool)
        assert result is False  # should_match not present

    def test_matches_can_check_multiple_conditions(self):
        """matches() can implement complex matching logic."""

        class ComplexHandler(Handler):
            """Handler with complex matching logic."""

            def matches(self, hook_input: dict) -> bool:
                """Complex match logic."""
                tool_name = hook_input.get("tool_name")
                tool_input = hook_input.get("tool_input", {})
                command = tool_input.get("command", "")

                return tool_name == "Bash" and "rm -rf" in command

            def handle(self, hook_input: dict) -> HookResult:
                """Handle implementation."""
                return HookResult(decision="deny", reason="Dangerous command")

        handler = ComplexHandler(name="complex", priority=10)

        # Should match
        assert handler.matches({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}) is True

        # Should not match (different tool)
        assert (
            handler.matches({"tool_name": "Write", "tool_input": {"command": "rm -rf /"}}) is False
        )

        # Should not match (no dangerous command)
        assert handler.matches({"tool_name": "Bash", "tool_input": {"command": "ls -la"}}) is False


# handle() Method Tests


class TestHandleMethod:
    """Test handle() method behavior."""

    def test_handle_receives_hook_input(self, concrete_handler):
        """handle() should receive hook_input dict."""
        hook_input = {"tool_name": "Bash", "test": "data"}
        result = concrete_handler.handle(hook_input)
        assert isinstance(result, HookResult)

    def test_handle_returns_hook_result(self, concrete_handler):
        """handle() should return HookResult."""
        result = concrete_handler.handle({})
        assert isinstance(result, HookResult)

    def test_handle_with_empty_dict(self, concrete_handler):
        """handle() should handle empty dict."""
        result = concrete_handler.handle({})
        assert isinstance(result, HookResult)

    def test_handle_can_return_different_decisions(self):
        """handle() can return different decision types."""

        class MultiDecisionHandler(Handler):
            """Handler that returns different decisions."""

            def matches(self, hook_input: dict) -> bool:
                """Match implementation."""
                return True

            def handle(self, hook_input: dict) -> HookResult:
                """Handle with different decisions based on input."""
                action = hook_input.get("action")

                if action == "allow":
                    return HookResult(decision="allow")
                elif action == "deny":
                    return HookResult(decision="deny", reason="Denied")
                elif action == "ask":
                    return HookResult(decision="ask", reason="Need confirmation")
                else:
                    return HookResult(decision="allow")

        handler = MultiDecisionHandler(name="multi", priority=10)

        # Test different decisions
        assert handler.handle({"action": "allow"}).decision == "allow"
        assert handler.handle({"action": "deny"}).decision == "deny"
        assert handler.handle({"action": "ask"}).decision == "ask"


# Integration Tests


class TestHandlerIntegration:
    """Integration tests for Handler usage patterns."""

    def test_typical_deny_handler(self):
        """Typical deny handler workflow."""

        class DenyHandler(Handler):
            """Handler that denies operations."""

            def matches(self, hook_input: dict) -> bool:
                """Match dangerous operations."""
                command = hook_input.get("tool_input", {}).get("command", "")
                return "rm -rf" in command

            def handle(self, hook_input: dict) -> HookResult:
                """Deny dangerous operations."""
                return HookResult(decision="deny", reason="Dangerous command blocked")

        handler = DenyHandler(name="deny-dangerous", priority=10)

        # Test matching and handling
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}
        assert handler.matches(hook_input) is True

        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert result.reason and "Dangerous" in result.reason

    def test_typical_guidance_handler(self):
        """Typical guidance handler workflow (non-terminal)."""

        class GuidanceHandler(Handler):
            """Handler that provides guidance."""

            def __init__(self) -> None:
                """Initialize with non-terminal."""
                super().__init__(name="guidance-handler", priority=20, terminal=False)

            def matches(self, hook_input: dict) -> bool:
                """Match Write operations."""
                return hook_input.get("tool_name") == "Write"

            def handle(self, hook_input: dict) -> HookResult:
                """Provide guidance."""
                return HookResult(decision="allow", guidance="Consider using Edit instead of Write")

        handler = GuidanceHandler()

        assert handler.terminal is False

        hook_input = {"tool_name": "Write", "tool_input": {"file_path": "test.py"}}
        assert handler.matches(hook_input) is True

        result = handler.handle(hook_input)
        assert result.decision == "allow"
        assert result.guidance and "Edit instead" in result.guidance

    def test_handler_priority_ordering(self):
        """Test that handlers can be ordered by priority."""
        handlers = [
            ConcreteHandler(name="high", priority=50),
            ConcreteHandler(name="low", priority=10),
            ConcreteHandler(name="medium", priority=30),
        ]

        # Sort by priority
        sorted_handlers = sorted(handlers, key=lambda h: h.priority)

        assert sorted_handlers[0].name == "low"
        assert sorted_handlers[1].name == "medium"
        assert sorted_handlers[2].name == "high"

    def test_handler_terminal_flag_usage(self):
        """Test terminal flag affects handler behavior."""
        terminal = ConcreteHandler(name="terminal", priority=10, terminal=True)
        non_terminal = ConcreteHandler(name="non-terminal", priority=20, terminal=False)

        assert terminal.terminal is True
        assert non_terminal.terminal is False

        # Both can execute, but terminal flag indicates behavior
        assert terminal.matches({"should_match": True}) is True
        assert non_terminal.matches({"should_match": True}) is True


# Edge Cases and Error Handling


class TestHandlerEdgeCases:
    """Test edge cases for Handler."""

    def test_handler_with_none_name(self):
        """Handler raises ValueError with None name and no handler_id."""
        # After adding handler_id support, None name is no longer allowed
        # unless handler_id is provided
        import pytest

        with pytest.raises(ValueError, match="Either handler_id or name must be provided"):
            ConcreteHandler(name=None)  # type: ignore[arg-type]

    def test_handler_with_empty_name(self):
        """Handler can be created with empty name."""
        handler = ConcreteHandler(name="")
        assert handler.name == ""

    def test_handler_with_negative_priority(self):
        """Handler can have negative priority (no validation)."""
        handler = ConcreteHandler(name="test", priority=-10)
        assert handler.priority == -10

    def test_handler_with_zero_priority(self):
        """Handler can have zero priority."""
        handler = ConcreteHandler(name="test", priority=0)
        assert handler.priority == 0

    def test_handler_with_very_high_priority(self):
        """Handler can have very high priority."""
        handler = ConcreteHandler(name="test", priority=9999)
        assert handler.priority == 9999

    def test_handler_matches_with_none_input(self):
        """matches() with None input should be handled by implementation."""
        handler = ConcreteHandler(name="test")

        # Implementation should handle None gracefully
        # Our ConcreteHandler uses .get() so it won't crash
        with pytest.raises(AttributeError):
            # None has no .get() method
            handler.matches(None)  # type: ignore[arg-type]

    def test_handler_handle_with_none_input(self):
        """handle() with None input returns result (implementation-dependent)."""
        handler = ConcreteHandler(name="test")

        # Our implementation doesn't use hook_input, so it works
        result = handler.handle(None)  # type: ignore[arg-type]
        assert isinstance(result, HookResult)


class TestHandlerDocstring:
    """Test Handler class documentation."""

    def test_handler_has_docstring(self):
        """Handler class should have docstring."""
        assert Handler.__doc__ is not None
        assert len(Handler.__doc__) > 0

    def test_handler_init_has_docstring(self):
        """Handler.__init__ should have docstring."""
        assert Handler.__init__.__doc__ is not None

    def test_handler_matches_has_docstring(self):
        """Handler.matches should have docstring."""
        assert Handler.matches.__doc__ is not None

    def test_handler_handle_has_docstring(self):
        """Handler.handle should have docstring."""
        assert Handler.handle.__doc__ is not None


class TestHandlerTags:
    """Test Handler tag functionality."""

    def test_handler_with_language_tags(self):
        """Handler can have language-specific tags."""
        handler = ConcreteHandler(name="python-handler", tags=["python", "qa-enforcement"])
        assert "python" in handler.tags
        assert "qa-enforcement" in handler.tags

    def test_handler_with_function_tags(self):
        """Handler can have function-specific tags."""
        handler = ConcreteHandler(name="safety-handler", tags=["safety", "blocking", "terminal"])
        assert "safety" in handler.tags
        assert "blocking" in handler.tags

    def test_handler_with_mixed_tags(self):
        """Handler can have mixed tag types."""
        tags = ["python", "tdd", "qa-enforcement", "blocking", "terminal"]
        handler = ConcreteHandler(name="tdd-handler", tags=tags)
        assert handler.tags == tags

    def test_multiple_handlers_with_different_tags(self):
        """Multiple handlers can have different tag sets."""
        handler1 = ConcreteHandler(name="h1", tags=["python", "safety"])
        handler2 = ConcreteHandler(name="h2", tags=["typescript", "qa-enforcement"])
        handler3 = ConcreteHandler(name="h3", tags=["git", "workflow"])

        assert handler1.tags != handler2.tags
        assert handler2.tags != handler3.tags

    def test_tag_filtering_logic(self):
        """Test typical tag filtering logic."""
        handlers = [
            ConcreteHandler(name="h1", tags=["python", "safety"]),
            ConcreteHandler(name="h2", tags=["typescript", "qa-enforcement"]),
            ConcreteHandler(name="h3", tags=["python", "tdd"]),
            ConcreteHandler(name="h4", tags=["git", "workflow"]),
        ]

        # Filter by enable_tags (any match)
        enable_tags = ["python"]
        filtered = [h for h in handlers if any(tag in h.tags for tag in enable_tags)]
        assert len(filtered) == 2
        assert filtered[0].name == "h1"
        assert filtered[1].name == "h3"

    def test_tag_exclusion_logic(self):
        """Test typical tag exclusion logic."""
        handlers = [
            ConcreteHandler(name="h1", tags=["python", "safety"]),
            ConcreteHandler(name="h2", tags=["ec-specific", "validation"]),
            ConcreteHandler(name="h3", tags=["python", "tdd"]),
        ]

        # Filter by disable_tags (exclude any match)
        disable_tags = ["ec-specific"]
        filtered = [h for h in handlers if not any(tag in h.tags for tag in disable_tags)]
        assert len(filtered) == 2
        assert filtered[0].name == "h1"
        assert filtered[1].name == "h3"


class TestHandlerRepr:
    """Test Handler __repr__ method."""

    def test_repr_includes_name(self):
        """__repr__ should include handler name."""
        handler = ConcreteHandler(name="test-handler")
        repr_str = repr(handler)
        assert "test-handler" in repr_str

    def test_repr_includes_priority(self):
        """__repr__ should include priority."""
        handler = ConcreteHandler(name="test", priority=25)
        repr_str = repr(handler)
        assert "priority=25" in repr_str

    def test_repr_includes_terminal(self):
        """__repr__ should include terminal flag."""
        handler = ConcreteHandler(name="test", terminal=False)
        repr_str = repr(handler)
        assert "terminal=False" in repr_str

    def test_repr_includes_tags(self):
        """__repr__ should include tags."""
        handler = ConcreteHandler(name="test", tags=["safety", "git"])
        repr_str = repr(handler)
        assert "tags=" in repr_str
        assert "safety" in repr_str
        assert "git" in repr_str

    def test_repr_with_empty_tags(self):
        """__repr__ should show empty list for tags."""
        handler = ConcreteHandler(name="test")
        repr_str = repr(handler)
        assert "tags=[]" in repr_str

    def test_repr_format(self):
        """__repr__ should have expected format."""
        handler = ConcreteHandler(name="test", priority=10, terminal=True, tags=["safety"])
        repr_str = repr(handler)
        assert repr_str.startswith("ConcreteHandler(")
        assert repr_str.endswith(")")
        assert "name=" in repr_str
        assert "priority=" in repr_str
        assert "terminal=" in repr_str
        assert "tags=" in repr_str
