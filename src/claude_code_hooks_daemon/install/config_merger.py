"""Config merger for applying user customizations onto new default config.

Takes a ConfigDiff (from ConfigDiffer) and applies it onto a new version's
default config, producing a merged config that preserves user customizations
while adopting new defaults.

Used during upgrades: "Upgrade = Clean Reinstall + Config Preservation"
"""

import copy
from dataclasses import dataclass, field
from typing import Any

from claude_code_hooks_daemon.install.config_differ import ConfigDiff


@dataclass
class MergeConflict:
    """A conflict detected during config merge.

    Attributes:
        path: Dot-separated path to the conflicting value (e.g., 'handlers.pre_tool_use.my_handler')
        conflict_type: Type of conflict (removed_handler, missing_handler, renamed_option)
        description: Human-readable description of the conflict
        user_value: The user's value for this setting
        default_value: The new default value for this setting
    """

    path: str
    conflict_type: str
    description: str
    user_value: Any = None
    default_value: Any = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary.

        Returns:
            Dictionary representation.
        """
        return {
            "path": self.path,
            "conflict_type": self.conflict_type,
            "description": self.description,
            "user_value": self.user_value,
            "default_value": self.default_value,
        }


@dataclass
class MergeResult:
    """Result of merging user customizations onto new default config.

    Attributes:
        merged_config: The merged configuration dictionary
        conflicts: List of conflicts that need user attention
    """

    merged_config: dict[str, Any]
    conflicts: list[MergeConflict] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        """Return True if merge had no conflicts."""
        return len(self.conflicts) == 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary.

        Returns:
            Dictionary representation.
        """
        return {
            "merged_config": self.merged_config,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "is_clean": self.is_clean,
        }


