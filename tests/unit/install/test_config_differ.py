"""Tests for ConfigDiffer - compares two YAML configs to extract user customizations.

TDD: These tests are written FIRST, before the implementation.
"""

from claude_code_hooks_daemon.install.config_differ import ConfigDiff, ConfigDiffer


class TestConfigDifferInit:
    """Test ConfigDiffer initialization."""

    def test_creates_instance(self) -> None:
        """ConfigDiffer can be instantiated."""
        differ = ConfigDiffer()
        assert differ is not None


class TestConfigDiff:
    """Test ConfigDiff dataclass."""

    def test_empty_diff(self) -> None:
        """Empty diff has no changes."""
        diff = ConfigDiff()
        assert diff.added_handlers == {}
        assert diff.removed_handlers == {}
        assert diff.changed_priorities == {}
        assert diff.changed_options == {}
        assert diff.custom_daemon_settings == {}
        assert diff.custom_plugins == []
        assert diff.has_changes is False

    def test_has_changes_with_added_handlers(self) -> None:
        """Diff with added handlers reports changes."""
        diff = ConfigDiff(
            added_handlers={
                "pre_tool_use": {"my_custom_handler": {"enabled": True, "priority": 50}}
            }
        )
        assert diff.has_changes is True

    def test_has_changes_with_changed_priorities(self) -> None:
        """Diff with changed priorities reports changes."""
        diff = ConfigDiff(
            changed_priorities={"pre_tool_use": {"destructive_git": {"old": 10, "new": 5}}}
        )
        assert diff.has_changes is True

    def test_has_changes_with_custom_daemon_settings(self) -> None:
        """Diff with custom daemon settings reports changes."""
        diff = ConfigDiff(custom_daemon_settings={"log_level": "DEBUG"})
        assert diff.has_changes is True


