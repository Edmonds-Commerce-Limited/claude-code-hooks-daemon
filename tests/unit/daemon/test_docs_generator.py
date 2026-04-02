"""Tests for DocsGenerator - generates .claude/HOOKS-DAEMON.md from live config.

TDD RED phase: These tests define the expected behavior of the DocsGenerator.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

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

        def get_claude_md(self) -> str | None:
            return None

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


# --- Additional helper factories ---


def _make_handler_instance_without_event_type(
    name: str,
    priority: int,
    tags: list[str],
    docstring: str,
    module_name: str,
) -> Any:
    """Create a handler instance that has no event_type attribute.

    Uses a subclass so that deleting the attribute works cleanly at the
    instance level without affecting the base Handler class.
    """
    from claude_code_hooks_daemon.core import Handler, HookResult

    class _NoEventTypeHandler(Handler):
        __doc__ = docstring

        def __init__(self) -> None:
            super().__init__(name=name, priority=priority, terminal=True, tags=tags)
            # Remove event_type if the base class ever sets one
            if hasattr(self, "event_type"):
                object.__delattr__(self, "event_type")

        def matches(self, hook_input: dict[str, Any]) -> bool:
            return True

        def handle(self, hook_input: dict[str, Any]) -> HookResult:
            return HookResult()

        def get_claude_md(self) -> str | None:
            return None

        def get_acceptance_tests(self) -> list[Any]:
            return []

    _NoEventTypeHandler.__module__ = module_name
    _NoEventTypeHandler.__name__ = name.title().replace("-", "") + "Handler"
    _NoEventTypeHandler.__qualname__ = _NoEventTypeHandler.__name__
    return _NoEventTypeHandler()


class _BrokenPriorityHandler:
    """A mock handler whose .priority property raises RuntimeError.

    Used to test exception handling during plugin/project handler inspection.
    """

    __module__ = "tests.broken_handler"

    @property
    def priority(self) -> int:
        raise RuntimeError("priority access failed")

    @property
    def tags(self) -> list[str]:
        return []

    @property
    def terminal(self) -> bool:
        return True

    def event_type_value(self) -> str:
        return "PreToolUse"


class TestDocsGeneratorPlanModeWorkflowDocs:
    """Tests for the workflow_docs line in plan mode (line 113)."""

    def test_plan_mode_includes_workflow_docs_link_when_configured(self) -> None:
        """Plan mode section should include workflow docs link when plan_workflow_docs is set."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        registry = _make_registry()
        config: dict[str, Any] = {
            "post_tool_use": {
                "markdown_organization": {
                    "enabled": True,
                    "options": {
                        "track_plans_in_project": "CLAUDE/Plan",
                        "plan_workflow_docs": "CLAUDE/PlanWorkflow.md",
                    },
                },
            },
        }
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown()
        assert "## Plan Mode" in output
        assert "**Workflow docs**" in output
        assert "@CLAUDE/PlanWorkflow.md" in output

    def test_plan_mode_has_no_workflow_docs_line_when_not_configured(self) -> None:
        """Plan mode section should have no workflow docs line when plan_workflow_docs absent."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        registry = _make_registry()
        config: dict[str, Any] = {
            "post_tool_use": {
                "markdown_organization": {
                    "enabled": True,
                    "options": {
                        "track_plans_in_project": "CLAUDE/Plan",
                    },
                },
            },
        }
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown()
        assert "## Plan Mode" in output
        assert "**Workflow docs**" not in output

    def test_plan_workflow_docs_from_pre_tool_use_branch(self) -> None:
        """_get_plan_workflow_docs should read from pre_tool_use when post_tool_use has no match."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        registry = _make_registry()
        config: dict[str, Any] = {
            "pre_tool_use": {
                "markdown_organization": {
                    "enabled": True,
                    "options": {
                        "track_plans_in_project": "CLAUDE/Plan",
                        "plan_workflow_docs": "CLAUDE/PlanWorkflow.md",
                    },
                },
            },
        }
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown()
        assert "## Plan Mode" in output
        assert "@CLAUDE/PlanWorkflow.md" in output


