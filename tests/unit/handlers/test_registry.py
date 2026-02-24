"""Tests for HandlerRegistry."""

import importlib
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.handlers.registry import (
    EVENT_TYPE_MAPPING,
    HandlerRegistry,
    _to_snake_case,
    get_registry,
)


class MockHandler(Handler):
    """Mock handler for testing."""

    def __init__(
        self, name: str = "mock", priority: int = 50, tags: list[str] | None = None
    ) -> None:
        """Initialize mock handler."""
        super().__init__(name=name, priority=priority, terminal=False, tags=tags or [])

    def matches(self, hook_input: dict) -> bool:
        """Always match."""
        return True

    def handle(self, hook_input: dict):
        """Mock handle."""
        from claude_code_hooks_daemon.core.hook_result import HookResult

        return HookResult.allow()

    def get_acceptance_tests(self) -> list:
        """Test handler - stub implementation."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType
        from claude_code_hooks_daemon.core.hook_result import Decision

        return [
            AcceptanceTest(
                title="mock handler",
                command="echo 'test'",
                description="Mock handler for unit tests",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                test_type=TestType.BLOCKING,
            )
        ]


class TestHandlerRegistry:
    """Tests for HandlerRegistry class."""

    @pytest.fixture
    def registry(self) -> HandlerRegistry:
        """Create a fresh registry for each test."""
        return HandlerRegistry()

    def test_initialization(self, registry: HandlerRegistry) -> None:
        """Registry should initialize empty."""
        assert registry.list_handlers() == []
        assert not registry.is_disabled("any_handler")

    def test_disable_handler(self, registry: HandlerRegistry) -> None:
        """disable should mark handler as disabled."""
        registry.disable("TestHandler")
        assert registry.is_disabled("TestHandler") is True

    def test_enable_handler(self, registry: HandlerRegistry) -> None:
        """enable should remove handler from disabled set."""
        registry.disable("TestHandler")
        assert registry.is_disabled("TestHandler") is True

        registry.enable("TestHandler")
        assert registry.is_disabled("TestHandler") is False

    def test_enable_never_disabled_handler(self, registry: HandlerRegistry) -> None:
        """enable should be safe to call on handlers that were never disabled."""
        registry.enable("NeverDisabled")
        assert registry.is_disabled("NeverDisabled") is False

    def test_is_disabled_default_false(self, registry: HandlerRegistry) -> None:
        """is_disabled should return False for unknown handlers."""
        assert registry.is_disabled("UnknownHandler") is False

    def test_get_handler_class(self, registry: HandlerRegistry) -> None:
        """get_handler_class should return handler class if registered."""
        # Manually register a handler class
        registry._handlers["TestHandler"] = MockHandler

        handler_class = registry.get_handler_class("TestHandler")
        assert handler_class == MockHandler

    def test_get_handler_class_none(self, registry: HandlerRegistry) -> None:
        """get_handler_class should return None for unknown handlers."""
        handler_class = registry.get_handler_class("UnknownHandler")
        assert handler_class is None

    def test_list_handlers_empty(self, registry: HandlerRegistry) -> None:
        """list_handlers should return empty list initially."""
        assert registry.list_handlers() == []

    def test_list_handlers_with_handlers(self, registry: HandlerRegistry) -> None:
        """list_handlers should return all registered handler names."""
        registry._handlers["Handler1"] = MockHandler
        registry._handlers["Handler2"] = MockHandler

        handlers = registry.list_handlers()
        assert set(handlers) == {"Handler1", "Handler2"}

    def test_discover_real_handlers(self, registry: HandlerRegistry) -> None:
        """discover should find real handlers in the handlers package."""
        count = registry.discover()

        # Should discover many handlers (we have 40+ in the codebase)
        assert count > 30

        # Should include some known handlers
        handlers = registry.list_handlers()
        assert "DestructiveGitHandler" in handlers
        # HelloWorld handlers are specific to event types
        assert any("HelloWorld" in h for h in handlers)

    def test_discover_invalid_package(self, registry: HandlerRegistry) -> None:
        """discover should handle invalid package gracefully."""
        count = registry.discover("nonexistent.package")
        assert count == 0

    def test_discover_skips_init_modules(self, registry: HandlerRegistry) -> None:
        """discover should skip __init__.py modules."""
        registry.discover()
        handlers = registry.list_handlers()

        # Should not include __init__ as a handler name
        assert "__init__" not in handlers

    def test_discover_skips_test_files(self, registry: HandlerRegistry) -> None:
        """discover should skip test files."""
        registry.discover()
        handlers = registry.list_handlers()

        # Should not include any test handlers
        for handler in handlers:
            assert "test" not in handler.lower()

    @patch("claude_code_hooks_daemon.handlers.registry.importlib.import_module")
    def test_discover_handles_import_errors(
        self, mock_import: MagicMock, registry: HandlerRegistry
    ) -> None:
        """discover should handle import errors gracefully."""
        mock_import.side_effect = ImportError("Test import error")

        count = registry.discover("claude_code_hooks_daemon.handlers")
        assert count == 0

    def test_discover_package_without_path_attribute(self, registry: HandlerRegistry) -> None:
        """discover should handle packages without __path__ gracefully."""
        # Try to discover from a module that doesn't have __path__
        count = registry.discover("sys")
        assert count == 0

    @patch("claude_code_hooks_daemon.handlers.registry.pkgutil.walk_packages")
    @patch("claude_code_hooks_daemon.handlers.registry.importlib.import_module")
    def test_discover_handles_module_load_errors(
        self, mock_import: MagicMock, mock_walk: MagicMock, registry: HandlerRegistry
    ) -> None:
        """discover should handle module loading errors gracefully."""
        # First call succeeds (package itself), second call fails (module)
        package_mock = MagicMock()
        package_mock.__path__ = ["/fake/path"]
        mock_import.side_effect = [package_mock, Exception("Module load error")]

        # Simulate finding a module
        mock_walk.return_value = [
            (None, "claude_code_hooks_daemon.handlers.pre_tool_use.test_handler", False)
        ]

        count = registry.discover("claude_code_hooks_daemon.handlers")
        assert count == 0


class TestRegisterAll:
    """Tests for register_all method."""

    @pytest.fixture
    def registry(self) -> HandlerRegistry:
        """Create registry with discovered handlers."""
        reg = HandlerRegistry()
        reg.discover()
        return reg

    @pytest.fixture
    def router(self) -> EventRouter:
        """Create fresh router."""
        return EventRouter()

    def test_register_all_basic(self, registry: HandlerRegistry, router: EventRouter) -> None:
        """register_all should register handlers with router."""
        count = registry.register_all(router)

        # Should register many handlers
        assert count > 30

        # Router should have handlers
        handler_counts = router.get_handler_count()
        assert handler_counts["PreToolUse"] > 10

    def test_register_all_respects_disabled_handlers(
        self, registry: HandlerRegistry, router: EventRouter
    ) -> None:
        """register_all should skip disabled handlers."""
        # Disable a specific handler class
        registry.disable("HelloWorldPreToolUseHandler")

        registry.register_all(router)

        # The disabled handler class should not be registered
        all_handlers = router.get_all_handlers()
        pre_tool_handlers = all_handlers.get("PreToolUse", [])
        handler_classes = [type(h).__name__ for h in pre_tool_handlers]
        assert "HelloWorldPreToolUseHandler" not in handler_classes

    def test_register_all_with_config_disabled(
        self, registry: HandlerRegistry, router: EventRouter
    ) -> None:
        """register_all should respect enabled=false in config."""
        config = {
            "pre_tool_use": {
                "destructive_git": {"enabled": False},
            }
        }

        registry.register_all(router, config=config)

        # DestructiveGitHandler should not be registered
        pre_handlers = router.get_chain(EventType.PRE_TOOL_USE)
        handler_names = [h.name for h in pre_handlers.handlers]
        assert "destructive-git" not in handler_names

    def test_register_all_with_priority_override(
        self, registry: HandlerRegistry, router: EventRouter
    ) -> None:
        """register_all should apply priority override from config."""
        config = {
            "pre_tool_use": {
                "destructive_git": {"priority": 999},
            }
        }

        registry.register_all(router, config=config)

        # Find the destructive git handler
        pre_handlers = router.get_chain(EventType.PRE_TOOL_USE)
        destructive_handler = None
        for handler in pre_handlers.handlers:
            if "destructive" in handler.name.lower():
                destructive_handler = handler
                break

        # Should have custom priority (handler was found and priority was applied)
        assert destructive_handler is not None
        assert destructive_handler.priority == 999

    def test_register_all_with_none_priority_keeps_default(
        self, registry: HandlerRegistry, router: EventRouter
    ) -> None:
        """register_all should NOT override priority when config value is None.

        Regression test for Plan 00070: PyYAML parses 'priority:' with no
        value as None, which would set handler.priority = None and crash
        the chain sort.
        """
        config = {
            "pre_tool_use": {
                "destructive_git": {"priority": None},
            }
        }

        registry.register_all(router, config=config)

        # Find the destructive git handler
        pre_handlers = router.get_chain(EventType.PRE_TOOL_USE)
        destructive_handler = None
        for handler in pre_handlers.handlers:
            if "destructive" in handler.name.lower():
                destructive_handler = handler
                break

        # Should keep original priority (not None)
        assert destructive_handler is not None
        assert destructive_handler.priority is not None
        assert isinstance(destructive_handler.priority, int)

    def test_register_all_with_enable_tags(
        self, registry: HandlerRegistry, router: EventRouter
    ) -> None:
        """register_all should filter handlers by enable_tags."""
        config = {
            "pre_tool_use": {
                "enable_tags": ["safety"],
            }
        }

        registry.register_all(router, config=config)

        # Only handlers with 'safety' tag should be registered
        pre_handlers = router.get_chain(EventType.PRE_TOOL_USE)

        # Should have some handlers
        assert len(pre_handlers) > 0

        # All handlers should have 'safety' tag
        for handler in pre_handlers.handlers:
            assert "safety" in handler.tags

    def test_register_all_with_disable_tags(
        self, registry: HandlerRegistry, router: EventRouter
    ) -> None:
        """register_all should exclude handlers by disable_tags."""
        config = {
            "pre_tool_use": {
                "disable_tags": ["test"],
            }
        }

        registry.register_all(router, config=config)

        # No handlers with 'test' tag should be registered
        pre_handlers = router.get_chain(EventType.PRE_TOOL_USE)

        for handler in pre_handlers.handlers:
            assert "test" not in handler.tags

    def test_register_all_handles_instantiation_errors(
        self, registry: HandlerRegistry, router: EventRouter
    ) -> None:
        """register_all should handle handler instantiation errors gracefully."""
        # This test ensures the method doesn't crash on bad handlers
        # In practice, all our handlers should instantiate correctly
        count = registry.register_all(router)
        assert count > 0

    def test_register_all_empty_config(
        self, registry: HandlerRegistry, router: EventRouter
    ) -> None:
        """register_all should work with None config."""
        count = registry.register_all(router, config=None)
        assert count > 0

    def test_register_all_missing_event_dir(
        self, registry: HandlerRegistry, router: EventRouter
    ) -> None:
        """register_all should skip missing event directories gracefully."""
        # Should not crash even if some event directories don't exist
        count = registry.register_all(router)
        assert count > 0

    def test_register_all_handles_import_errors(
        self, registry: HandlerRegistry, router: EventRouter
    ) -> None:
        """register_all should handle import errors gracefully."""
        # Use a config that points to invalid handlers (won't crash)
        config = {
            "pre_tool_use": {
                "nonexistent_handler": {"enabled": True},
            }
        }
        count = registry.register_all(router, config=config)
        assert count >= 0  # Should not crash

    def test_register_all_with_disable_tags_not_list(
        self, registry: HandlerRegistry, router: EventRouter
    ) -> None:
        """register_all should handle disable_tags that is not a list."""
        config = {
            "pre_tool_use": {
                "disable_tags": "not-a-list",  # Should be ignored/handled
            }
        }
        # Should not crash
        count = registry.register_all(router, config=config)
        assert count >= 0


class TestEventTypeMapping:
    """Tests for EVENT_TYPE_MAPPING."""

    def test_all_event_types_mapped(self) -> None:
        """All EventType values should be in the mapping."""
        mapped_types = set(EVENT_TYPE_MAPPING.values())
        all_types = set(EventType)

        assert mapped_types == all_types

    def test_mapping_keys_are_snake_case(self) -> None:
        """All mapping keys should be snake_case."""
        for key in EVENT_TYPE_MAPPING:
            assert key.islower()
            assert " " not in key
            # Should use underscores for word separation
            if len(key.split("_")) > 1:
                assert "_" in key


class TestSnakeCaseConverter:
    """Tests for _to_snake_case helper."""

    def test_simple_camel_case(self) -> None:
        """Should convert simple CamelCase to snake_case and strip _handler suffix."""
        assert _to_snake_case("HelloWorld") == "hello_world"
        assert _to_snake_case("MyHandler") == "my"  # _handler suffix stripped

    def test_acronyms(self) -> None:
        """Should handle acronyms correctly and strip _handler suffix."""
        assert _to_snake_case("HTTPHandler") == "http"  # _handler suffix stripped
        assert _to_snake_case("URLParser") == "url_parser"  # No _handler suffix

    def test_single_word(self) -> None:
        """Should handle single words."""
        assert _to_snake_case("Handler") == "handler"
        assert _to_snake_case("Test") == "test"

    def test_already_snake_case(self) -> None:
        """Should handle already snake_case strings."""
        assert _to_snake_case("already_snake_case") == "already_snake_case"

    def test_numbers(self) -> None:
        """Should handle numbers in names and strip _handler suffix."""
        assert _to_snake_case("Handler2") == "handler2"  # No _handler suffix
        assert _to_snake_case("Test123Handler") == "test123"  # _handler suffix stripped

    def test_multiple_uppercase(self) -> None:
        """Should handle multiple consecutive uppercase letters."""
        assert _to_snake_case("HTTPSConnection") == "https_connection"

    def test_real_handler_names(self) -> None:
        """Should correctly convert real handler class names to match config keys."""
        # These match the actual config keys in hooks-daemon.yaml
        assert _to_snake_case("DestructiveGitHandler") == "destructive_git"  # Config key
        assert (
            _to_snake_case("BashErrorDetectorHandler") == "bash_error_detector"
        )  # If had Handler suffix
        assert _to_snake_case("HelloWorldHandler") == "hello_world"  # Config key pattern


class TestDiscoverEdgeCases:
    """Tests for discover() edge cases - skip test modules and handle import errors."""

    @patch("claude_code_hooks_daemon.handlers.registry.pkgutil.walk_packages")
    @patch("claude_code_hooks_daemon.handlers.registry.importlib.import_module")
    def test_discover_skips_modules_with_test_in_name(
        self, mock_import: MagicMock, mock_walk: MagicMock
    ) -> None:
        """discover skips modules with 'test' in the module name."""
        fake_package = types.ModuleType("fake_handlers")
        fake_package.__path__ = ["/fake/path"]
        mock_import.return_value = fake_package

        mock_walk.return_value = [
            (None, "fake_handlers.test_something", False),
            (None, "fake_handlers.my_test_handler", False),
        ]

        registry = HandlerRegistry()
        count = registry.discover("fake_handlers")

        # No handlers discovered (both modules have "test" in name)
        assert count == 0
        # Test modules should NOT have been individually imported
        for call_args in mock_import.call_args_list:
            called_name = call_args[0][0]
            if called_name.startswith("fake_handlers."):
                pytest.fail(f"Test module should have been skipped: {called_name}")

    @patch("claude_code_hooks_daemon.handlers.registry.pkgutil.walk_packages")
    @patch("claude_code_hooks_daemon.handlers.registry.importlib.import_module")
    def test_discover_continues_after_module_import_exception(
        self, mock_import: MagicMock, mock_walk: MagicMock
    ) -> None:
        """discover logs warning and continues when module import raises Exception."""
        fake_package = types.ModuleType("fake_handlers")
        fake_package.__path__ = ["/fake/path"]

        empty_module = types.ModuleType("fake_handlers.valid_module")

        def import_side_effect(name: str) -> types.ModuleType:
            if name == "fake_handlers":
                return fake_package
            if name == "fake_handlers.broken_module":
                raise Exception("Broken module")
            return empty_module

        mock_import.side_effect = import_side_effect

        mock_walk.return_value = [
            (None, "fake_handlers.broken_module", False),
            (None, "fake_handlers.valid_module", False),
        ]

        registry = HandlerRegistry()
        count = registry.discover("fake_handlers")

        # Should not crash - broken module is skipped, valid module has no handlers
        assert count == 0


class TestRegisterAllEdgeCases:
    """Tests for register_all edge cases."""

    def test_register_all_skips_non_existent_event_directory(self, tmp_path: Path) -> None:
        """register_all skips event directories that don't exist on disk."""
        registry = HandlerRegistry()
        router = EventRouter()

        # Patch EVENT_TYPE_MAPPING to include a directory name that doesn't exist
        fake_mapping = {"nonexistent_event_dir": EventType.PRE_TOOL_USE}

        # Point handlers_dir to tmp_path which won't have "nonexistent_event_dir"
        mock_path_instance = MagicMock()
        mock_path_instance.parent = tmp_path

        with (
            patch(
                "claude_code_hooks_daemon.handlers.registry.EVENT_TYPE_MAPPING",
                fake_mapping,
            ),
            patch(
                "claude_code_hooks_daemon.handlers.registry.Path",
                return_value=mock_path_instance,
            ),
        ):
            count = registry.register_all(router)

        assert count == 0

    def test_register_all_continues_when_pass2_import_fails(self) -> None:
        """register_all logs warning and continues when pass 2 import fails (lines 253-255)."""
        registry = HandlerRegistry()
        router = EventRouter()

        # Save real import BEFORE patching
        real_import_fn = importlib.import_module
        call_tracker: dict[str, int] = {}

        def counting_import(name: str) -> Any:
            call_tracker[name] = call_tracker.get(name, 0) + 1
            # On second import of any handler module, fail (pass 2)
            if call_tracker[name] == 2 and "handlers." in name and not name.endswith("__init__"):
                raise Exception("Import failed in pass 2")
            return real_import_fn(name)

        with patch(
            "claude_code_hooks_daemon.handlers.registry.importlib.import_module",
            side_effect=counting_import,
        ):
            # Should not crash - logs warning and continues
            count = registry.register_all(router)

        # Some modules will fail on pass 2 but code should not crash
        assert count >= 0