class ConfigMerger:
    """Merges user customizations from a ConfigDiff onto a new default config.

    The merge strategy:
    1. Start with a deep copy of the new default config
    2. Apply custom daemon settings
    3. Apply handler priority changes (if handler still exists)
    4. Apply handler option changes (if handler still exists)
    5. Add user-custom handlers
    6. Add user-custom plugins
    7. Report conflicts for changes that couldn't be applied
    """

    def merge(
        self,
        new_default_config: dict[str, Any],
        diff: ConfigDiff,
    ) -> MergeResult:
        """Merge user customizations onto new default config.

        Args:
            new_default_config: The new version's default configuration
            diff: The structured diff of user customizations

        Returns:
            MergeResult with merged config and any conflicts
        """
        merged = copy.deepcopy(new_default_config)
        conflicts: list[MergeConflict] = []

        self._apply_daemon_settings(merged, diff)
        self._apply_priority_changes(merged, diff, conflicts)
        self._apply_option_changes(merged, diff, conflicts)
        self._apply_added_handlers(merged, diff)
        self._apply_plugins(merged, diff)
        self._report_removed_handler_conflicts(merged, diff, conflicts)

        return MergeResult(merged_config=merged, conflicts=conflicts)

    def _apply_daemon_settings(
        self,
        merged: dict[str, Any],
        diff: ConfigDiff,
    ) -> None:
        """Apply custom daemon settings.

        Args:
            merged: Merged config to modify in-place
            diff: ConfigDiff with custom daemon settings
        """
        if not diff.custom_daemon_settings:
            return

        if "daemon" not in merged:
            merged["daemon"] = {}

        for key, value in diff.custom_daemon_settings.items():
            merged["daemon"][key] = value

    def _apply_priority_changes(
        self,
        merged: dict[str, Any],
        diff: ConfigDiff,
        conflicts: list[MergeConflict],
    ) -> None:
        """Apply handler priority changes.

        Args:
            merged: Merged config to modify in-place
            diff: ConfigDiff with priority changes
            conflicts: List to append conflicts to
        """
        if not diff.changed_priorities:
            return

        handlers = merged.get("handlers", {})

        for event_type, handler_changes in diff.changed_priorities.items():
            event_handlers = handlers.get(event_type, {})

            for handler_name, priority_change in handler_changes.items():
                if handler_name in event_handlers:
                    if isinstance(event_handlers[handler_name], dict):
                        event_handlers[handler_name]["priority"] = priority_change["new"]
                else:
                    conflicts.append(
                        MergeConflict(
                            path=f"handlers.{event_type}.{handler_name}",
                            conflict_type="missing_handler",
                            description=(
                                f"Priority was changed from {priority_change['old']} to "
                                f"{priority_change['new']}, but handler '{handler_name}' "
                                f"no longer exists in the new default config"
                            ),
                            user_value=priority_change["new"],
                            default_value=None,
                        )
                    )

    def _apply_option_changes(
        self,
        merged: dict[str, Any],
        diff: ConfigDiff,
        conflicts: list[MergeConflict],
    ) -> None:
        """Apply handler option changes (enabled, options dict, etc.).

        Args:
            merged: Merged config to modify in-place
            diff: ConfigDiff with option changes
            conflicts: List to append conflicts to
        """
        if not diff.changed_options:
            return

        handlers = merged.get("handlers", {})

        for event_type, handler_changes in diff.changed_options.items():
            event_handlers = handlers.get(event_type, {})

            for handler_name, option_changes in handler_changes.items():
                if handler_name not in event_handlers:
                    conflicts.append(
                        MergeConflict(
                            path=f"handlers.{event_type}.{handler_name}",
                            conflict_type="missing_handler",
                            description=(
                                f"Options were customized for handler '{handler_name}', "
                                f"but it no longer exists in the new default config"
                            ),
                            user_value=option_changes,
                            default_value=None,
                        )
                    )
                    continue

                handler_config = event_handlers[handler_name]
                if not isinstance(handler_config, dict):
                    continue

                for option_key, change in option_changes.items():
                    if isinstance(change, dict) and "new" in change:
                        # Simple value change: {old: X, new: Y}
                        handler_config[option_key] = change["new"]
                    elif isinstance(change, dict):
                        # Nested dict change: {sub_key: {old: X, new: Y}}
                        if option_key not in handler_config:
                            handler_config[option_key] = {}
                        if isinstance(handler_config[option_key], dict):
                            for sub_key, sub_change in change.items():
                                if isinstance(sub_change, dict) and "new" in sub_change:
                                    handler_config[option_key][sub_key] = sub_change["new"]

    def _apply_added_handlers(
        self,
        merged: dict[str, Any],
        diff: ConfigDiff,
    ) -> None:
        """Add user-custom handlers.

        Args:
            merged: Merged config to modify in-place
            diff: ConfigDiff with added handlers
        """
        if not diff.added_handlers:
            return

        if "handlers" not in merged:
            merged["handlers"] = {}

        for event_type, handlers in diff.added_handlers.items():
            if event_type not in merged["handlers"]:
                merged["handlers"][event_type] = {}

            for handler_name, handler_config in handlers.items():
                merged["handlers"][event_type][handler_name] = copy.deepcopy(handler_config)

    def _apply_plugins(
        self,
        merged: dict[str, Any],
        diff: ConfigDiff,
    ) -> None:
        """Apply custom plugin configurations.

        Args:
            merged: Merged config to modify in-place
            diff: ConfigDiff with custom plugins
        """
        if not diff.custom_plugins:
            return

        if "plugins" not in merged:
            merged["plugins"] = {}

        if not isinstance(merged["plugins"], dict):
            merged["plugins"] = {}

        if "plugins" not in merged["plugins"]:
            merged["plugins"]["plugins"] = []

        for plugin in diff.custom_plugins:
            merged["plugins"]["plugins"].append(copy.deepcopy(plugin))

    def _report_removed_handler_conflicts(
        self,
        merged: dict[str, Any],
        diff: ConfigDiff,
        conflicts: list[MergeConflict],
    ) -> None:
        """Report conflicts for handlers the user removed that exist in new default.

        Args:
            merged: Merged config (for reference)
            diff: ConfigDiff with removed handlers
            conflicts: List to append conflicts to
        """
        if not diff.removed_handlers:
            return

        handlers = merged.get("handlers", {})

        for event_type, removed in diff.removed_handlers.items():
            event_handlers = handlers.get(event_type, {})

            for handler_name, old_config in removed.items():
                if handler_name in event_handlers:
                    conflicts.append(
                        MergeConflict(
                            path=f"handlers.{event_type}.{handler_name}",
                            conflict_type="removed_handler",
                            description=(
                                f"Handler '{handler_name}' was removed from your config, "
                                f"but it still exists in the new default. "
                                f"The new default version is included in the merged config."
                            ),
                            user_value=None,
                            default_value=event_handlers[handler_name],
                        )
                    )
