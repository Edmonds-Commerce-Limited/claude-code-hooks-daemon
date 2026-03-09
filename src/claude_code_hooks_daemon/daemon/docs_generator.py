"""Documentation generator for hooks daemon configuration.

Generates .claude/HOOKS-DAEMON.md from live config and handler metadata.
This provides agents with an accurate, auto-generated summary of active
handlers, plan mode settings, and configuration reference.
"""

from __future__ import annotations

import inspect
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from claude_code_hooks_daemon.constants import ConfigKey
from claude_code_hooks_daemon.handlers.registry import EVENT_TYPE_MAPPING

if TYPE_CHECKING:
    from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

logger = logging.getLogger(__name__)

# Behavior tag constants for classification
_BEHAVIOR_BLOCKING = "blocking"
_BEHAVIOR_ADVISORY = "advisory"
_BEHAVIOR_CONTEXT = "context-injection"

# Config keys for plan mode detection
_MARKDOWN_ORGANIZATION_KEY = "markdown_organization"
_TRACK_PLANS_KEY = "track_plans_in_project"
_PLAN_WORKFLOW_DOCS_KEY = "plan_workflow_docs"
_OPTIONS_KEY = "options"

# Type alias for collected handler data:
# (handler_name, config_key, event_type_str, priority, behavior, description, is_enabled)
CollectedHandler = tuple[str, str, str, int, str, str, bool]