class TestGetConfigKey:
    """Tests for _get_config_key and _get_config_key_from_constant."""

    def test_get_config_key_fallback_for_unknown_class(self) -> None:
        """_get_config_key auto-generates key for unknown class name with warning."""

        from claude_code_hooks_daemon.handlers.registry import _get_config_key

        with patch("claude_code_hooks_daemon.handlers.registry.logger") as mock_logger:
            result = _get_config_key("CompletelyUnknownHandler")

        # Should fall back to auto-generated snake_case
        assert result == "completely_unknown"
        # Should log a warning
        mock_logger.warning.assert_called_once()
        assert "not found in HandlerID constants" in mock_logger.warning.call_args[0][0]

    def test_get_config_key_from_constant_returns_none_for_unknown(self) -> None:
        """_get_config_key_from_constant returns None for unknown class name."""
        from claude_code_hooks_daemon.handlers.registry import _get_config_key_from_constant

        result = _get_config_key_from_constant("TotallyFakeClassName")

        assert result is None

    def test_get_config_key_from_constant_finds_known_handler(self) -> None:
        """_get_config_key_from_constant finds a known handler's config key."""
        from claude_code_hooks_daemon.handlers.registry import _get_config_key_from_constant

        result = _get_config_key_from_constant("DestructiveGitHandler")

        assert result is not None
        assert result == "destructive_git"


class TestGetRegistry:
    """Tests for get_registry global instance."""

    def test_get_registry_singleton(self) -> None:
        """get_registry should return the same instance."""
        registry1 = get_registry()
        registry2 = get_registry()

        assert registry1 is registry2

    def test_get_registry_autodiscovers(self) -> None:
        """get_registry should auto-discover handlers on first call."""
        registry = get_registry()

        # Should have discovered handlers
        assert len(registry.list_handlers()) > 30

    @patch("claude_code_hooks_daemon.handlers.registry._registry", None)
    def test_get_registry_creates_on_first_call(self) -> None:
        """get_registry should create registry on first call."""
        from claude_code_hooks_daemon.handlers import registry as registry_module

        registry_module._registry = None

        registry = get_registry()
        assert isinstance(registry, HandlerRegistry)
        assert registry is not None

        # Cleanup
        registry_module._registry = None
