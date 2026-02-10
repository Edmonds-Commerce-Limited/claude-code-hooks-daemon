"""Tests for ConfigMerger - applies user customizations onto new default config.

TDD: These tests are written FIRST, before the implementation.
"""

from claude_code_hooks_daemon.install.config_differ import ConfigDiff
from claude_code_hooks_daemon.install.config_merger import ConfigMerger, MergeConflict, MergeResult


class TestMergeConflict:
    """Test MergeConflict dataclass."""

    def test_create_conflict(self) -> None:
        """MergeConflict can be created with all fields."""
        conflict = MergeConflict(
            path="handlers.pre_tool_use.my_handler",
            conflict_type="removed_handler",
            description="Handler 'my_handler' was removed in new version",
            user_value={"enabled": True, "priority": 50},
            default_value=None,
        )
        assert conflict.path == "handlers.pre_tool_use.my_handler"
        assert conflict.conflict_type == "removed_handler"
        assert conflict.user_value == {"enabled": True, "priority": 50}
        assert conflict.default_value is None


class TestMergeResult:
    """Test MergeResult dataclass."""

    def test_successful_merge(self) -> None:
        """MergeResult with no conflicts is successful."""
        result = MergeResult(
            merged_config={"version": "2.0"},
            conflicts=[],
        )
        assert result.is_clean is True
        assert result.merged_config == {"version": "2.0"}

    def test_merge_with_conflicts(self) -> None:
        """MergeResult with conflicts reports not clean."""
        result = MergeResult(
            merged_config={"version": "2.0"},
            conflicts=[
                MergeConflict(
                    path="handlers.pre_tool_use.old_handler",
                    conflict_type="removed_handler",
                    description="Handler removed",
                    user_value={"enabled": True},
                    default_value=None,
                )
            ],
        )
        assert result.is_clean is False

    def test_to_dict(self) -> None:
        """MergeResult can be serialized to dict."""
        result = MergeResult(
            merged_config={"version": "2.0"},
            conflicts=[],
        )
        d = result.to_dict()
        assert "merged_config" in d
        assert "conflicts" in d
        assert "is_clean" in d


class TestConfigMergerInit:
    """Test ConfigMerger initialization."""

    def test_creates_instance(self) -> None:
        """ConfigMerger can be instantiated."""
        merger = ConfigMerger()
        assert merger is not None


