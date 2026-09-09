"""Tests for config CLI commands (config-diff, config-merge, config-validate).

TDD: These tests are written FIRST, before the implementation.
"""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from claude_code_hooks_daemon.install.config_cli import (
    list_known_versions,
    run_audit_handler_keys,
    run_check_config_migrations,
    run_config_diff,
    run_config_merge,
    run_config_validate,
)
from claude_code_hooks_daemon.install.report_offload import SUMMARY_MAX_BYTES


@pytest.fixture()
def tmp_configs(tmp_path: Path) -> dict[str, Path]:
    """Create temporary config files for testing."""
    user_config = {
        "version": "2.0",
        "daemon": {"log_level": "DEBUG", "idle_timeout_seconds": 600},
        "handlers": {
            "pre_tool_use": {
                "destructive_git": {"enabled": True, "priority": 5},
                "my_custom_handler": {"enabled": True, "priority": 50},
            }
        },
    }
    default_config = {
        "version": "2.0",
        "daemon": {"log_level": "INFO", "idle_timeout_seconds": 600},
        "handlers": {
            "pre_tool_use": {
                "destructive_git": {"enabled": True, "priority": 10},
                "sed_blocker": {"enabled": True, "priority": 10},
            }
        },
    }

    user_path = tmp_path / "user-config.yaml"
    default_path = tmp_path / "default-config.yaml"

    with user_path.open("w") as f:
        yaml.safe_dump(user_config, f)
    with default_path.open("w") as f:
        yaml.safe_dump(default_config, f)

    return {"user": user_path, "default": default_path}


class TestRunConfigDiff:
    """Test run_config_diff function."""

    def test_returns_diff_dict(self, tmp_configs: dict[str, Path]) -> None:
        """Returns a dictionary with diff results."""
        result = run_config_diff(
            user_config_path=tmp_configs["user"],
            default_config_path=tmp_configs["default"],
        )
        assert isinstance(result, dict)
        assert "has_changes" in result
        assert result["has_changes"] is True

    def test_detects_priority_change(self, tmp_configs: dict[str, Path]) -> None:
        """Detects priority changes in diff output."""
        result = run_config_diff(
            user_config_path=tmp_configs["user"],
            default_config_path=tmp_configs["default"],
        )
        assert "changed_priorities" in result
        assert "pre_tool_use" in result["changed_priorities"]

    def test_detects_added_handler(self, tmp_configs: dict[str, Path]) -> None:
        """Detects added handlers in diff output."""
        result = run_config_diff(
            user_config_path=tmp_configs["user"],
            default_config_path=tmp_configs["default"],
        )
        assert "added_handlers" in result
        assert "my_custom_handler" in result["added_handlers"].get("pre_tool_use", {})

    def test_json_output(self, tmp_configs: dict[str, Path]) -> None:
        """Output is valid JSON-serializable."""
        result = run_config_diff(
            user_config_path=tmp_configs["user"],
            default_config_path=tmp_configs["default"],
        )
        json_str = json.dumps(result)
        assert json_str is not None

    def test_nonexistent_file_raises(self, tmp_path: Path) -> None:
        """Raises FileNotFoundError for nonexistent files."""
        with pytest.raises(FileNotFoundError):
            run_config_diff(
                user_config_path=tmp_path / "nonexistent.yaml",
                default_config_path=tmp_path / "also-nonexistent.yaml",
            )


