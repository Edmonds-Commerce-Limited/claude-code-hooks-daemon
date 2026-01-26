"""Tests for config initialization command."""

import tempfile
from pathlib import Path

import yaml

from claude_code_hooks_daemon.config.validator import ConfigValidator
from claude_code_hooks_daemon.daemon.init_config import (
    ConfigTemplate,
    generate_config,
)


class TestConfigTemplate:
    """Test config template generation."""

    def test_minimal_config_generation(self):
        """Test that minimal config is valid and contains essentials."""
        config_yaml = generate_config(mode="minimal")

        # Parse YAML
        config = yaml.safe_load(config_yaml)

        # Should be valid
        errors = ConfigValidator.validate(config)
        assert errors == [], f"Generated config should be valid, got errors: {errors}"

        # Check essential fields
        assert config["version"] == "1.0"
        assert "daemon" in config
        assert config["daemon"]["idle_timeout_seconds"] == 600
        assert config["daemon"]["log_level"] == "INFO"
        assert "handlers" in config

    def test_full_config_generation(self):
        """Test that full config is valid and contains all events."""
        config_yaml = generate_config(mode="full")

        # Parse YAML
        config = yaml.safe_load(config_yaml)

        # Should be valid
        errors = ConfigValidator.validate(config)
        assert errors == [], f"Generated config should be valid, got errors: {errors}"

        # Check all 10 event types present
        expected_events = {
            "pre_tool_use",
            "post_tool_use",
            "permission_request",
            "notification",
            "user_prompt_submit",
            "session_start",
            "session_end",
            "stop",
            "subagent_stop",
            "pre_compact",
        }
        assert set(config["handlers"].keys()) == expected_events

    def test_default_config_generation(self):
        """Test that default mode generates full config."""
        config_yaml = generate_config()  # No mode specified

        # Parse YAML
        config = yaml.safe_load(config_yaml)

        # Should be valid
        errors = ConfigValidator.validate(config)
        assert errors == [], f"Generated config should be valid, got errors: {errors}"

        # Should have all event types (default is full)
        assert len(config["handlers"]) == 10

    def test_config_contains_comments(self):
        """Test that generated config contains helpful comments."""
        config_yaml = generate_config(mode="full")

        # Should contain explanatory comments
        assert "# Daemon Settings" in config_yaml or "Daemon" in config_yaml
        assert "# Handler Configuration" in config_yaml or "handlers:" in config_yaml

    def test_config_contains_example_handlers(self):
        """Test that full config contains commented example handlers."""
        config_yaml = generate_config(mode="full")

        # Should contain example handler references
        assert "destructive_git" in config_yaml

    def test_minimal_config_has_no_examples(self):
        """Test that minimal config has minimal content."""
        minimal_yaml = generate_config(mode="minimal")
        full_yaml = generate_config(mode="full")

        # Minimal should be shorter than full
        assert len(minimal_yaml) < len(full_yaml)

    def test_generated_config_is_valid_yaml(self):
        """Test that generated config is parseable YAML."""
        for mode in ["minimal", "full"]:
            config_yaml = generate_config(mode=mode)

            # Should parse without errors
            try:
                config = yaml.safe_load(config_yaml)
                assert isinstance(config, dict)
            except yaml.YAMLError as e:
                raise AssertionError(f"Generated {mode} config is not valid YAML: {e}") from e

    def test_version_field_present(self):
        """Test that version field is present and correct."""
        config_yaml = generate_config(mode="minimal")
        config = yaml.safe_load(config_yaml)

        assert "version" in config
        assert config["version"] == "1.0"

    def test_daemon_section_present(self):
        """Test that daemon section is present with required fields."""
        config_yaml = generate_config(mode="minimal")
        config = yaml.safe_load(config_yaml)

        assert "daemon" in config
        assert "idle_timeout_seconds" in config["daemon"]
        assert "log_level" in config["daemon"]

    def test_handlers_section_present(self):
        """Test that handlers section is present."""
        config_yaml = generate_config(mode="minimal")
        config = yaml.safe_load(config_yaml)

        assert "handlers" in config
        assert isinstance(config["handlers"], dict)

    def test_plugins_section_present(self):
        """Test that plugins section is present."""
        config_yaml = generate_config(mode="full")
        config = yaml.safe_load(config_yaml)

        assert "plugins" in config
        assert isinstance(config["plugins"], list)

    def test_all_event_types_in_full_mode(self):
        """Test that full mode includes all 10 event types."""
        config_yaml = generate_config(mode="full")
        config = yaml.safe_load(config_yaml)

        event_types = list(config["handlers"].keys())
        assert len(event_types) == 10

        expected = [
            "pre_tool_use",
            "post_tool_use",
            "permission_request",
            "notification",
            "user_prompt_submit",
            "session_start",
            "session_end",
            "stop",
            "subagent_stop",
            "pre_compact",
        ]

        for event in expected:
            assert event in event_types, f"Missing event type: {event}"

    def test_pre_tool_use_has_destructive_git_example(self):
        """Test that pre_tool_use section includes destructive_git handler."""
        config_yaml = generate_config(mode="full")
        config = yaml.safe_load(config_yaml)

        assert "pre_tool_use" in config["handlers"]
        pre_tool_use = config["handlers"]["pre_tool_use"]

        # Should have destructive_git as an enabled example
        assert "destructive_git" in pre_tool_use
        assert pre_tool_use["destructive_git"]["enabled"] is True
        assert pre_tool_use["destructive_git"]["priority"] == 10

    def test_config_template_docstring(self):
        """Test that ConfigTemplate class has proper documentation."""
        # Should have class and method docstrings
        assert ConfigTemplate.__doc__ is not None
        assert ConfigTemplate.generate_minimal.__doc__ is not None
        assert ConfigTemplate.generate_full.__doc__ is not None


class TestConfigTemplateWrite:
    """Test writing config to file."""

    def test_write_config_to_file(self):
        """Test that config can be written to file and re-read."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".claude" / "hooks-daemon.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)

            # Generate and write config
            config_yaml = generate_config(mode="minimal")
            config_path.write_text(config_yaml)

            # Re-read and validate
            config = yaml.safe_load(config_path.read_text())
            errors = ConfigValidator.validate(config)
            assert errors == []

    def test_write_full_config_to_file(self):
        """Test that full config can be written to file and re-read."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".claude" / "hooks-daemon.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)

            # Generate and write config
            config_yaml = generate_config(mode="full")
            config_path.write_text(config_yaml)

            # Re-read and validate
            config = yaml.safe_load(config_path.read_text())
            errors = ConfigValidator.validate(config)
            assert errors == []
