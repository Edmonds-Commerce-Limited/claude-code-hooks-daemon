"""Tests for DocsGenerator - generates .claude/HOOKS-DAEMON.md from live config.

TDD RED phase: These tests define the expected behavior of the DocsGenerator.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.core import Handler, HookResult


# --- Helpers ---


def _make_handler_class(
    name: str,
    priority: int,
    tags: list[str],
    terminal: bool = True,
    docstring: str = "A test handler.",
    module_name: str = "claude_code_hooks_daemon.handlers.pre_tool_use.test_handler",
) -> type[Handler]:
    """Create a mock handler class for testing."""

    class _TestHandler(Handler):
        __doc__ = docstring

        def __init__(self) -> None:
            super().__init__(
                name=name,
                priority=priority,
                terminal=terminal,
                tags=tags,
            )

        def matches(self, hook_input: dict[str, Any]) -> bool:
            return True

        def handle(self, hook_input: dict[str, Any]) -> HookResult:
            return HookResult()

        def get_acceptance_tests(self) -> list[Any]:
            return []

    _TestHandler.__module__ = module_name
    _TestHandler.__name__ = name.replace("-", "_").title().replace("_", "") + "Handler"
    _TestHandler.__qualname__ = _TestHandler.__name__
    return _TestHandler


def _make_registry(*handler_classes: type[Handler]) -> MagicMock:
    """Create a mock registry with given handler classes."""
    registry = MagicMock()
    registry.list_handlers.return_value = [cls.__name__ for cls in handler_classes]
    registry.get_handler_class.side_effect = lambda name: next(
        (cls for cls in handler_classes if cls.__name__ == name), None
    )
    return registry


def _make_config(
    event_type: str, handlers: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Create a config dict for a single event type."""
    return {event_type: handlers or {}}


# --- Tests ---


class TestDocsGeneratorHeader:
    """Tests for the generated document header."""

    def test_header_contains_title(self) -> None:
        """Header should contain 'Hooks Daemon - Active Configuration'."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        registry = _make_registry()
        gen = DocsGenerator(config={}, registry=registry)
        output = gen.generate_markdown()
        assert "# Hooks Daemon - Active Configuration" in output

    def test_header_contains_version(self) -> None:
        """Header should contain the current version."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator
        from claude_code_hooks_daemon.version import __version__

        registry = _make_registry()
        gen = DocsGenerator(config={}, registry=registry)
        output = gen.generate_markdown()
        assert __version__ in output

    def test_header_contains_generation_timestamp(self) -> None:
        """Header should contain a date stamp."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        registry = _make_registry()
        gen = DocsGenerator(config={}, registry=registry)
        output = gen.generate_markdown()
        today = datetime.now().strftime("%Y-%m-%d")
        assert today in output

    def test_header_contains_regeneration_command(self) -> None:
        """Header should tell agents how to regenerate."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        registry = _make_registry()
        gen = DocsGenerator(config={}, registry=registry)
        output = gen.generate_markdown()
        assert "generate-docs" in output


