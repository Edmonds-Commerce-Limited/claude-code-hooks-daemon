"""Config differ for comparing user config against default/example config.

Identifies user customizations (added handlers, changed priorities, custom options,
plugins) by comparing against the version's example config. Used during upgrades
to preserve user settings when merging with new default configs.

Decision: Key-based diff against example config (Plan 00041 Decision 2).
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConfigDiff:
    """Structured diff between user config and default config.

    Attributes:
        added_handlers: Handlers added by user, keyed by event_type -> handler_name -> config
        removed_handlers: Handlers in default but removed by user, keyed by event_type -> handler_name -> config
        changed_priorities: Priority changes, keyed by event_type -> handler_name -> {old, new}
        changed_options: Option changes (enabled, options dict), keyed by event_type -> handler_name -> field -> {old, new}
        custom_daemon_settings: Daemon settings that differ from defaults
        custom_plugins: Plugin configs added by user
    """

    added_handlers: dict[str, dict[str, Any]] = field(default_factory=dict)
    removed_handlers: dict[str, dict[str, Any]] = field(default_factory=dict)
    changed_priorities: dict[str, dict[str, Any]] = field(default_factory=dict)
    changed_options: dict[str, dict[str, Any]] = field(default_factory=dict)
    custom_daemon_settings: dict[str, Any] = field(default_factory=dict)
    custom_plugins: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        """Return True if any customizations were detected."""
        return bool(
            self.added_handlers
            or self.removed_handlers
            or self.changed_priorities
            or self.changed_options
            or self.custom_daemon_settings
            or self.custom_plugins
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize diff to a dictionary for JSON output.

        Returns:
            Dictionary representation of the diff.
        """
        return {
            "added_handlers": self.added_handlers,
            "removed_handlers": self.removed_handlers,
            "changed_priorities": self.changed_priorities,
            "changed_options": self.changed_options,
            "custom_daemon_settings": self.custom_daemon_settings,
            "custom_plugins": self.custom_plugins,
            "has_changes": self.has_changes,
        }