class TestRunConfigMerge:
    """Test run_config_merge function."""

    def test_returns_merge_result_dict(self, tmp_configs: dict[str, Path]) -> None:
        """Returns a dictionary with merge results."""
        new_default = {
            "version": "2.0",
            "daemon": {"log_level": "INFO", "idle_timeout_seconds": 600},
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 10},
                    "new_handler": {"enabled": True, "priority": 25},
                }
            },
        }
        new_default_path = tmp_configs["default"].parent / "new-default.yaml"
        with new_default_path.open("w") as f:
            yaml.safe_dump(new_default, f)

        result = run_config_merge(
            user_config_path=tmp_configs["user"],
            old_default_config_path=tmp_configs["default"],
            new_default_config_path=new_default_path,
        )
        assert isinstance(result, dict)
        assert "merged_config" in result
        assert "conflicts" in result
        assert "is_clean" in result

    def test_preserves_user_customizations(self, tmp_configs: dict[str, Path]) -> None:
        """Merged config preserves user customizations."""
        new_default = {
            "version": "2.0",
            "daemon": {"log_level": "INFO", "idle_timeout_seconds": 600},
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 10},
                }
            },
        }
        new_default_path = tmp_configs["default"].parent / "new-default.yaml"
        with new_default_path.open("w") as f:
            yaml.safe_dump(new_default, f)

        result = run_config_merge(
            user_config_path=tmp_configs["user"],
            old_default_config_path=tmp_configs["default"],
            new_default_config_path=new_default_path,
        )
        merged = result["merged_config"]
        # Custom daemon setting preserved
        assert merged["daemon"]["log_level"] == "DEBUG"
        # Custom priority preserved
        assert merged["handlers"]["pre_tool_use"]["destructive_git"]["priority"] == 5
        # Custom handler preserved
        assert "my_custom_handler" in merged["handlers"]["pre_tool_use"]


class TestRunConfigValidate:
    """Test run_config_validate function."""

    def test_valid_config(self, tmp_path: Path) -> None:
        """Valid config passes validation."""
        config = {
            "version": "2.0",
            "daemon": {"log_level": "INFO"},
            "handlers": {},
        }
        config_path = tmp_path / "valid-config.yaml"
        with config_path.open("w") as f:
            yaml.safe_dump(config, f)

        result = run_config_validate(config_path=config_path)
        assert isinstance(result, dict)
        assert result["valid"] is True

    def test_invalid_config(self, tmp_path: Path) -> None:
        """Invalid config fails validation with error details."""
        config: dict[str, Any] = {
            "version": "abc",
            "daemon": {"log_level": "TRACE"},
            "handlers": {},
        }
        config_path = tmp_path / "invalid-config.yaml"
        with config_path.open("w") as f:
            yaml.safe_dump(config, f)

        result = run_config_validate(config_path=config_path)
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_nonexistent_file_raises(self, tmp_path: Path) -> None:
        """Raises FileNotFoundError for nonexistent files."""
        with pytest.raises(FileNotFoundError):
            run_config_validate(config_path=tmp_path / "nonexistent.yaml")

    def test_non_dict_yaml_raises(self, tmp_path: Path) -> None:
        """Raises ValueError for YAML that is not a dictionary."""
        config_path = tmp_path / "list-config.yaml"
        with config_path.open("w") as f:
            f.write("- item1\n- item2\n")

        with pytest.raises(ValueError, match="YAML dictionary"):
            run_config_validate(config_path=config_path)


_MINIMAL_MANIFEST = """\
version: "{version}"
date: "2026-01-01"
breaking: false
config_changes:
  added: []
  renamed: []
  removed: []
  changed: []
"""

_MANIFEST_WITH_ADDED = """\
version: "2.13.0"
date: "2026-02-17"
breaking: false
config_changes:
  added:
    - key: daemon.enforce_single_daemon_process
      description: "Prevents multiple daemon instances"
  renamed: []
  removed: []
  changed: []
"""

_MANIFEST_WITH_RECOMMENDED = """\
version: "2.13.0"
date: "2026-02-17"
breaking: false
config_changes:
  added:
    - key: handlers.post_tool_use.recovery_cron_advisor.enabled
      description: "Opt-in failsafe recovery cron advisory"
      recommended: true
      dormant: true
      recommended_value: true
  renamed: []
  removed: []
  changed: []
"""


