"""Tests for ConfigMerger - applies user customizations onto new default config.

TDD: These tests are written FIRST, before the implementation.
"""

from typing import Any

from claude_code_hooks_daemon.install.config_differ import ConfigDiff, ConfigDiffer
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

    def test_applies_custom_plugin_settings(self) -> None:
        """Applies `plugins.paths` (a sibling of the `plugins.plugins` list) from diff.

        Regression (release review C4).
        """
        new_default = {
            "version": "2.0",
            "handlers": {},
            "plugins": {"paths": []},
        }
        diff = ConfigDiff(custom_plugin_settings={"paths": [".claude/lib"]})
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        assert result.merged_config["plugins"]["paths"] == [".claude/lib"]
        assert result.is_clean is True

    def test_custom_plugin_settings_applied_alongside_custom_plugins(self) -> None:
        """`plugins.paths` and `plugins.plugins` are both preserved together."""
        new_default = {"version": "2.0", "handlers": {}}
        diff = ConfigDiff(
            custom_plugin_settings={"paths": [".claude/lib"]},
            custom_plugins=[
                {"path": "my_plugin.py", "event_type": "pre_tool_use", "enabled": True}
            ],
        )
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        assert result.merged_config["plugins"]["paths"] == [".claude/lib"]
        assert len(result.merged_config["plugins"]["plugins"]) == 1

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
        """Reports a conflict when the priority target handler is non-dict.

        Regression: a priority customization for a handler that exists in the
        new default but is a scalar (e.g. `handler: true` YAML shorthand) was
        silently dropped with no signal. It must now surface as a conflict.
        """
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
        # Should not crash - non-dict handler config is reported, not applied.
        assert isinstance(result, MergeResult)
        assert len(result.conflicts) == 1
        conflict = result.conflicts[0]
        assert conflict.conflict_type == "unmergeable_handler_shape"
        assert conflict.path == "handlers.pre_tool_use.destructive_git"
        assert conflict.user_value == 5

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

    def test_nested_change_with_subkey_named_new_not_misclassified(self) -> None:
        """A nested change whose sub-key is literally 'new' must apply per sub-key.

        The differ emits a nested change as ``{option_key: {sub_key: {'old': X,
        'new': Y}}}``. When a ``sub_key`` is itself the string ``'new'`` the
        nested record looks like ``{'new': {'old': X, 'new': Y}}``. Regression:
        the old code keyed on ``'new' in change`` and treated this nested record
        as a SIMPLE change, replacing the whole ``options`` dict with the inner
        ``{'old': X, 'new': Y}`` descriptor instead of setting
        ``options['new'] = Y``.
        """
        new_default = {
            "version": "2.0",
            "handlers": {
                "pre_tool_use": {
                    "branch_policy": {
                        "enabled": True,
                        "priority": 40,
                        "options": {"new": "old-branch"},
                    }
                }
            },
        }
        diff = ConfigDiff(
            changed_options={
                "pre_tool_use": {
                    "branch_policy": {
                        "options": {"new": {"old": "old-branch", "new": "release-branch"}},
                    }
                }
            }
        )
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        handler = result.merged_config["handlers"]["pre_tool_use"]["branch_policy"]
        assert handler["options"] == {"new": "release-branch"}

    def test_simple_change_whose_new_value_is_dict_with_new_key(self) -> None:
        """A simple change whose new value is a dict containing 'new' applies verbatim.

        The differ emits ``{option_key: {'old': X, 'new': <dict>}}`` for a
        non-dict-to-dict change. The merged option must be the FULL new dict,
        even when that dict itself contains a 'new' member.
        """
        new_value = {"new": True, "label": "x"}
        new_default = {
            "version": "2.0",
            "handlers": {"pre_tool_use": {"branch_policy": {"enabled": True, "options": None}}},
        }
        diff = ConfigDiff(
            changed_options={
                "pre_tool_use": {
                    "branch_policy": {"options": {"old": None, "new": new_value}},
                }
            }
        )
        result = self.merger.merge(new_default_config=new_default, diff=diff)
        handler = result.merged_config["handlers"]["pre_tool_use"]["branch_policy"]
        assert handler["options"] == new_value