class TestConfigDifferDiff:
    """Test ConfigDiffer.diff() method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.differ = ConfigDiffer()

    def test_identical_configs_produce_empty_diff(self) -> None:
        """Two identical configs produce no diff."""
        config = {
            "version": "2.0",
            "daemon": {"log_level": "INFO"},
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": True, "priority": 10}}},
        }
        diff = self.differ.diff(user_config=config, default_config=config)
        assert diff.has_changes is False

    def test_detects_added_handler(self) -> None:
        """Detects handlers added by user that are not in default config."""
        default_config = {
            "version": "2.0",
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": True, "priority": 10}}},
        }
        user_config = {
            "version": "2.0",
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 10},
                    "my_custom_handler": {"enabled": True, "priority": 50},
                }
            },
        }
        diff = self.differ.diff(user_config=user_config, default_config=default_config)
        assert "pre_tool_use" in diff.added_handlers
        assert "my_custom_handler" in diff.added_handlers["pre_tool_use"]

    def test_detects_removed_handler(self) -> None:
        """Detects handlers present in default but removed from user config."""
        default_config = {
            "version": "2.0",
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 10},
                    "sed_blocker": {"enabled": True, "priority": 10},
                }
            },
        }
        user_config = {
            "version": "2.0",
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 10},
                }
            },
        }
        diff = self.differ.diff(user_config=user_config, default_config=default_config)
        assert "pre_tool_use" in diff.removed_handlers
        assert "sed_blocker" in diff.removed_handlers["pre_tool_use"]

    def test_detects_changed_priority(self) -> None:
        """Detects handler priority changes."""
        default_config = {
            "version": "2.0",
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": True, "priority": 10}}},
        }
        user_config = {
            "version": "2.0",
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": True, "priority": 5}}},
        }
        diff = self.differ.diff(user_config=user_config, default_config=default_config)
        assert "pre_tool_use" in diff.changed_priorities
        assert diff.changed_priorities["pre_tool_use"]["destructive_git"] == {
            "old": 10,
            "new": 5,
        }

    def test_detects_changed_enabled_status(self) -> None:
        """Detects handler enabled/disabled status changes."""
        default_config = {
            "version": "2.0",
            "handlers": {"pre_tool_use": {"tdd_enforcement": {"enabled": False, "priority": 35}}},
        }
        user_config = {
            "version": "2.0",
            "handlers": {"pre_tool_use": {"tdd_enforcement": {"enabled": True, "priority": 35}}},
        }
        diff = self.differ.diff(user_config=user_config, default_config=default_config)
        assert "pre_tool_use" in diff.changed_options
        assert "tdd_enforcement" in diff.changed_options["pre_tool_use"]
        assert diff.changed_options["pre_tool_use"]["tdd_enforcement"]["enabled"] == {
            "old": False,
            "new": True,
        }

    def test_detects_changed_handler_options(self) -> None:
        """Detects changes to handler-specific options."""
        default_config = {
            "version": "2.0",
            "handlers": {
                "pre_tool_use": {
                    "markdown_organization": {
                        "enabled": False,
                        "priority": 50,
                        "options": {"track_plans_in_project": None},
                    }
                }
            },
        }
        user_config = {
            "version": "2.0",
            "handlers": {
                "pre_tool_use": {
                    "markdown_organization": {
                        "enabled": True,
                        "priority": 50,
                        "options": {"track_plans_in_project": "CLAUDE/Plan"},
                    }
                }
            },
        }
        diff = self.differ.diff(user_config=user_config, default_config=default_config)
        assert "pre_tool_use" in diff.changed_options
        handler_changes = diff.changed_options["pre_tool_use"]["markdown_organization"]
        assert "options" in handler_changes
        assert handler_changes["options"]["track_plans_in_project"] == {
            "old": None,
            "new": "CLAUDE/Plan",
        }

    def test_detects_custom_daemon_settings(self) -> None:
        """Detects custom daemon settings that differ from default."""
        default_config = {
            "version": "2.0",
            "daemon": {"log_level": "INFO", "idle_timeout_seconds": 600},
        }
        user_config = {
            "version": "2.0",
            "daemon": {"log_level": "DEBUG", "idle_timeout_seconds": 600},
        }
        diff = self.differ.diff(user_config=user_config, default_config=default_config)
        assert diff.custom_daemon_settings == {"log_level": "DEBUG"}

    def test_detects_custom_plugins(self) -> None:
        """Detects custom plugin configurations."""
        default_config = {
            "version": "2.0",
            "handlers": {},
        }
        user_config = {
            "version": "2.0",
            "handlers": {},
            "plugins": {
                "plugins": [
                    {
                        "path": ".claude/hooks/handlers/my_plugin.py",
                        "event_type": "pre_tool_use",
                        "enabled": True,
                    }
                ]
            },
        }
        diff = self.differ.diff(user_config=user_config, default_config=default_config)
        assert len(diff.custom_plugins) == 1
        assert diff.custom_plugins[0]["path"] == ".claude/hooks/handlers/my_plugin.py"

    def test_handles_missing_handlers_section(self) -> None:
        """Handles configs with missing handlers section gracefully."""
        default_config = {"version": "2.0"}
        user_config = {"version": "2.0"}
        diff = self.differ.diff(user_config=user_config, default_config=default_config)
        assert diff.has_changes is False

    def test_handles_new_event_type_in_user_config(self) -> None:
        """Handles user adding handlers for a new event type."""
        default_config = {
            "version": "2.0",
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": True, "priority": 10}}},
        }
        user_config = {
            "version": "2.0",
            "handlers": {
                "pre_tool_use": {"destructive_git": {"enabled": True, "priority": 10}},
                "post_tool_use": {"my_custom_post": {"enabled": True, "priority": 20}},
            },
        }
        diff = self.differ.diff(user_config=user_config, default_config=default_config)
        assert "post_tool_use" in diff.added_handlers
        assert "my_custom_post" in diff.added_handlers["post_tool_use"]

    def test_multiple_changes_across_event_types(self) -> None:
        """Detects changes across multiple event types simultaneously."""
        default_config = {
            "version": "2.0",
            "daemon": {"log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 10},
                    "sed_blocker": {"enabled": True, "priority": 10},
                },
                "session_start": {"yolo_container_detection": {"enabled": True, "priority": 10}},
            },
        }
        user_config = {
            "version": "2.0",
            "daemon": {"log_level": "DEBUG"},
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 5},
                    "my_custom": {"enabled": True, "priority": 50},
                },
                "session_start": {"yolo_container_detection": {"enabled": False, "priority": 10}},
            },
        }
        diff = self.differ.diff(user_config=user_config, default_config=default_config)
        # Changed priority
        assert "pre_tool_use" in diff.changed_priorities
        assert "destructive_git" in diff.changed_priorities["pre_tool_use"]
        # Added handler
        assert "pre_tool_use" in diff.added_handlers
        assert "my_custom" in diff.added_handlers["pre_tool_use"]
        # Removed handler
        assert "pre_tool_use" in diff.removed_handlers
        assert "sed_blocker" in diff.removed_handlers["pre_tool_use"]
        # Changed option (enabled status)
        assert "session_start" in diff.changed_options
        # Custom daemon setting
        assert diff.custom_daemon_settings == {"log_level": "DEBUG"}

    def test_empty_configs(self) -> None:
        """Handles empty configs gracefully."""
        diff = self.differ.diff(user_config={}, default_config={})
        assert diff.has_changes is False

    def test_diff_to_dict(self) -> None:
        """ConfigDiff can be serialized to a dictionary."""
        diff = ConfigDiff(
            added_handlers={"pre_tool_use": {"my_handler": {"enabled": True, "priority": 50}}},
            custom_daemon_settings={"log_level": "DEBUG"},
        )
        result = diff.to_dict()
        assert isinstance(result, dict)
        assert "added_handlers" in result
        assert "custom_daemon_settings" in result

    def test_detects_changed_idle_timeout(self) -> None:
        """Detects custom idle_timeout_seconds in daemon settings."""
        default_config = {
            "version": "2.0",
            "daemon": {"idle_timeout_seconds": 600},
        }
        user_config = {
            "version": "2.0",
            "daemon": {"idle_timeout_seconds": 1200},
        }
        diff = self.differ.diff(user_config=user_config, default_config=default_config)
        assert diff.custom_daemon_settings == {"idle_timeout_seconds": 1200}

    def test_ignores_version_differences(self) -> None:
        """Version field differences are NOT tracked as custom settings."""
        default_config = {"version": "2.0", "handlers": {}}
        user_config = {"version": "2.0", "handlers": {}}
        diff = self.differ.diff(user_config=user_config, default_config=default_config)
        assert diff.has_changes is False

    def test_handler_with_only_enabled_field(self) -> None:
        """Handles handler configs with only enabled field (no priority)."""
        default_config = {
            "version": "2.0",
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": True, "priority": 10}}},
        }
        user_config = {
            "version": "2.0",
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": False}}},
        }
        diff = self.differ.diff(user_config=user_config, default_config=default_config)
        assert "pre_tool_use" in diff.changed_options
        assert "destructive_git" in diff.changed_options["pre_tool_use"]

    def test_non_dict_daemon_section(self) -> None:
        """Handles non-dict daemon section gracefully."""
        default_config = {"version": "2.0", "daemon": "invalid"}
        user_config = {"version": "2.0", "daemon": {"log_level": "DEBUG"}}
        diff = self.differ.diff(user_config=user_config, default_config=default_config)
        assert diff.custom_daemon_settings == {}

    def test_non_dict_handlers_section(self) -> None:
        """Handles non-dict handlers section gracefully."""
        default_config = {"version": "2.0", "handlers": "invalid"}
        user_config = {"version": "2.0", "handlers": {"pre_tool_use": {}}}
        diff = self.differ.diff(user_config=user_config, default_config=default_config)
        assert diff.has_changes is False

    def test_non_dict_event_type_value(self) -> None:
        """Handles non-dict event type values gracefully."""
        default_config = {
            "version": "2.0",
            "handlers": {"pre_tool_use": "invalid"},
        }
        user_config = {
            "version": "2.0",
            "handlers": {"pre_tool_use": "also_invalid"},
        }
        diff = self.differ.diff(user_config=user_config, default_config=default_config)
        assert diff.has_changes is False

    def test_non_dict_handler_config(self) -> None:
        """Handles non-dict handler config values gracefully."""
        default_config = {
            "version": "2.0",
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": "not_a_dict",
                }
            },
        }
        user_config = {
            "version": "2.0",
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": "also_not_a_dict",
                }
            },
        }
        diff = self.differ.diff(user_config=user_config, default_config=default_config)
        # No crash, graceful handling
        assert isinstance(diff, ConfigDiff)

    def test_non_dict_plugins_section(self) -> None:
        """Handles non-dict plugins section gracefully."""
        default_config = {"version": "2.0", "plugins": "invalid"}
        user_config = {"version": "2.0", "plugins": "also_invalid"}
        diff = self.differ.diff(user_config=user_config, default_config=default_config)
        assert diff.custom_plugins == []

    def test_non_list_plugin_list(self) -> None:
        """Handles non-list plugins.plugins value gracefully."""
        default_config = {"version": "2.0", "plugins": {"plugins": "not_a_list"}}
        user_config = {"version": "2.0", "plugins": {"plugins": "also_not_a_list"}}
        diff = self.differ.diff(user_config=user_config, default_config=default_config)
        assert diff.custom_plugins == []
