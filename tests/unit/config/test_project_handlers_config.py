"""Unit tests for ProjectHandlersConfig model."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config, ProjectHandlersConfig


class TestProjectHandlersConfigDefaults:
    """Test ProjectHandlersConfig default values."""

    def test_default_enabled_is_true(self) -> None:
        """Test that project handlers are enabled by default."""
        config = ProjectHandlersConfig()
        assert config.enabled is True

    def test_default_path(self) -> None:
        """Test default path is .claude/project-handlers."""
        config = ProjectHandlersConfig()
        assert config.path == ".claude/project-handlers"

    def test_custom_enabled_false(self) -> None:
        """Test setting enabled to False."""
        config = ProjectHandlersConfig(enabled=False)
        assert config.enabled is False

    def test_custom_path(self) -> None:
        """Test setting a custom path."""
        config = ProjectHandlersConfig(path="custom/handlers")
        assert config.path == "custom/handlers"


class TestProjectHandlersConfigValidation:
    """Test ProjectHandlersConfig validation."""

    def test_enabled_must_be_bool(self) -> None:
        """Test that enabled field validates as bool."""
        config = ProjectHandlersConfig(enabled=True)
        assert isinstance(config.enabled, bool)

    def test_path_must_be_string(self) -> None:
        """Test that path field validates as string."""
        config = ProjectHandlersConfig(path="some/path")
        assert isinstance(config.path, str)

    def test_empty_path_is_valid(self) -> None:
        """Test that empty path is valid (will be resolved at runtime)."""
        config = ProjectHandlersConfig(path="")
        assert config.path == ""

    def test_extra_fields_are_rejected(self) -> None:
        """Test that unknown fields raise ValidationError (extra='forbid').

        Regression test for M3: extra='allow' silently accepted typos in config.
        Using extra='forbid' catches config typos early.
        """
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            ProjectHandlersConfig(enabled=True, path="handlers", typo_field="oops")


class TestProjectHandlersConfigInRootConfig:
    """Test ProjectHandlersConfig integration with root Config model."""

    def test_root_config_has_project_handlers_field(self) -> None:
        """Test that root Config model has project_handlers field."""
        config = Config()
        assert hasattr(config, "project_handlers")
        assert isinstance(config.project_handlers, ProjectHandlersConfig)

    def test_root_config_default_project_handlers(self) -> None:
        """Test root Config uses default ProjectHandlersConfig."""
        config = Config()
        assert config.project_handlers.enabled is True
        assert config.project_handlers.path == ".claude/project-handlers"

    def test_root_config_project_handlers_from_dict(self) -> None:
        """Test root Config parses project_handlers from dict."""
        config = Config.model_validate(
            {
                "version": "2.0",
                "project_handlers": {
                    "enabled": False,
                    "path": "custom/handlers",
                },
            }
        )
        assert config.project_handlers.enabled is False
        assert config.project_handlers.path == "custom/handlers"

    def test_root_config_project_handlers_from_yaml(self, tmp_path: Path) -> None:
        """Test root Config loads project_handlers from YAML file."""
        config_data = {
            "version": "2.0",
            "project_handlers": {
                "enabled": True,
                "path": ".claude/project-handlers",
            },
        }
        config_file = tmp_path / "hooks-daemon.yaml"
        config_file.write_text(yaml.safe_dump(config_data))

        config = Config.load(config_file)
        assert config.project_handlers.enabled is True
        assert config.project_handlers.path == ".claude/project-handlers"

    def test_root_config_missing_project_handlers_uses_defaults(self) -> None:
        """Test root Config uses defaults when project_handlers is missing."""
        config = Config.model_validate({"version": "2.0"})
        assert config.project_handlers.enabled is True
        assert config.project_handlers.path == ".claude/project-handlers"

    def test_root_config_serializes_project_handlers(self) -> None:
        """Test that project_handlers is included in YAML serialization."""
        config = Config(
            project_handlers=ProjectHandlersConfig(
                enabled=False,
                path="custom/path",
            )
        )
        yaml_output = config.to_yaml()
        parsed = yaml.safe_load(yaml_output)
        assert "project_handlers" in parsed
        assert parsed["project_handlers"]["enabled"] is False
        assert parsed["project_handlers"]["path"] == "custom/path"