class TestRunCheckConfigMigrations:
    """Tests for run_check_config_migrations."""

    def _write_config(self, path: Path, config: dict) -> Path:
        p = path / "hooks-daemon.yaml"
        p.write_text(yaml.dump(config))
        return p

    def _write_manifest(self, d: Path, version: str, content: str) -> None:
        (d / f"v{version}.yaml").write_text(content)

    def test_returns_advisory_dict_structure(self, tmp_path: Path) -> None:
        md = tmp_path / "manifests"
        md.mkdir()
        self._write_manifest(md, "2.13.0", _MANIFEST_WITH_ADDED)
        cfg = self._write_config(tmp_path, {"handlers": {}, "daemon": {}})

        result = run_check_config_migrations(
            from_version="2.12.0",
            to_version="2.13.0",
            user_config_path=cfg,
            manifests_dir=md,
        )

        assert "from_version" in result
        assert "to_version" in result
        assert "has_warnings" in result
        assert "has_suggestions" in result
        assert "warnings" in result
        assert "suggestions" in result

    def test_text_format_includes_text_key(self, tmp_path: Path) -> None:
        md = tmp_path / "manifests"
        md.mkdir()
        cfg = self._write_config(tmp_path, {"handlers": {}, "daemon": {}})

        result = run_check_config_migrations(
            from_version="2.12.0",
            to_version="2.13.0",
            user_config_path=cfg,
            output_format="text",
            manifests_dir=md,
        )

        assert "text" in result
        assert isinstance(result["text"], str)

    def test_json_format_omits_text_key(self, tmp_path: Path) -> None:
        md = tmp_path / "manifests"
        md.mkdir()
        cfg = self._write_config(tmp_path, {"handlers": {}, "daemon": {}})

        result = run_check_config_migrations(
            from_version="2.12.0",
            to_version="2.13.0",
            user_config_path=cfg,
            output_format="json",
            manifests_dir=md,
        )

        assert "text" not in result

    def test_suggestion_when_new_option_not_in_user_config(self, tmp_path: Path) -> None:
        md = tmp_path / "manifests"
        md.mkdir()
        self._write_manifest(md, "2.13.0", _MANIFEST_WITH_ADDED)
        cfg = self._write_config(tmp_path, {"handlers": {}, "daemon": {}})

        result = run_check_config_migrations(
            from_version="2.12.0",
            to_version="2.13.0",
            user_config_path=cfg,
            manifests_dir=md,
        )

        assert result["has_suggestions"] is True
        assert len(result["suggestions"]) == 1
        assert result["suggestions"][0]["key"] == "daemon.enforce_single_daemon_process"

    def test_json_suggestion_includes_plan_00133_fields(self, tmp_path: Path) -> None:
        """JSON suggestions carry recommended/dormant/recommended_value/current_value.

        Regression: the JSON path dropped these Plan 00133 fields that the text
        path renders, so machine-readable consumers lost the recommended /
        default-flip signal. UNSET must serialise as null.
        """
        md = tmp_path / "manifests"
        md.mkdir()
        self._write_manifest(md, "2.13.0", _MANIFEST_WITH_RECOMMENDED)
        cfg = self._write_config(tmp_path, {"handlers": {}, "daemon": {}})

        result = run_check_config_migrations(
            from_version="2.12.0",
            to_version="2.13.0",
            user_config_path=cfg,
            output_format="json",
            manifests_dir=md,
        )

        assert result["has_suggestions"] is True
        assert len(result["suggestions"]) == 1
        suggestion = result["suggestions"][0]
        assert suggestion["recommended"] is True
        assert suggestion["dormant"] is True
        assert suggestion["recommended_value"] is True
        # The client never set the key, so current_value is unset -> null in JSON.
        assert suggestion["current_value"] is None

    def test_json_suggestion_unset_recommended_value_is_null(self, tmp_path: Path) -> None:
        """A suggestion without a recommended_value serialises it as null, not a sentinel."""
        md = tmp_path / "manifests"
        md.mkdir()
        self._write_manifest(md, "2.13.0", _MANIFEST_WITH_ADDED)
        cfg = self._write_config(tmp_path, {"handlers": {}, "daemon": {}})

        result = run_check_config_migrations(
            from_version="2.12.0",
            to_version="2.13.0",
            user_config_path=cfg,
            output_format="json",
            manifests_dir=md,
        )

        suggestion = result["suggestions"][0]
        assert suggestion["recommended"] is False
        assert suggestion["dormant"] is False
        assert suggestion["recommended_value"] is None
        assert suggestion["current_value"] is None

    def test_nonexistent_config_raises_file_not_found(self, tmp_path: Path) -> None:
        md = tmp_path / "manifests"
        md.mkdir()
        with pytest.raises(FileNotFoundError):
            run_check_config_migrations(
                from_version="2.12.0",
                to_version="2.13.0",
                user_config_path=tmp_path / "missing.yaml",
                manifests_dir=md,
            )

    def test_from_greater_than_to_raises_value_error(self, tmp_path: Path) -> None:
        md = tmp_path / "manifests"
        md.mkdir()
        cfg = self._write_config(tmp_path, {})
        with pytest.raises(ValueError):
            run_check_config_migrations(
                from_version="2.15.0",
                to_version="2.10.0",
                user_config_path=cfg,
                manifests_dir=md,
            )