class TestDocsGeneratorPlanTrackingFromPlanNumberHelper:
    """Tests for _get_plan_tracking_path reading from plan_number_helper (line 397)."""

    def test_plan_tracking_path_from_plan_number_helper_post_tool_use(self) -> None:
        """_get_plan_tracking_path should read from plan_number_helper in post_tool_use."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        registry = _make_registry()
        config: dict[str, Any] = {
            "post_tool_use": {
                "plan_number_helper": {
                    "enabled": True,
                    "options": {
                        "track_plans_in_project": "PLANS",
                    },
                },
            },
        }
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown()
        assert "## Plan Mode" in output
        assert "PLANS" in output

    def test_plan_tracking_path_from_plan_number_helper_pre_tool_use(self) -> None:
        """_get_plan_tracking_path should read from plan_number_helper in pre_tool_use."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        registry = _make_registry()
        config: dict[str, Any] = {
            "pre_tool_use": {
                "plan_number_helper": {
                    "enabled": True,
                    "options": {
                        "track_plans_in_project": "MYPLANS",
                    },
                },
            },
        }
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown()
        assert "## Plan Mode" in output
        assert "MYPLANS" in output


class TestDocsGeneratorExtractEventTypeStr:
    """Tests for _extract_event_type_str static method (lines 196-198)."""

    def test_extract_event_type_str_returns_none_when_no_event_type(self) -> None:
        """Returns None when handler has no event_type attribute."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handler = MagicMock(spec=[])  # no attributes at all
        result = DocsGenerator._extract_event_type_str(handler)
        assert result is None

    def test_extract_event_type_str_uses_value_attribute_when_present(self) -> None:
        """Returns str(raw.value) when event_type has a .value attribute."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        mock_event_type = MagicMock()
        mock_event_type.value = "PreToolUse"
        handler = MagicMock()
        handler.event_type = mock_event_type
        result = DocsGenerator._extract_event_type_str(handler)
        assert result == "PreToolUse"

    def test_extract_event_type_str_uses_str_when_no_value_attribute(self) -> None:
        """Returns str(raw) when event_type has no .value attribute (plain string)."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handler = MagicMock()
        handler.event_type = "PostToolUse"
        result = DocsGenerator._extract_event_type_str(handler)
        assert result == "PostToolUse"


class TestDocsGeneratorEventTypeToDir:
    """Tests for _event_type_to_dir static method (lines 325-328)."""

    def test_event_type_to_dir_returns_none_for_none_input(self) -> None:
        """Returns None when event_type_value is None."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        assert DocsGenerator._event_type_to_dir(None) is None

    def test_event_type_to_dir_returns_none_for_empty_string(self) -> None:
        """Returns None when event_type_value is empty string."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        assert DocsGenerator._event_type_to_dir("") is None

    def test_event_type_to_dir_maps_pre_tool_use_value_to_dir(self) -> None:
        """Returns 'pre_tool_use' for PreToolUse value."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        result = DocsGenerator._event_type_to_dir("PreToolUse")
        assert result == "pre_tool_use"

    def test_event_type_to_dir_maps_post_tool_use_value_to_dir(self) -> None:
        """Returns 'post_tool_use' for PostToolUse value."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        result = DocsGenerator._event_type_to_dir("PostToolUse")
        assert result == "post_tool_use"

    def test_event_type_to_dir_returns_none_for_unknown_value(self) -> None:
        """Returns None for unknown event type values."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        assert DocsGenerator._event_type_to_dir("UnknownEventType") is None