class TestDocsGeneratorHandlerCollection:
    """Tests for handler collection and grouping."""

    def test_handlers_grouped_by_event_type(self) -> None:
        """Handlers should be grouped under event type headings."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handler_cls = _make_handler_class(
            name="destructive-git",
            priority=10,
            tags=["blocking", "safety"],
            module_name="claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git",
        )
        registry = _make_registry(handler_cls)
        config = _make_config("pre_tool_use", {})
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown()
        assert "### PreToolUse" in output

    def test_handler_table_has_priority_column(self) -> None:
        """Handler tables should include priority column."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handler_cls = _make_handler_class(
            name="destructive-git",
            priority=10,
            tags=["blocking"],
            module_name="claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git",
        )
        registry = _make_registry(handler_cls)
        config = _make_config("pre_tool_use", {})
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown()
        assert "Priority" in output
        assert "| 10 " in output

    def test_handler_table_has_behavior_column(self) -> None:
        """Handler tables should include behavior column derived from tags."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handler_cls = _make_handler_class(
            name="destructive-git",
            priority=10,
            tags=["blocking", "safety"],
            module_name="claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git",
        )
        registry = _make_registry(handler_cls)
        config = _make_config("pre_tool_use", {})
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown()
        assert "Behavior" in output
        assert "BLOCKING" in output

    def test_handler_table_has_description_from_docstring(self) -> None:
        """Handler description should come from first line of class docstring."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handler_cls = _make_handler_class(
            name="destructive-git",
            priority=10,
            tags=["blocking"],
            docstring="Block destructive git commands like force push.",
            module_name="claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git",
        )
        registry = _make_registry(handler_cls)
        config = _make_config("pre_tool_use", {})
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown()
        assert "Block destructive git commands like force push" in output

    def test_handlers_sorted_by_priority_within_event_type(self) -> None:
        """Handlers should be sorted by priority (lower first) within each event type."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handler_a = _make_handler_class(
            name="handler-high-priority",
            priority=10,
            tags=["blocking"],
            docstring="High priority handler.",
            module_name="claude_code_hooks_daemon.handlers.pre_tool_use.handler_a",
        )
        handler_b = _make_handler_class(
            name="handler-low-priority",
            priority=50,
            tags=["advisory"],
            docstring="Low priority handler.",
            module_name="claude_code_hooks_daemon.handlers.pre_tool_use.handler_b",
        )
        registry = _make_registry(handler_a, handler_b)
        config = _make_config("pre_tool_use", {})
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown()

        # "10" should appear before "50" in the output
        pos_10 = output.index("| 10 ")
        pos_50 = output.index("| 50 ")
        assert pos_10 < pos_50

    def test_disabled_handlers_excluded_by_default(self) -> None:
        """Disabled handlers should not appear in output by default."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handler_cls = _make_handler_class(
            name="disabled-handler",
            priority=10,
            tags=["blocking"],
            docstring="Should not appear.",
            module_name="claude_code_hooks_daemon.handlers.pre_tool_use.disabled_handler",
        )
        registry = _make_registry(handler_cls)
        config = _make_config(
            "pre_tool_use",
            {"disabled_handler_handler": {"enabled": False}},
        )
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown()
        assert "Should not appear." not in output

    def test_disabled_handlers_included_when_flag_set(self) -> None:
        """Disabled handlers should appear when include_disabled=True."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handler_cls = _make_handler_class(
            name="disabled-handler",
            priority=10,
            tags=["blocking"],
            docstring="Now it appears.",
            module_name="claude_code_hooks_daemon.handlers.pre_tool_use.disabled_handler",
        )
        registry = _make_registry(handler_cls)
        config = _make_config(
            "pre_tool_use",
            {"disabled_handler_handler": {"enabled": False}},
        )
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown(include_disabled=True)
        assert "Now it appears" in output

    def test_handler_count_in_event_type_heading(self) -> None:
        """Event type headings should include handler count."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handler_cls = _make_handler_class(
            name="test-handler",
            priority=10,
            tags=["blocking"],
            module_name="claude_code_hooks_daemon.handlers.pre_tool_use.test_handler",
        )
        registry = _make_registry(handler_cls)
        config = _make_config("pre_tool_use", {})
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown()
        assert "1 handler" in output or "(1)" in output


class TestDocsGeneratorPlanMode:
    """Tests for plan mode section rendering."""

    def test_plan_mode_section_rendered_when_configured(self) -> None:
        """Plan mode section should appear when track_plans_in_project is set."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        registry = _make_registry()
        config: dict[str, Any] = {
            "post_tool_use": {
                "markdown_organization": {
                    "enabled": True,
                    "options": {"track_plans_in_project": "CLAUDE/Plan"},
                },
            },
        }
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown()
        assert "## Plan Mode" in output
        assert "CLAUDE/Plan" in output

    def test_plan_mode_section_absent_when_not_configured(self) -> None:
        """Plan mode section should NOT appear when track_plans_in_project is not set."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        registry = _make_registry()
        gen = DocsGenerator(config={}, registry=registry)
        output = gen.generate_markdown()
        assert "## Plan Mode" not in output

    def test_plan_mode_section_has_writing_instructions(self) -> None:
        """Plan mode section should tell agents to write directly to project."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        registry = _make_registry()
        config: dict[str, Any] = {
            "post_tool_use": {
                "markdown_organization": {
                    "enabled": True,
                    "options": {"track_plans_in_project": "CLAUDE/Plan"},
                },
            },
        }
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown()
        assert "PLAN.md" in output


class TestDocsGeneratorConfigReference:
    """Tests for the config reference section."""

    def test_config_reference_section_present(self) -> None:
        """Output should include a config reference section."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        registry = _make_registry()
        gen = DocsGenerator(config={}, registry=registry)
        output = gen.generate_markdown()
        assert "## Quick Config Reference" in output

    def test_config_reference_mentions_yaml_file(self) -> None:
        """Config reference should mention the config file path."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        registry = _make_registry()
        gen = DocsGenerator(config={}, registry=registry)
        output = gen.generate_markdown()
        assert "hooks-daemon.yaml" in output

    def test_config_reference_mentions_enable_disable(self) -> None:
        """Config reference should explain how to enable/disable handlers."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        registry = _make_registry()
        gen = DocsGenerator(config={}, registry=registry)
        output = gen.generate_markdown()
        assert "enabled:" in output


