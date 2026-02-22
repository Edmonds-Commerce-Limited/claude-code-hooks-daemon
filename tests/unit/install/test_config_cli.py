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
    run_check_config_migrations,
    run_config_diff,
    run_config_merge,
    run_config_validate,
)


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