class TestDocsGeneratorDetectBehaviorFallback:
    """Tests for _detect_behavior NON-TERMINAL fallback (line 369)."""

    def test_detect_behavior_returns_non_terminal_for_non_terminal_handler(self) -> None:
        """Returns NON-TERMINAL when terminal=False and no behavior tags."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        instance = MagicMock()
        instance.tags = []
        instance.terminal = False
        result = DocsGenerator._detect_behavior(instance)
        assert result == "NON-TERMINAL"

    def test_detect_behavior_returns_terminal_when_terminal_true_and_no_tags(self) -> None:
        """Returns TERMINAL when terminal=True and no behavior tags."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        instance = MagicMock()
        instance.tags = []
        instance.terminal = True
        result = DocsGenerator._detect_behavior(instance)
        assert result == "TERMINAL"

    def test_non_terminal_handler_shown_in_output(self) -> None:
        """NON-TERMINAL behavior should appear in generated docs for non-terminal handlers."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handler_cls = _make_handler_class(
            name="non-terminal-handler",
            priority=5,
            tags=[],
            terminal=False,
            module_name="claude_code_hooks_daemon.handlers.post_tool_use.non_terminal",
        )
        registry = _make_registry(handler_cls)
        config = _make_config("post_tool_use", {})
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown()
        assert "NON-TERMINAL" in output


class TestDocsGeneratorHandlerClassNone:
    """Tests for handler_class is None branch in _collect_handlers (line 219)."""

    def test_none_handler_class_is_skipped_gracefully(self) -> None:
        """When registry.get_handler_class returns None, that handler is silently skipped."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        registry = MagicMock()
        registry.list_handlers.return_value = ["NonExistentHandler"]
        registry.get_handler_class.return_value = None
        gen = DocsGenerator(config={}, registry=registry)
        # Should not raise and should produce valid output
        output = gen.generate_markdown()
        assert "# Hooks Daemon" in output
        # No handler table should appear since the only handler was None
        assert "## Active Handlers" not in output


class TestDocsGeneratorDisabledHandlerBranch:
    """Tests for disabled handler excluded when include_disabled=False (line 229)."""

    def test_handler_with_enabled_false_excluded_from_default_output(self) -> None:
        """Handler configured as enabled=False is excluded when include_disabled=False."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handler_cls = _make_handler_class(
            name="off-handler",
            priority=10,
            tags=["blocking"],
            docstring="This handler is disabled.",
            module_name="claude_code_hooks_daemon.handlers.pre_tool_use.off_handler",
        )
        registry = _make_registry(handler_cls)
        # The config key is the snake_case of the class name with _handler suffix removed
        # Class name is "OffHandlerHandler", snake_case = "off_handler"
        config = _make_config(
            "pre_tool_use",
            {"off_handler": {"enabled": False}},
        )
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown(include_disabled=False)
        assert "This handler is disabled" not in output


class TestDocsGeneratorInspectionExceptions:
    """Tests for exception handling during handler inspection (lines 251-252, 276-277, 310-311)."""

    def test_exception_during_registry_handler_instantiation_is_swallowed(self) -> None:
        """Exception raised when instantiating a registry handler is caught and logged."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        class _BrokenHandler:
            """A handler class whose constructor raises."""

            __module__ = "claude_code_hooks_daemon.handlers.pre_tool_use.broken"
            __name__ = "BrokenHandler"

            def __init__(self) -> None:
                raise RuntimeError("instantiation failed")

        registry = MagicMock()
        registry.list_handlers.return_value = ["BrokenHandler"]
        registry.get_handler_class.return_value = _BrokenHandler

        gen = DocsGenerator(config={"pre_tool_use": {}}, registry=registry)
        # Should not raise
        output = gen.generate_markdown()
        assert "# Hooks Daemon" in output

    def test_exception_during_plugin_handler_inspection_is_swallowed(self) -> None:
        """Exception raised while inspecting a plugin handler is caught and logged."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        gen = DocsGenerator(
            config={},
            registry=_make_registry(),
            plugins=[_BrokenPriorityHandler()],
        )
        # Should not raise
        output = gen.generate_markdown()
        assert "# Hooks Daemon" in output

    def test_exception_during_project_handler_inspection_is_swallowed(self) -> None:
        """Exception raised while inspecting a project handler is caught and logged."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        gen = DocsGenerator(
            config={},
            registry=_make_registry(),
            project_handlers=[_BrokenPriorityHandler()],
        )
        # Should not raise
        output = gen.generate_markdown()
        assert "# Hooks Daemon" in output