class TestDocsGeneratorBehaviorDetection:
    """Tests for detecting handler behavior from tags."""

    def test_advisory_tag_detected(self) -> None:
        """Advisory behavior should be detected from tags."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handler_cls = _make_handler_class(
            name="advisor",
            priority=50,
            tags=["advisory"],
            module_name="claude_code_hooks_daemon.handlers.pre_tool_use.advisor",
        )
        registry = _make_registry(handler_cls)
        config = _make_config("pre_tool_use", {})
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown()
        assert "ADVISORY" in output

    def test_context_tag_maps_to_context_behavior(self) -> None:
        """Handlers with context-injection tag should show CONTEXT behavior."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handler_cls = _make_handler_class(
            name="context-handler",
            priority=50,
            tags=["context-injection"],
            module_name="claude_code_hooks_daemon.handlers.session_start.ctx",
        )
        registry = _make_registry(handler_cls)
        config = _make_config("session_start", {})
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown()
        assert "CONTEXT" in output

    def test_no_behavior_tag_shows_handler_terminal_status(self) -> None:
        """Handlers without behavior tags should fall back to terminal/non-terminal."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handler_cls = _make_handler_class(
            name="plain-handler",
            priority=50,
            tags=["safety"],
            terminal=True,
            module_name="claude_code_hooks_daemon.handlers.pre_tool_use.plain",
        )
        registry = _make_registry(handler_cls)
        config = _make_config("pre_tool_use", {})
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown()
        # Should show TERMINAL as fallback
        assert "TERMINAL" in output


class TestDocsGeneratorEmptyEventTypes:
    """Tests for event types with no handlers."""

    def test_empty_event_types_not_shown(self) -> None:
        """Event types with no enabled handlers should not appear."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        registry = _make_registry()
        gen = DocsGenerator(config={}, registry=registry)
        output = gen.generate_markdown()
        # No handler event type headings should appear
        assert "### PreToolUse" not in output
        assert "### PostToolUse" not in output

    def test_active_handlers_section_heading_present(self) -> None:
        """Output should have an Active Handlers section heading."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handler_cls = _make_handler_class(
            name="test-handler",
            priority=10,
            tags=["blocking"],
            module_name="claude_code_hooks_daemon.handlers.pre_tool_use.test_handler",
        )
        registry = _make_registry(handler_cls)
        config = _make_config("pre_tool_use", {})
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown()
        assert "## Active Handlers" in output


class TestDocsGeneratorMultipleEventTypes:
    """Tests for output with handlers across multiple event types."""

    def test_multiple_event_types_rendered(self) -> None:
        """Handlers from different event types should each get their own section."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        pre_handler = _make_handler_class(
            name="pre-handler",
            priority=10,
            tags=["blocking"],
            docstring="Pre tool use handler.",
            module_name="claude_code_hooks_daemon.handlers.pre_tool_use.pre_handler",
        )
        post_handler = _make_handler_class(
            name="post-handler",
            priority=20,
            tags=["advisory"],
            docstring="Post tool use handler.",
            module_name="claude_code_hooks_daemon.handlers.post_tool_use.post_handler",
        )
        registry = _make_registry(pre_handler, post_handler)
        config: dict[str, Any] = {"pre_tool_use": {}, "post_tool_use": {}}
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown()
        assert "### PreToolUse" in output
        assert "### PostToolUse" in output


class TestDocsGeneratorProjectHandlers:
    """Tests for project handler inclusion."""

    def test_project_handlers_appear_in_output(self) -> None:
        """Project handlers should appear in the generated docs."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        # Create a mock project handler instance (not a class)
        handler_instance = _make_handler_class(
            name="my-project-handler",
            priority=45,
            tags=["advisory"],
            docstring="Custom project handler for validation.",
            module_name="project_handlers.pre_tool_use.my_handler",
        )()

        registry = _make_registry()
        gen = DocsGenerator(
            config={"pre_tool_use": {}},
            registry=registry,
            project_handlers=[handler_instance],
        )
        output = gen.generate_markdown()
        assert "Custom project handler for validation" in output
        assert "45" in output

    def test_plugin_handlers_appear_in_output(self) -> None:
        """Plugin handlers should appear in the generated docs."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handler_instance = _make_handler_class(
            name="my-plugin",
            priority=30,
            tags=["blocking"],
            docstring="Plugin handler for security.",
            module_name="plugins.pre_tool_use.security",
        )()

        registry = _make_registry()
        gen = DocsGenerator(
            config={"pre_tool_use": {}},
            registry=registry,
            plugins=[handler_instance],
        )
        output = gen.generate_markdown()
        assert "Plugin handler for security" in output
        assert "30" in output