class TestListKnownVersions:
    """Tests for list_known_versions in config_cli."""

    def test_delegates_to_migrations_module(self, tmp_path: Path) -> None:
        (tmp_path / "v2.2.0.yaml").write_text('version: "2.2.0"\n')
        (tmp_path / "v2.3.0.yaml").write_text('version: "2.3.0"\n')
        result = list_known_versions(manifests_dir=tmp_path)
        assert result == ["2.2.0", "2.3.0"]

    def test_returns_empty_for_missing_dir(self, tmp_path: Path) -> None:
        result = list_known_versions(manifests_dir=tmp_path / "missing")
        assert result == []


class TestHandlerKeyAuditInCli:
    """Plan 00362: the CLI layer surfaces stale handler keys and the merge's moves."""

    def test_config_validate_warns_on_relocated_key(self, tmp_path: Path) -> None:
        config = {
            "version": "2.0",
            "daemon": {"log_level": "INFO"},
            "handlers": {"stop": {"hedging_language_detector": {"enabled": True}}},
        }
        config_path = tmp_path / "hooks-daemon.yaml"
        config_path.write_text(yaml.safe_dump(config))

        result = run_config_validate(config_path=config_path)
        assert result["valid"] is True
        assert any(
            "pseudo_events.nitpick.handlers.hedging_language" in w for w in result["warnings"]
        )

    def test_check_config_migrations_reports_stale_keys_without_a_manifest(
        self, tmp_path: Path
    ) -> None:
        md = tmp_path / "manifests"
        md.mkdir()
        cfg = tmp_path / "hooks-daemon.yaml"
        cfg.write_text(
            yaml.safe_dump(
                {
                    "handlers": {
                        "stop": {"dismissive_language_detector": {"enabled": True}},
                        "notification": {"notification_logger": {"enabled": True}},
                    },
                    "daemon": {},
                }
            )
        )

        result = run_check_config_migrations(
            from_version="3.41.0",
            to_version="3.62.1",
            user_config_path=cfg,
            manifests_dir=md,
        )

        assert result["has_warnings"] is True
        paths = {f["path"] for f in result["stale_handler_keys"]}
        assert paths == {
            "handlers.stop.dismissive_language_detector",
            "handlers.notification.notification_logger",
        }
        assert "pseudo_events.nitpick.handlers.dismissive_language" in result["text"]
        assert "no longer exists" in result["text"]

    def test_check_config_migrations_clean_config_has_no_stale_keys(self, tmp_path: Path) -> None:
        md = tmp_path / "manifests"
        md.mkdir()
        cfg = tmp_path / "hooks-daemon.yaml"
        cfg.write_text(yaml.safe_dump({"handlers": {"stop": {"auto_continue_stop": {}}}}))

        result = run_check_config_migrations(
            from_version="3.41.0", to_version="3.62.1", user_config_path=cfg, manifests_dir=md
        )
        assert result["stale_handler_keys"] == []
        assert result["has_warnings"] is False

    def test_config_merge_moves_relocated_keys_and_reports_them(self, tmp_path: Path) -> None:
        user = {
            "version": "2.0",
            "daemon": {"log_level": "INFO"},
            "handlers": {"stop": {"hedging_language_detector": {"enabled": True, "priority": 30}}},
        }
        default = {"version": "2.0", "daemon": {"log_level": "INFO"}, "handlers": {"stop": {}}}
        user_path = tmp_path / "user.yaml"
        old_path = tmp_path / "old.yaml"
        new_path = tmp_path / "new.yaml"
        user_path.write_text(yaml.safe_dump(user))
        old_path.write_text(yaml.safe_dump(default))
        new_path.write_text(yaml.safe_dump(default))

        result = run_config_merge(user_path, old_path, new_path)

        merged = result["merged_config"]
        assert "hedging_language_detector" not in merged["handlers"]["stop"]
        assert merged["pseudo_events"]["nitpick"]["handlers"]["hedging_language"] == {
            "enabled": True,
            "priority": 30,
        }
        assert [m["action"] for m in result["handler_key_migrations"]] == ["moved"]

    def test_config_merge_keeps_user_settings_when_old_default_had_the_key(
        self, tmp_path: Path
    ) -> None:
        """The client shape: old default AND user carry the key; new default has nitpick.

        Without pre-migrating the user's config the differ sees only a
        priority/enabled change on a handler the new default removed, reports
        a conflict, and the new default's `enabled: true` silently replaces
        the user's `enabled: false`.
        """
        old_default = {
            "version": "2.0",
            "daemon": {"log_level": "INFO"},
            "handlers": {"stop": {"hedging_language_detector": {"enabled": True, "priority": 30}}},
        }
        user = {
            "version": "2.0",
            "daemon": {"log_level": "INFO"},
            "handlers": {"stop": {"hedging_language_detector": {"enabled": False, "priority": 31}}},
        }
        new_default = {
            "version": "2.0",
            "daemon": {"log_level": "INFO"},
            "handlers": {"stop": {}},
            "pseudo_events": {
                "nitpick": {
                    "enabled": True,
                    "triggers": ["stop:1/1"],
                    "handlers": {"hedging_language": {"enabled": True}},
                }
            },
        }
        user_path = tmp_path / "user.yaml"
        old_path = tmp_path / "old.yaml"
        new_path = tmp_path / "new.yaml"
        user_path.write_text(yaml.safe_dump(user))
        old_path.write_text(yaml.safe_dump(old_default))
        new_path.write_text(yaml.safe_dump(new_default))

        result = run_config_merge(user_path, old_path, new_path)

        nitpick = result["merged_config"]["pseudo_events"]["nitpick"]
        assert nitpick["handlers"]["hedging_language"] == {"enabled": False, "priority": 31}
        assert nitpick["triggers"] == ["stop:1/1"]
        assert "hedging_language_detector" not in result["merged_config"]["handlers"]["stop"]
        assert [m["summary"] for m in result["handler_key_migrations"]] == [
            "handlers.stop.hedging_language_detector -> "
            "pseudo_events.nitpick.handlers.hedging_language"
        ]
        assert result["conflicts"] == []

    def test_run_audit_handler_keys(self, tmp_path: Path) -> None:
        cfg = tmp_path / "hooks-daemon.yaml"
        cfg.write_text(
            yaml.safe_dump({"handlers": {"stop": {"hedging_language_detector": {"enabled": True}}}})
        )
        result = run_audit_handler_keys(config_path=cfg)
        assert result["has_findings"] is True
        assert result["findings"][0]["kind"] == "relocated"
        assert "applied_migrations" not in result

    def test_run_audit_handler_keys_reports_applied_migrations(self, tmp_path: Path) -> None:
        backup = tmp_path / "hooks-daemon.yaml.backup"
        backup.write_text(
            yaml.safe_dump({"handlers": {"stop": {"hedging_language_detector": {"enabled": True}}}})
        )
        cfg = tmp_path / "hooks-daemon.yaml"
        cfg.write_text(
            yaml.safe_dump(
                {
                    "handlers": {"stop": {}},
                    "pseudo_events": {"nitpick": {"handlers": {"hedging_language": {}}}},
                }
            )
        )
        result = run_audit_handler_keys(config_path=cfg, migrated_from=backup)
        assert result["has_findings"] is False
        assert [m["summary"] for m in result["applied_migrations"]] == [
            "handlers.stop.hedging_language_detector -> "
            "pseudo_events.nitpick.handlers.hedging_language"
        ]