class ConfigDiffer:
    """Compares user config against default/example config to extract customizations.

    Used during upgrades to identify what the user has changed so those
    changes can be preserved when merging with a new default config.
    """

    def diff(
        self,
        user_config: dict[str, Any],
        default_config: dict[str, Any],
    ) -> ConfigDiff:
        """Compare user config against default config and return structured diff.

        Args:
            user_config: The user's current configuration (dict from YAML)
            default_config: The default/example configuration for the version

        Returns:
            ConfigDiff with all detected customizations
        """
        result = ConfigDiff()

        self._diff_daemon_settings(user_config, default_config, result)
        self._diff_handlers(user_config, default_config, result)
        self._diff_plugins(user_config, default_config, result)

        return result

    def _diff_daemon_settings(
        self,
        user_config: dict[str, Any],
        default_config: dict[str, Any],
        result: ConfigDiff,
    ) -> None:
        """Extract daemon settings that differ from defaults.

        Args:
            user_config: User's config dict
            default_config: Default config dict
            result: ConfigDiff to populate
        """
        user_daemon = user_config.get("daemon", {})
        default_daemon = default_config.get("daemon", {})

        if not isinstance(user_daemon, dict) or not isinstance(default_daemon, dict):
            return

        for key, user_value in user_daemon.items():
            default_value = default_daemon.get(key)
            if user_value != default_value:
                result.custom_daemon_settings[key] = user_value

    def _diff_handlers(
        self,
        user_config: dict[str, Any],
        default_config: dict[str, Any],
        result: ConfigDiff,
    ) -> None:
        """Extract handler customizations across all event types.

        Args:
            user_config: User's config dict
            default_config: Default config dict
            result: ConfigDiff to populate
        """
        user_handlers = user_config.get("handlers", {})
        default_handlers = default_config.get("handlers", {})

        if not isinstance(user_handlers, dict) or not isinstance(default_handlers, dict):
            return

        # Collect all event types from both configs
        all_event_types = set(user_handlers.keys()) | set(default_handlers.keys())

        for event_type in all_event_types:
            user_event = user_handlers.get(event_type, {})
            default_event = default_handlers.get(event_type, {})

            if not isinstance(user_event, dict):
                user_event = {}
            if not isinstance(default_event, dict):
                default_event = {}

            self._diff_event_handlers(event_type, user_event, default_event, result)

    def _diff_event_handlers(
        self,
        event_type: str,
        user_event: dict[str, Any],
        default_event: dict[str, Any],
        result: ConfigDiff,
    ) -> None:
        """Diff handlers within a single event type.

        Args:
            event_type: Event type name (e.g., 'pre_tool_use')
            user_event: User's handlers for this event type
            default_event: Default handlers for this event type
            result: ConfigDiff to populate
        """
        user_handler_names = set(user_event.keys())
        default_handler_names = set(default_event.keys())

        # Added handlers: in user but not in default
        added = user_handler_names - default_handler_names
        if added:
            if event_type not in result.added_handlers:
                result.added_handlers[event_type] = {}
            for name in added:
                result.added_handlers[event_type][name] = user_event[name]

        # Removed handlers: in default but not in user
        removed = default_handler_names - user_handler_names
        if removed:
            if event_type not in result.removed_handlers:
                result.removed_handlers[event_type] = {}
            for name in removed:
                result.removed_handlers[event_type][name] = default_event[name]

        # Changed handlers: in both, check for differences
        common = user_handler_names & default_handler_names
        for name in common:
            user_handler = user_event[name]
            default_handler = default_event[name]

            if not isinstance(user_handler, dict):
                user_handler = {}
            if not isinstance(default_handler, dict):
                default_handler = {}

            self._diff_single_handler(event_type, name, user_handler, default_handler, result)

    def _diff_single_handler(
        self,
        event_type: str,
        handler_name: str,
        user_handler: dict[str, Any],
        default_handler: dict[str, Any],
        result: ConfigDiff,
    ) -> None:
        """Diff a single handler's configuration.

        Args:
            event_type: Event type name
            handler_name: Handler name
            user_handler: User's handler config
            default_handler: Default handler config
            result: ConfigDiff to populate
        """
        # Check priority changes
        user_priority = user_handler.get("priority")
        default_priority = default_handler.get("priority")
        if user_priority is not None and default_priority is not None:
            if user_priority != default_priority:
                if event_type not in result.changed_priorities:
                    result.changed_priorities[event_type] = {}
                result.changed_priorities[event_type][handler_name] = {
                    "old": default_priority,
                    "new": user_priority,
                }

        # Check other option changes (enabled, options, etc.)
        option_changes: dict[str, Any] = {}
        all_keys = set(user_handler.keys()) | set(default_handler.keys())

        for key in all_keys:
            # Priority is tracked separately
            if key == "priority":
                continue

            user_value = user_handler.get(key)
            default_value = default_handler.get(key)

            if user_value != default_value:
                # For nested dicts (like options), diff the individual keys
                if isinstance(user_value, dict) and isinstance(default_value, dict):
                    nested_changes: dict[str, Any] = {}
                    nested_keys = set(user_value.keys()) | set(default_value.keys())
                    for nested_key in nested_keys:
                        nested_user = user_value.get(nested_key)
                        nested_default = default_value.get(nested_key)
                        if nested_user != nested_default:
                            nested_changes[nested_key] = {
                                "old": nested_default,
                                "new": nested_user,
                            }
                    if nested_changes:
                        option_changes[key] = nested_changes
                else:
                    option_changes[key] = {
                        "old": default_value,
                        "new": user_value,
                    }

        if option_changes:
            if event_type not in result.changed_options:
                result.changed_options[event_type] = {}
            result.changed_options[event_type][handler_name] = option_changes

    def _diff_plugins(
        self,
        user_config: dict[str, Any],
        default_config: dict[str, Any],
        result: ConfigDiff,
    ) -> None:
        """Extract custom plugin configurations.

        Args:
            user_config: User's config dict
            default_config: Default config dict
            result: ConfigDiff to populate
        """
        user_plugins = user_config.get("plugins", {})
        default_plugins = default_config.get("plugins", {})

        if not isinstance(user_plugins, dict):
            user_plugins = {}
        if not isinstance(default_plugins, dict):
            default_plugins = {}

        user_plugin_list = user_plugins.get("plugins", [])
        default_plugin_list = default_plugins.get("plugins", [])

        if not isinstance(user_plugin_list, list):
            user_plugin_list = []
        if not isinstance(default_plugin_list, list):
            default_plugin_list = []

        # Any plugins in user config that aren't in default are custom
        for plugin in user_plugin_list:
            if plugin not in default_plugin_list:
                result.custom_plugins.append(plugin)