class TestConfigMergerMerge:
    """Test ConfigMerger.merge() method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.merger = ConfigMerger()

    def test_empty_diff_returns_new_default(self) -> None:
        """Empty diff produces the new default config unchanged."""
        new_default = {
            "version": "2.0",
            "daemon": {"log_level": "INFO"},
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": True, "priority": 10}}},
        }
        diff = ConfigDiff()
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        assert result.is_clean is True
        assert result.merged_config == new_default

    def test_applies_custom_daemon_settings(self) -> None:
        """Applies custom daemon settings from diff onto new default."""
        new_default = {
            "version": "2.0",
            "daemon": {"log_level": "INFO", "idle_timeout_seconds": 600},
        }
        diff = ConfigDiff(custom_daemon_settings={"log_level": "DEBUG"})
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        assert result.merged_config["daemon"]["log_level"] == "DEBUG"
        assert result.merged_config["daemon"]["idle_timeout_seconds"] == 600
        assert result.is_clean is True

    def test_applies_changed_priorities(self) -> None:
        """Applies custom handler priorities from diff."""
        new_default = {
            "version": "2.0",
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": True, "priority": 10}}},
        }
        diff = ConfigDiff(
            changed_priorities={"pre_tool_use": {"destructive_git": {"old": 10, "new": 5}}}
        )
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        assert result.merged_config["handlers"]["pre_tool_use"]["destructive_git"]["priority"] == 5
        assert result.is_clean is True

    def test_applies_changed_options(self) -> None:
        """Applies custom handler options (enabled, options dict) from diff."""
        new_default = {
            "version": "2.0",
            "handlers": {"pre_tool_use": {"tdd_enforcement": {"enabled": False, "priority": 35}}},
        }
        diff = ConfigDiff(
            changed_options={
                "pre_tool_use": {"tdd_enforcement": {"enabled": {"old": False, "new": True}}}
            }
        )
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        assert (
            result.merged_config["handlers"]["pre_tool_use"]["tdd_enforcement"]["enabled"] is True
        )
        assert result.is_clean is True

    def test_applies_nested_options_changes(self) -> None:
        """Applies nested handler options changes from diff."""
        new_default = {
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
        diff = ConfigDiff(
            changed_options={
                "pre_tool_use": {
                    "markdown_organization": {
                        "enabled": {"old": False, "new": True},
                        "options": {"track_plans_in_project": {"old": None, "new": "CLAUDE/Plan"}},
                    }
                }
            }
        )
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        handler = result.merged_config["handlers"]["pre_tool_use"]["markdown_organization"]
        assert handler["enabled"] is True
        assert handler["options"]["track_plans_in_project"] == "CLAUDE/Plan"

    def test_adds_custom_handlers(self) -> None:
        """Adds user-custom handlers that exist in diff but not in new default."""
        new_default = {
            "version": "2.0",
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": True, "priority": 10}}},
        }
        diff = ConfigDiff(
            added_handlers={
                "pre_tool_use": {"my_custom_handler": {"enabled": True, "priority": 50}}
            }
        )
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        assert "my_custom_handler" in result.merged_config["handlers"]["pre_tool_use"]
        assert result.merged_config["handlers"]["pre_tool_use"]["my_custom_handler"] == {
            "enabled": True,
            "priority": 50,
        }

    def test_adds_custom_handlers_for_new_event_type(self) -> None:
        """Adds custom handlers for an event type not in new default."""
        new_default = {
            "version": "2.0",
            "handlers": {},
        }
        diff = ConfigDiff(
            added_handlers={"post_tool_use": {"my_post_handler": {"enabled": True, "priority": 20}}}
        )
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        assert "post_tool_use" in result.merged_config["handlers"]
        assert "my_post_handler" in result.merged_config["handlers"]["post_tool_use"]

    def test_applies_custom_plugins(self) -> None:
        """Applies custom plugin configurations from diff."""
        new_default = {
            "version": "2.0",
            "handlers": {},
        }
        diff = ConfigDiff(
            custom_plugins=[
                {
                    "path": ".claude/hooks/handlers/my_plugin.py",
                    "event_type": "pre_tool_use",
                    "enabled": True,
                }
            ]
        )
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        plugins = result.merged_config.get("plugins", {})
        assert len(plugins.get("plugins", [])) == 1

    def test_conflict_for_removed_handler_with_user_customization(self) -> None:
        """Reports conflict when handler was removed by user but exists in new default."""
        new_default = {
            "version": "2.0",
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 10},
                    "new_handler": {"enabled": True, "priority": 15},
                }
            },
        }
        diff = ConfigDiff(
            removed_handlers={
                "pre_tool_use": {"destructive_git": {"enabled": True, "priority": 10}}
            }
        )
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        # The removed handler should still be in merged config (new default wins)
        # but a conflict should be reported
        assert len(result.conflicts) >= 1
        conflict_paths = [c.path for c in result.conflicts]
        assert any("destructive_git" in p for p in conflict_paths)

    def test_conflict_for_priority_change_on_missing_handler(self) -> None:
        """Reports conflict when priority was changed but handler no longer in new default."""
        new_default = {
            "version": "2.0",
            "handlers": {"pre_tool_use": {}},
        }
        diff = ConfigDiff(
            changed_priorities={"pre_tool_use": {"old_handler": {"old": 10, "new": 5}}}
        )
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        assert len(result.conflicts) >= 1
        assert any("old_handler" in c.path for c in result.conflicts)

    def test_multiple_changes_applied_together(self) -> None:
        """All types of changes are applied simultaneously."""
        new_default = {
            "version": "2.0",
            "daemon": {"log_level": "INFO", "idle_timeout_seconds": 600},
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 10},
                    "tdd_enforcement": {"enabled": False, "priority": 35},
                }
            },
        }
        diff = ConfigDiff(
            custom_daemon_settings={"log_level": "DEBUG"},
            changed_priorities={"pre_tool_use": {"destructive_git": {"old": 10, "new": 5}}},
            changed_options={
                "pre_tool_use": {"tdd_enforcement": {"enabled": {"old": False, "new": True}}}
            },
            added_handlers={"pre_tool_use": {"my_custom": {"enabled": True, "priority": 50}}},
        )
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        assert result.merged_config["daemon"]["log_level"] == "DEBUG"
        assert result.merged_config["handlers"]["pre_tool_use"]["destructive_git"]["priority"] == 5
        assert (
            result.merged_config["handlers"]["pre_tool_use"]["tdd_enforcement"]["enabled"] is True
        )
        assert "my_custom" in result.merged_config["handlers"]["pre_tool_use"]

    def test_preserves_new_default_handlers_not_in_diff(self) -> None:
        """New handlers in the new default that aren't in diff are preserved."""
        new_default = {
            "version": "2.0",
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 10},
                    "brand_new_handler": {"enabled": True, "priority": 25},
                }
            },
        }
        diff = ConfigDiff()
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        assert "brand_new_handler" in result.merged_config["handlers"]["pre_tool_use"]

    def test_merge_does_not_mutate_new_default(self) -> None:
        """Merge operation does not mutate the input new_default config."""
        new_default = {
            "version": "2.0",
            "daemon": {"log_level": "INFO"},
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": True, "priority": 10}}},
        }
        import copy

        original = copy.deepcopy(new_default)
        diff = ConfigDiff(custom_daemon_settings={"log_level": "DEBUG"})
        self.merger.merge(new_default_config=new_default, diff=diff)
        assert new_default == original

    def test_conflict_for_option_change_on_missing_handler(self) -> None:
        """Reports conflict when options were changed but handler no longer in new default."""
        new_default = {
            "version": "2.0",
            "handlers": {"pre_tool_use": {}},
        }
        diff = ConfigDiff(
            changed_options={
                "pre_tool_use": {"removed_handler": {"enabled": {"old": False, "new": True}}}
            }
        )
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        assert len(result.conflicts) >= 1
        assert any("removed_handler" in c.path for c in result.conflicts)

    def test_missing_handlers_section_in_new_default(self) -> None:
        """Handles new default config missing handlers section."""
        new_default = {"version": "2.0"}
        diff = ConfigDiff(
            added_handlers={"pre_tool_use": {"my_custom": {"enabled": True, "priority": 50}}}
        )
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        assert "handlers" in result.merged_config
        assert "my_custom" in result.merged_config["handlers"]["pre_tool_use"]

    def test_missing_daemon_section_in_new_default(self) -> None:
        """Handles new default config missing daemon section."""
        new_default = {"version": "2.0"}
        diff = ConfigDiff(custom_daemon_settings={"log_level": "DEBUG"})
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        assert result.merged_config["daemon"]["log_level"] == "DEBUG"

    def test_merge_conflict_to_dict(self) -> None:
        """MergeConflict.to_dict() serializes all fields."""
        conflict = MergeConflict(
            path="handlers.pre_tool_use.test",
            conflict_type="removed_handler",
            description="Test conflict",
            user_value={"enabled": True},
            default_value=None,
        )
        d = conflict.to_dict()
        assert d["path"] == "handlers.pre_tool_use.test"
        assert d["conflict_type"] == "removed_handler"
        assert d["description"] == "Test conflict"
        assert d["user_value"] == {"enabled": True}
        assert d["default_value"] is None

    def test_non_dict_handler_config_in_priority_change(self) -> None:
        """Handles non-dict handler config when applying priority changes."""
        new_default = {
            "version": "2.0",
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": "not_a_dict",
                }
            },
        }
        diff = ConfigDiff(
            changed_priorities={"pre_tool_use": {"destructive_git": {"old": 10, "new": 5}}}
        )
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        # Should not crash - non-dict handler config is skipped
        assert isinstance(result, MergeResult)

    def test_non_dict_handler_config_in_option_change(self) -> None:
        """Handles non-dict handler config when applying option changes."""
        new_default = {
            "version": "2.0",
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": "not_a_dict",
                }
            },
        }
        diff = ConfigDiff(
            changed_options={
                "pre_tool_use": {"destructive_git": {"enabled": {"old": True, "new": False}}}
            }
        )
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        assert isinstance(result, MergeResult)

    def test_non_dict_plugins_in_merged(self) -> None:
        """Handles non-dict plugins section in merged config."""
        new_default = {
            "version": "2.0",
            "plugins": "not_a_dict",
        }
        diff = ConfigDiff(
            custom_plugins=[{"path": "my_plugin.py", "event_type": "pre_tool_use", "enabled": True}]
        )
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        assert len(result.merged_config["plugins"]["plugins"]) == 1

    def test_removed_handler_no_longer_in_new_default(self) -> None:
        """No conflict when removed handler also doesn't exist in new default."""
        new_default = {
            "version": "2.0",
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": True, "priority": 10}}},
        }
        diff = ConfigDiff(
            removed_handlers={
                "pre_tool_use": {"old_deprecated_handler": {"enabled": True, "priority": 50}}
            }
        )
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        # No conflict since the handler doesn't exist in new default either
        assert result.is_clean is True