_MANIFEST_WITH_RENAMED = """\
version: "2.13.0"
date: "2026-02-17"
breaking: false
config_changes:
  added: []
  renamed:
    - old_key: daemon.old_name
      new_key: daemon.new_name
      description: "Renamed for clarity"
  removed: []
  changed: []
"""


class TestRunCheckConfigMigrationsOffload:
    """Plan 00329: the advisory is offloaded to a file and stdout stays bounded."""

    def _write_config(self, path: Path, config: dict[str, Any]) -> Path:
        p = path / "hooks-daemon.yaml"
        p.write_text(yaml.dump(config))
        return p

    def _manifests(self, tmp_path: Path) -> Path:
        md = tmp_path / "manifests"
        md.mkdir()
        (md / "v2.13.0.yaml").write_text(_MANIFEST_WITH_RECOMMENDED)
        (md / "v2.14.0.yaml").write_text(_MANIFEST_WITH_ADDED.replace("2.13.0", "2.14.0"))
        return md

    def test_report_dir_bounds_the_text_and_writes_the_full_advisory(self, tmp_path: Path) -> None:
        md = self._manifests(tmp_path)
        cfg = self._write_config(tmp_path, {"handlers": {}, "daemon": {}})
        result = run_check_config_migrations(
            from_version="2.12.0",
            to_version="2.14.0",
            user_config_path=cfg,
            output_format="text",
            manifests_dir=md,
            report_dir=tmp_path / "reports",
        )
        report_path = Path(result["report_path"])
        assert report_path == tmp_path / "reports" / "v2.12.0-to-v2.14.0" / "ADVISORY.md"
        full = report_path.read_text(encoding="utf-8")
        assert "Prevents multiple daemon instances" in full
        text = result["text"]
        assert len(text.encode("utf-8")) <= SUMMARY_MAX_BYTES
        assert str(report_path) in text
        # the actionable line survives inline, the informational prose does not
        assert "recovery_cron_advisor.enabled" in text
        assert "recovery_cron_advisor.enabled = true" in text
        assert "Prevents multiple daemon instances" not in text
        assert "1 informational" in text

    def test_warnings_and_stale_keys_stay_inline(self, tmp_path: Path) -> None:
        md = tmp_path / "manifests"
        md.mkdir()
        (md / "v2.13.0.yaml").write_text(_MANIFEST_WITH_RENAMED)
        cfg = self._write_config(tmp_path, {"handlers": {}, "daemon": {"old_name": 1}})
        result = run_check_config_migrations(
            from_version="2.12.0",
            to_version="2.13.0",
            user_config_path=cfg,
            output_format="text",
            manifests_dir=md,
            report_dir=tmp_path / "reports",
        )
        assert result["has_warnings"] is True
        assert "daemon.old_name" in result["text"]
        assert "daemon.new_name" in result["text"]

    def test_without_report_dir_the_full_advisory_is_the_text(self, tmp_path: Path) -> None:
        md = self._manifests(tmp_path)
        cfg = self._write_config(tmp_path, {"handlers": {}, "daemon": {}})
        result = run_check_config_migrations(
            from_version="2.12.0",
            to_version="2.14.0",
            user_config_path=cfg,
            output_format="text",
            manifests_dir=md,
        )
        assert "Prevents multiple daemon instances" in result["text"]
        assert result["report_path"] is None

    def test_nothing_to_report_writes_nothing(self, tmp_path: Path) -> None:
        md = tmp_path / "manifests"
        md.mkdir()
        cfg = self._write_config(tmp_path, {"handlers": {}, "daemon": {}})
        result = run_check_config_migrations(
            from_version="2.12.0",
            to_version="2.13.0",
            user_config_path=cfg,
            output_format="text",
            manifests_dir=md,
            report_dir=tmp_path / "reports",
        )
        assert result["report_path"] is None
        assert not (tmp_path / "reports").exists()
        assert "No Changes Needed" in result["text"]

    def test_bound_holds_for_hundreds_of_new_options(self, tmp_path: Path) -> None:
        md = tmp_path / "manifests"
        md.mkdir()
        added = "".join(
            f'    - key: handlers.pre_tool_use.h{i:03d}.enabled\n      description: "opt {i}"\n'
            f"      recommended: true\n      recommended_value: true\n"
            for i in range(300)
        )
        (md / "v2.13.0.yaml").write_text(
            'version: "2.13.0"\ndate: "2026-02-17"\nbreaking: false\nconfig_changes:\n'
            f"  added:\n{added}  renamed: []\n  removed: []\n  changed: []\n"
        )
        cfg = self._write_config(tmp_path, {"handlers": {}, "daemon": {}})
        result = run_check_config_migrations(
            from_version="2.12.0",
            to_version="2.13.0",
            user_config_path=cfg,
            output_format="text",
            manifests_dir=md,
            report_dir=tmp_path / "reports",
        )
        assert len(result["text"].encode("utf-8")) <= SUMMARY_MAX_BYTES
        assert "more" in result["text"]
        assert "ADVISORY.md" in result["text"]