class DocsGenerator:
    """Generate .claude/HOOKS-DAEMON.md from live config and handler metadata."""

    __slots__ = ("_config", "_plugins", "_project_handlers", "_registry")

    def __init__(
        self,
        config: dict[str, Any],
        registry: HandlerRegistry,
        plugins: list[Any] | None = None,
        project_handlers: list[Any] | None = None,
    ) -> None:
        """Initialize docs generator.

        Args:
            config: Configuration dictionary (handlers section from hooks-daemon.yaml)
            registry: Handler registry with discovered handlers
            plugins: Optional list of plugin handler instances
            project_handlers: Optional list of project handler instances
        """
        self._config = config
        self._registry = registry
        self._plugins = plugins or []
        self._project_handlers = project_handlers or []

    def generate_markdown(self, include_disabled: bool = False) -> str:
        """Generate documentation markdown from live config and handlers.

        Args:
            include_disabled: Include disabled handlers in output

        Returns:
            Complete markdown document string
        """
        sections: list[str] = []

        sections.append(self._render_header())

        plan_section = self._render_plan_mode_section()
        if plan_section:
            sections.append(plan_section)

        handlers_section = self._render_handlers_section(include_disabled)
        if handlers_section:
            sections.append(handlers_section)

        sections.append(self._render_config_reference())

        return "\n\n".join(sections) + "\n"

    def _render_header(self) -> str:
        """Render document header with version and timestamp."""
        from claude_code_hooks_daemon.version import __version__

        today = datetime.now().strftime("%Y-%m-%d")
        return (
            "# Hooks Daemon - Active Configuration\n\n"
            f"> Generated on {today} (v{__version__}) by `generate-docs`. "
            "Regenerate: `$PYTHON -m claude_code_hooks_daemon.daemon.cli generate-docs`"
        )

    def _render_plan_mode_section(self) -> str | None:
        """Render plan mode section if track_plans_in_project is configured.

        Returns:
            Plan mode markdown section, or None if not configured.
        """
        plan_path = self._get_plan_tracking_path()
        if not plan_path:
            return None

        workflow_docs = self._get_plan_workflow_docs()
        workflow_line = ""
        if workflow_docs:
            workflow_line = f"\n**Workflow docs**: @{workflow_docs}"

        return (
            "## Plan Mode\n\n"
            "> Write plans DIRECTLY to project version control.\n\n"
            f"**Plan location**: `{plan_path}/{{number}}-{{name}}/PLAN.md`\n"
            f"**Next number**: Scan `{plan_path}/` (including `Completed/`) "
            f"for highest number, increment.{workflow_line}\n\n"
            "The redirect handler intercepts `~/.claude/plans/` writes as a safety net only."
        )

    def _render_handlers_section(self, include_disabled: bool = False) -> str | None:
        """Render active handlers grouped by event type.

        Args:
            include_disabled: Include disabled handlers

        Returns:
            Handlers markdown section, or None if no handlers found.
        """
        handlers_by_event: dict[str, list[CollectedHandler]] = {}
        self._collect_handlers(handlers_by_event, include_disabled)

        if not handlers_by_event:
            return None

        lines: list[str] = ["## Active Handlers"]

        # Render known event types in canonical order
        rendered_keys: set[str] = set()
        for event_dir_name, event_type in EVENT_TYPE_MAPPING.items():
            event_handlers = handlers_by_event.get(event_dir_name, [])
            if not event_handlers:
                continue
            rendered_keys.add(event_dir_name)
            self._render_handler_table(lines, event_type.value, event_handlers)

        # Render any extra keys (plugin/project handlers with unknown event types)
        for extra_key in sorted(handlers_by_event.keys() - rendered_keys):
            extra_handlers = handlers_by_event[extra_key]
            if extra_handlers:
                heading = extra_key.replace("_", " ").title()
                self._render_handler_table(lines, heading, extra_handlers)

        return "\n".join(lines)

    @staticmethod
    def _render_handler_table(
        lines: list[str], heading: str, handlers: list[CollectedHandler]
    ) -> None:
        """Render a handler table for one event type section.

        Args:
            lines: Output lines list to append to
            heading: Section heading (e.g., "PreToolUse")
            handlers: Handler info tuples for this section
        """
        handlers.sort(key=lambda h: h[3])
        count = len(handlers)
        count_label = f"{count} handler{'s' if count != 1 else ''}"
        lines.append(f"\n### {heading} ({count_label})\n")
        lines.append("| Priority | Handler | Behavior | Description |")
        lines.append("|----------|---------|----------|-------------|")

        for handler_info in handlers:
            _name, config_key, _evt, priority, behavior, description, _enabled = handler_info
            lines.append(f"| {priority} | {config_key} | {behavior} | {description} |")

    def _render_config_reference(self) -> str:
        """Render quick config reference section."""
        return (
            "## Quick Config Reference\n\n"
            "**Config file**: `.claude/hooks-daemon.yaml`\n"
            "**Enable/disable**: Set `enabled: true/false` under handler name\n"
            "**Handler options**: Set under `options:` key per handler"
        )

    def _collect_handlers(
        self,
        handlers_by_event: dict[str, list[CollectedHandler]],
        include_disabled: bool,
    ) -> None:
        """Collect handler metadata from registry, plugins, and project handlers.

        Args:
            handlers_by_event: Dict to populate, keyed by event directory name
            include_disabled: Include disabled handlers
        """
        from claude_code_hooks_daemon.handlers.registry import _to_snake_case

        for event_dir_name in EVENT_TYPE_MAPPING:
            event_config = self._config.get(event_dir_name, {})

            for handler_class_name in self._registry.list_handlers():
                handler_class = self._registry.get_handler_class(handler_class_name)
                if not handler_class:
                    continue

                if event_dir_name not in handler_class.__module__:
                    continue

                config_key = _to_snake_case(handler_class_name)
                handler_config = event_config.get(config_key, {})
                is_enabled = handler_config.get(ConfigKey.ENABLED, True)

                if not is_enabled and not include_disabled:
                    continue

                try:
                    instance = handler_class()
                    priority = handler_config.get(ConfigKey.PRIORITY, instance.priority)
                    behavior = self._detect_behavior(instance)
                    description = self._get_description(handler_class)

                    handler_info: CollectedHandler = (
                        handler_class_name,
                        config_key,
                        event_dir_name,
                        priority,
                        behavior,
                        description,
                        is_enabled,
                    )

                    if event_dir_name not in handlers_by_event:
                        handlers_by_event[event_dir_name] = []
                    handlers_by_event[event_dir_name].append(handler_info)

                except Exception as e:
                    logger.warning("Failed to inspect handler %s: %s", handler_class_name, e)

        # Collect from plugin handlers
        for plugin_handler in self._plugins:
            try:
                handler_name = plugin_handler.__class__.__name__
                event_type_str = getattr(plugin_handler, "event_type", None)
                if hasattr(event_type_str, "value"):
                    event_type_str = event_type_str.value
                # Find matching event dir name
                event_dir = self._event_type_to_dir(event_type_str) or "plugin"
                behavior = self._detect_behavior(plugin_handler)
                description = self._get_description(type(plugin_handler))

                handler_info = (
                    handler_name,
                    handler_name,
                    event_dir,
                    plugin_handler.priority,
                    behavior,
                    description,
                    True,
                )
                if event_dir not in handlers_by_event:
                    handlers_by_event[event_dir] = []
                handlers_by_event[event_dir].append(handler_info)
            except Exception as e:
                logger.warning("Failed to inspect plugin handler: %s", e)

        # Collect from project handlers
        for project_handler in self._project_handlers:
            try:
                handler_name = project_handler.__class__.__name__
                event_type_str = getattr(project_handler, "event_type", None)
                if hasattr(event_type_str, "value"):
                    event_type_str = event_type_str.value
                # Try module path for event type detection
                module = getattr(project_handler, "__module__", "") or ""
                event_dir = self._event_type_to_dir(event_type_str)
                if not event_dir:
                    # Fall back to module path detection
                    for dir_name in EVENT_TYPE_MAPPING:
                        if dir_name in module:
                            event_dir = dir_name
                            break
                event_dir = event_dir or "project"

                behavior = self._detect_behavior(project_handler)
                description = self._get_description(type(project_handler))

                handler_info = (
                    handler_name,
                    handler_name,
                    event_dir,
                    project_handler.priority,
                    behavior,
                    description,
                    True,
                )
                if event_dir not in handlers_by_event:
                    handlers_by_event[event_dir] = []
                handlers_by_event[event_dir].append(handler_info)
            except Exception as e:
                logger.warning("Failed to inspect project handler: %s", e)

    @staticmethod
    def _event_type_to_dir(event_type_value: str | None) -> str | None:
        """Map an EventType value back to its directory name.

        Args:
            event_type_value: EventType string value (e.g., "PreToolUse")

        Returns:
            Directory name (e.g., "pre_tool_use"), or None if not found.
        """
        if not event_type_value:
            return None
        for dir_name, event_type in EVENT_TYPE_MAPPING.items():
            if event_type.value == event_type_value:
                return dir_name
        return None

    @staticmethod
    def _detect_behavior(instance: Any) -> str:
        """Detect handler behavior from its tags.

        Priority order: BLOCKING > ADVISORY > CONTEXT > TERMINAL/NON-TERMINAL

        Args:
            instance: Handler instance

        Returns:
            Behavior string (e.g., "BLOCKING", "ADVISORY", "CONTEXT", "TERMINAL")
        """
        tags = getattr(instance, "tags", []) or []

        if _BEHAVIOR_BLOCKING in tags:
            return "BLOCKING"
        if _BEHAVIOR_ADVISORY in tags:
            return "ADVISORY"
        if _BEHAVIOR_CONTEXT in tags:
            return "CONTEXT"

        # Fallback to terminal status
        terminal = getattr(instance, "terminal", True)
        return "TERMINAL" if terminal else "NON-TERMINAL"

    @staticmethod
    def _get_description(handler_class: type) -> str:
        """Get handler description from class docstring.

        Uses first line of docstring via inspect.getdoc().

        Args:
            handler_class: Handler class

        Returns:
            First line of docstring, or empty string if no docstring.
        """
        doc = inspect.getdoc(handler_class)
        if not doc:
            return ""
        # Return first line only
        return doc.split("\n")[0].rstrip(".")

    def _get_plan_tracking_path(self) -> str | None:
        """Extract track_plans_in_project from config.

        Checks both post_tool_use.markdown_organization and
        pre_tool_use.plan_number_helper for the setting.

        Returns:
            Plan tracking path string, or None if not configured.
        """
        for event_type_key in ("post_tool_use", "pre_tool_use"):
            event_config = self._config.get(event_type_key, {})

            # Check markdown_organization handler
            md_org = event_config.get(_MARKDOWN_ORGANIZATION_KEY, {})
            options = md_org.get(_OPTIONS_KEY, {})
            plan_path = options.get(_TRACK_PLANS_KEY)
            if plan_path:
                return str(plan_path)

            # Check plan_number_helper handler
            plan_helper = event_config.get("plan_number_helper", {})
            helper_options = plan_helper.get(_OPTIONS_KEY, {})
            plan_path = helper_options.get(_TRACK_PLANS_KEY)
            if plan_path:
                return str(plan_path)

        return None

    def _get_plan_workflow_docs(self) -> str | None:
        """Extract plan_workflow_docs from config.

        Returns:
            Path to workflow docs, or None if not configured.
        """
        for event_type_key in ("post_tool_use", "pre_tool_use"):
            event_config = self._config.get(event_type_key, {})
            md_org = event_config.get(_MARKDOWN_ORGANIZATION_KEY, {})
            options = md_org.get(_OPTIONS_KEY, {})
            workflow_docs = options.get(_PLAN_WORKFLOW_DOCS_KEY)
            if workflow_docs:
                return str(workflow_docs)

        return None