class TestTopLevelSectionsSurviveTheMerge:
    """A configured section absent from the shipped example must not be dropped.

    Field report, v3.61.0 -> v3.62.0 client upgrade. The shipped
    `.claude/hooks-daemon.yaml.example` contains only `daemon`, `handlers` and
    `version`. The merge starts from a copy of the new default and applies back
    only daemon settings, handler priorities/options, added handlers and
    plugins — so every OTHER top-level section the user configured is silently
    discarded. `plan_workflow`, `documentation` and `agents` are all documented,
    all schema-valid, and all accepted by `config-validate`.

    What makes it dangerous rather than merely wrong is the reporting.
    `is_clean` and `conflicts` track handler-level drift only, so against a
    config with complete handler coverage the merge reports `is_clean: True,
    conflicts: []` while dropping 27 keys. The more thoroughly a project has
    configured its handlers, the less warning it gets.
    """

    def setup_method(self) -> None:
        self.merger = ConfigMerger()

    @staticmethod
    def _new_default() -> dict[str, Any]:
        """A fresh copy per test: the merge deep-copies, but a shared mutable
        default would still let one test's assertion depend on another's."""
        return {
            "version": "2.0",
            "daemon": {"log_level": "INFO"},
            "handlers": {"pre_tool_use": {"sed_blocker": {"enabled": True}}},
        }

    def test_a_configured_section_absent_from_the_example_is_carried_through(self) -> None:
        diff = ConfigDiff(
            custom_sections={
                "plan_workflow": {"enabled": True, "directory": "CLAUDE/Plan"},
                "documentation": {"trees": {"agent": "CLAUDE", "human": "docs"}},
            }
        )
        merged = self.merger.merge(new_default_config=self._new_default(), diff=diff).merged_config

        assert merged["plan_workflow"] == {"enabled": True, "directory": "CLAUDE/Plan"}
        assert merged["documentation"] == {"trees": {"agent": "CLAUDE", "human": "docs"}}

    def test_the_known_sections_are_untouched_by_the_carry_through(self) -> None:
        diff = ConfigDiff(custom_sections={"plan_workflow": {"enabled": True}})
        merged = self.merger.merge(new_default_config=self._new_default(), diff=diff).merged_config

        assert merged["version"] == "2.0"
        assert merged["daemon"] == {"log_level": "INFO"}
        assert merged["handlers"]["pre_tool_use"]["sed_blocker"]["enabled"] is True

    def test_no_custom_sections_leaves_the_default_shape_alone(self) -> None:
        merged = self.merger.merge(
            new_default_config=self._new_default(), diff=ConfigDiff()
        ).merged_config

        assert sorted(merged.keys()) == ["daemon", "handlers", "version"]

    def test_the_field_scenario_end_to_end_through_the_differ(self) -> None:
        """The reported path, not just the merger half.

        The section was lost at the DIFF stage — `ConfigDiff` had no field for
        it — so a merger-only test could pass while the real upgrade still
        dropped configuration. This drives the whole differ -> merger path the
        upgrade actually uses, against an example containing only the three
        sections the shipped one has.
        """
        shipped_example = {
            "version": "2.0",
            "daemon": {"log_level": "INFO"},
            "handlers": {"pre_tool_use": {"sed_blocker": {"enabled": True}}},
        }
        user_config = {
            "version": "2.0",
            "daemon": {"log_level": "DEBUG"},
            "handlers": {"pre_tool_use": {"sed_blocker": {"enabled": True}}},
            "plan_workflow": {"enabled": True, "directory": "CLAUDE/Plan"},
            "documentation": {"trees": {"agent": "CLAUDE", "human": "docs"}},
            "agents": {"docs_qa": {"enabled": True}},
        }

        diff = ConfigDiffer().diff(user_config, shipped_example)
        merged = ConfigMerger().merge(new_default_config=shipped_example, diff=diff).merged_config

        assert merged["plan_workflow"] == {"enabled": True, "directory": "CLAUDE/Plan"}
        assert merged["documentation"] == {"trees": {"agent": "CLAUDE", "human": "docs"}}
        assert merged["agents"] == {"docs_qa": {"enabled": True}}
        assert merged["daemon"]["log_level"] == "DEBUG", "the daemon pass must still work"

    def test_the_schema_version_comes_from_the_new_default_not_the_user(self) -> None:
        """`version` is a shipped schema marker, not a user setting. Carrying
        the user's value would restore the version they were upgrading FROM and
        make the upgrade undo itself."""
        shipped_example = {"version": "3.0", "daemon": {}, "handlers": {}}
        user_config = {"version": "2.0", "daemon": {}, "handlers": {}}

        diff = ConfigDiffer().diff(user_config, shipped_example)
        merged = ConfigMerger().merge(new_default_config=shipped_example, diff=diff).merged_config

        assert merged["version"] == "3.0"

    def test_a_carried_section_does_not_overwrite_one_the_new_default_introduced(self) -> None:
        """If a later version ships its own default for a section the user had
        configured, the USER's value still wins — that is the whole point of
        preserving customisations. Pinned so a future "defaults win" change is
        a deliberate decision rather than a silent one."""
        new_default = dict(self._new_default(), plan_workflow={"enabled": False})
        diff = ConfigDiff(custom_sections={"plan_workflow": {"enabled": True}})

        merged = self.merger.merge(new_default_config=new_default, diff=diff).merged_config

        assert merged["plan_workflow"]["enabled"] is True