class TestDocsGeneratorPluginHandlerEventDir:
    """Tests for plugin handler event dir resolution (lines 276-277 branch coverage)."""

    def test_plugin_handler_with_known_event_type_value_uses_correct_section(self) -> None:
        """Plugin handler with a known EventType value is placed in the right section."""
        from claude_code_hooks_daemon.core.event import EventType
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handler_instance = _make_handler_class(
            name="plugin-pre",
            priority=10,
            tags=["blocking"],
            docstring="Plugin in pre_tool_use section.",
            module_name="plugins.pre_tool_use.plugin_pre",
        )()
        # Attach event_type with .value to exercise the hasattr(raw, "value") branch
        object.__setattr__(handler_instance, "event_type", EventType.PRE_TOOL_USE)

        registry = _make_registry()
        gen = DocsGenerator(config={}, registry=registry, plugins=[handler_instance])
        output = gen.generate_markdown()
        assert "Plugin in pre_tool_use section" in output
        assert "### PreToolUse" in output

    def test_plugin_handler_with_unknown_event_type_falls_back_to_plugin_section(self) -> None:
        """Plugin handler with no recognised event_type goes into 'plugin' section."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handler_instance = _make_handler_instance_without_event_type(
            name="unknown-plugin",
            priority=5,
            tags=["advisory"],
            docstring="Plugin with unknown event type.",
            module_name="plugins.unknown.handler",
        )

        registry = _make_registry()
        gen = DocsGenerator(config={}, registry=registry, plugins=[handler_instance])
        output = gen.generate_markdown()
        assert "Plugin with unknown event type" in output
        # The heading will be "Plugin" (extra_key branch)
        assert "Plugin" in output


class TestDocsGeneratorProjectHandlerEventDirFallback:
    """Tests for project handler module-path event dir fallback (lines 287-293 branch coverage)."""

    def test_project_handler_falls_back_to_module_path_detection(self) -> None:
        """Project handler uses module path to determine event dir when event_type is None."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handler_instance = _make_handler_instance_without_event_type(
            name="proj-handler",
            priority=20,
            tags=["advisory"],
            docstring="Project handler via module path.",
            module_name="myproject.pre_tool_use.proj_handler",
        )

        registry = _make_registry()
        gen = DocsGenerator(
            config={},
            registry=registry,
            project_handlers=[handler_instance],
        )
        output = gen.generate_markdown()
        assert "Project handler via module path" in output
        assert "### PreToolUse" in output

    def test_project_handler_falls_back_to_project_section_when_module_unknown(self) -> None:
        """Project handler goes into 'project' section when both event_type and module path fail."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handler_instance = _make_handler_instance_without_event_type(
            name="orphan-handler",
            priority=99,
            tags=["advisory"],
            docstring="Orphan project handler.",
            module_name="completely.unknown.module",
        )

        registry = _make_registry()
        gen = DocsGenerator(
            config={},
            registry=registry,
            project_handlers=[handler_instance],
        )
        output = gen.generate_markdown()
        assert "Orphan project handler" in output


class TestDocsGeneratorGenerateOrchestration:
    """Tests for generate_markdown orchestration (line 413)."""

    def test_generate_markdown_returns_string_ending_with_newline(self) -> None:
        """generate_markdown output always ends with a newline."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        registry = _make_registry()
        gen = DocsGenerator(config={}, registry=registry)
        output = gen.generate_markdown()
        assert output.endswith("\n")

    def test_generate_markdown_with_all_sections_present(self) -> None:
        """generate_markdown with plan mode, handlers, and config sections all present."""
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handler_cls = _make_handler_class(
            name="full-handler",
            priority=15,
            tags=["blocking"],
            docstring="Full integration handler.",
            module_name="claude_code_hooks_daemon.handlers.pre_tool_use.full_handler",
        )
        registry = _make_registry(handler_cls)
        config: dict[str, Any] = {
            "pre_tool_use": {
                "markdown_organization": {
                    "enabled": True,
                    "options": {
                        "track_plans_in_project": "CLAUDE/Plan",
                        "plan_workflow_docs": "CLAUDE/PlanWorkflow.md",
                    },
                },
            },
        }
        gen = DocsGenerator(config=config, registry=registry)
        output = gen.generate_markdown()
        # All four sections should be present
        assert "# Hooks Daemon - Active Configuration" in output
        assert "## Plan Mode" in output
        assert "## Active Handlers" in output
        assert "## Quick Config Reference" in output