class TestPluginPathsSurviveTheMerge:
    """`plugins.paths` must survive an upgrade merge alongside `plugins.plugins`.

    Release review finding C4. `_diff_plugins` only ever captured entries of
    the `plugins.plugins` LIST. `paths` is a documented sibling key
    (`docs/guides/CONFIGURATION.md`), and because `plugins` sits on
    `_SECTIONS_WITH_A_DEDICATED_PASS` the custom-sections pass skips it too —
    so it was captured by nothing at all. A user config with `plugins: {paths:
    [...], plugins: [...]}` merged to `plugins: {plugins: [...]}` while
    reporting `conflicts: []` and `is_clean: True`.
    """

    def setup_method(self) -> None:
        self.differ = ConfigDiffer()
        self.merger = ConfigMerger()

    def test_the_field_scenario_end_to_end_through_the_differ(self) -> None:
        """The reported path, not just the merger half — the loss happened at
        the DIFF stage, so a merger-only test could pass while the real
        upgrade still dropped `paths`."""
        shipped_example = {
            "version": "2.0",
            "handlers": {},
            "plugins": {"paths": [], "plugins": []},
        }
        user_config = {
            "version": "2.0",
            "handlers": {},
            "plugins": {
                "paths": [".claude/lib", "vendor/handlers"],
                "plugins": [
                    {
                        "path": ".claude/hooks/handlers/my_plugin.py",
                        "event_type": "pre_tool_use",
                        "enabled": True,
                    }
                ],
            },
        }

        diff = self.differ.diff(user_config, shipped_example)
        result = self.merger.merge(new_default_config=shipped_example, diff=diff)

        assert result.merged_config["plugins"]["paths"] == [".claude/lib", "vendor/handlers"]
        assert len(result.merged_config["plugins"]["plugins"]) == 1
        assert result.is_clean is True


class TestCustomisedSectionsReceiveNewDefaultSubkeys:
    """A section the user customised must still receive a subkey a later
    default introduces, instead of losing it to a wholesale replacement.

    Release review finding C5. `_apply_custom_sections` did `merged[section] =
    deepcopy(value)`, replacing the whole section, so any key the new version
    ADDS inside a section the user has customised never reached them.
    """

    def setup_method(self) -> None:
        self.differ = ConfigDiffer()
        self.merger = ConfigMerger()

    @staticmethod
    def _new_default() -> dict[str, Any]:
        return {
            "version": "2.0",
            "daemon": {"log_level": "INFO"},
            "handlers": {"pre_tool_use": {"sed_blocker": {"enabled": True}}},
        }

    def test_a_new_default_subkey_survives_when_the_section_is_customised(self) -> None:
        new_default = dict(
            self._new_default(),
            plan_workflow={"plans_directory": "CLAUDE/Plan", "auto_number": True},
        )
        diff = ConfigDiff(custom_sections={"plan_workflow": {"plans_directory": "docs/Plans"}})

        merged = self.merger.merge(new_default_config=new_default, diff=diff).merged_config

        assert merged["plan_workflow"] == {
            "plans_directory": "docs/Plans",
            "auto_number": True,
        }

    def test_deep_merge_recurses_into_nested_mappings(self) -> None:
        new_default = dict(
            self._new_default(),
            documentation={"trees": {"agent": "CLAUDE", "human": "docs"}, "strict": False},
        )
        diff = ConfigDiff(custom_sections={"documentation": {"trees": {"agent": "AGENT_DOCS"}}})

        merged = self.merger.merge(new_default_config=new_default, diff=diff).merged_config

        assert merged["documentation"] == {
            "trees": {"agent": "AGENT_DOCS", "human": "docs"},
            "strict": False,
        }

    def test_a_list_value_is_replaced_not_merged(self) -> None:
        new_default = dict(
            self._new_default(),
            agents={"docs_qa": {"enabled": True}, "reviewers": ["alice", "bob"]},
        )
        diff = ConfigDiff(custom_sections={"agents": {"reviewers": ["carol"]}})

        merged = self.merger.merge(new_default_config=new_default, diff=diff).merged_config

        assert merged["agents"]["reviewers"] == ["carol"]
        assert merged["agents"]["docs_qa"] == {"enabled": True}

    def test_the_field_scenario_end_to_end_through_the_differ(self) -> None:
        """Drives the whole differ -> merger path, mirroring how the upgrade
        actually detects and re-applies a customised section."""
        shipped_example = dict(
            self._new_default(),
            plan_workflow={"plans_directory": "CLAUDE/Plan", "auto_number": True},
        )
        user_config = dict(
            self._new_default(),
            plan_workflow={"plans_directory": "docs/Plans", "auto_number": True},
        )

        diff = self.differ.diff(user_config, shipped_example)
        merged = self.merger.merge(new_default_config=shipped_example, diff=diff).merged_config

        assert merged["plan_workflow"] == {
            "plans_directory": "docs/Plans",
            "auto_number": True,
        }
