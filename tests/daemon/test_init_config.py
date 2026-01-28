"""Tests for config initialization command."""

import importlib
import pkgutil
import re
import tempfile
from pathlib import Path
from typing import ClassVar

import pytest
import yaml

from claude_code_hooks_daemon.config.validator import ConfigValidator
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.daemon.init_config import (
    ConfigTemplate,
    generate_config,
)


def _to_snake_case(name: str) -> str:
    """Convert CamelCase to snake_case."""
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _discover_all_handlers() -> dict[str, list[str]]:
    """Discover all handler classes in the codebase.

    Returns:
        Dict mapping event_type to list of handler config keys (snake_case)
    """
    handlers_by_event: dict[str, list[str]] = {}

    event_dirs = [
        "pre_tool_use",
        "post_tool_use",
        "session_start",
        "session_end",
        "pre_compact",
        "user_prompt_submit",
        "permission_request",
        "notification",
        "stop",
        "subagent_stop",
        "status_line",
    ]

    for event_dir in event_dirs:
        handlers_by_event[event_dir] = []
        try:
            event_module = importlib.import_module(f"claude_code_hooks_daemon.handlers.{event_dir}")
        except ImportError:
            continue

        if not hasattr(event_module, "__path__"):
            continue

        for _importer, modname, _ispkg in pkgutil.iter_modules(event_module.__path__):
            if modname.startswith("_") or modname == "hello_world":
                continue

            try:
                module = importlib.import_module(
                    f"claude_code_hooks_daemon.handlers.{event_dir}.{modname}"
                )
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, Handler)
                        and attr is not Handler
                        and not attr.__name__.startswith("_")
                        and "HelloWorld" not in attr.__name__
                    ):
                        config_key = _to_snake_case(attr.__name__)
                        handlers_by_event[event_dir].append(config_key)
            except Exception:
                pass

    return handlers_by_event


class TestConfigTemplate:
    """Test config template generation."""

    def test_minimal_config_generation(self):
        """Test that minimal config is valid and contains essentials."""
        config_yaml = generate_config(mode="minimal")

        # Parse YAML
        config = yaml.safe_load(config_yaml)

        # Should be valid
        errors = ConfigValidator.validate(config, validate_handler_names=False)
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
        errors = ConfigValidator.validate(config, validate_handler_names=False)
        assert errors == [], f"Generated config should be valid, got errors: {errors}"

        # Check all 11 event types present
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
            "status_line",
        }
        assert set(config["handlers"].keys()) == expected_events

    def test_default_config_generation(self):
        """Test that default mode generates full config."""
        config_yaml = generate_config()  # No mode specified

        # Parse YAML
        config = yaml.safe_load(config_yaml)

        # Should be valid
        errors = ConfigValidator.validate(config, validate_handler_names=False)
        assert errors == [], f"Generated config should be valid, got errors: {errors}"

        # Should have all event types (default is full)
        assert len(config["handlers"]) == 11

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
        """Test that full mode includes all 11 event types."""
        config_yaml = generate_config(mode="full")
        config = yaml.safe_load(config_yaml)

        event_types = list(config["handlers"].keys())
        assert len(event_types) == 11

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
            "status_line",
        ]

        for event in expected:
            assert event in event_types, f"Missing event type: {event}"

    def test_pre_tool_use_has_destructive_git_example(self):
        """Test that pre_tool_use section includes destructive_git_handler."""
        config_yaml = generate_config(mode="full")
        config = yaml.safe_load(config_yaml)

        assert "pre_tool_use" in config["handlers"]
        pre_tool_use = config["handlers"]["pre_tool_use"]

        # Should have destructive_git_handler as an enabled example
        assert "destructive_git_handler" in pre_tool_use
        assert pre_tool_use["destructive_git_handler"]["enabled"] is True
        assert pre_tool_use["destructive_git_handler"]["priority"] == 10

    def test_pre_tool_use_has_gh_issue_comments_enabled(self):
        """Test that pre_tool_use section includes gh_issue_comments_handler enabled."""
        config_yaml = generate_config(mode="full")
        config = yaml.safe_load(config_yaml)

        assert "pre_tool_use" in config["handlers"]
        pre_tool_use = config["handlers"]["pre_tool_use"]

        # Should have gh_issue_comments_handler as an enabled handler
        assert "gh_issue_comments_handler" in pre_tool_use
        assert pre_tool_use["gh_issue_comments_handler"]["enabled"] is True
        assert pre_tool_use["gh_issue_comments_handler"]["priority"] == 40

    def test_full_config_has_all_safety_handlers_enabled(self):
        """Test that full config enables all safety handlers by default."""
        config_yaml = generate_config(mode="full")
        config = yaml.safe_load(config_yaml)

        pre_tool_use = config["handlers"]["pre_tool_use"]

        # All safety handlers should be enabled
        safety_handlers = [
            "destructive_git_handler",
            "sed_blocker_handler",
            "absolute_path_handler",
            "worktree_file_copy_handler",
            "git_stash_handler",
        ]
        for handler in safety_handlers:
            assert handler in pre_tool_use, f"Missing handler: {handler}"
            assert pre_tool_use[handler]["enabled"] is True, f"{handler} not enabled"

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
            errors = ConfigValidator.validate(config, validate_handler_names=False)
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
            errors = ConfigValidator.validate(config, validate_handler_names=False)
            assert errors == []


class TestConfigHandlerCoverage:
    """TDD tests to ensure all handlers are included in default config.

    These tests will FAIL when new handlers are added but not included
    in the default configuration template. This enforces the principle
    that all handlers should be included and enabled by default.
    """

    # Handlers that are intentionally excluded from default config
    # (e.g., workflow-specific handlers that need explicit opt-in)
    EXCLUDED_HANDLERS: ClassVar[set[str]] = {
        # Plan workflow handlers - require CLAUDE/Plan/ directory structure
        "validate_plan_number_handler",
        "plan_time_estimates_handler",
        "plan_workflow_handler",
        "plan_number_helper_handler",
        "markdown_organization_handler",
        # NPM handler - project-specific
        "npm_command_handler",
        # Permission handlers - YOLO mode doesn't use these
        "auto_approve_reads_handler",
        # Git context injector - optional
        "git_context_injector_handler",
        # Workflow restoration - optional
        "workflow_state_restoration_handler",
        "workflow_state_pre_compact_handler",
        # YOLO container detection - auto-detects
        "yolo_container_detection_handler",
        # Reminder handlers - optional
        "remind_prompt_library_handler",
        "remind_validator_handler",
        # Stop handlers - optional
        "auto_continue_stop_handler",
        "task_completion_checker_handler",
        # ESLint validation - optional
        "validate_eslint_on_write_handler",
        "validate_sitemap_handler",
        # Status line handlers - project-specific
        "suggest_status_line_handler",
    }

    @pytest.fixture
    def discovered_handlers(self) -> dict[str, list[str]]:
        """Discover all handlers in codebase."""
        return _discover_all_handlers()

    @pytest.fixture
    def full_config(self) -> dict:
        """Generate and parse full config."""
        config_yaml = generate_config(mode="full")
        return yaml.safe_load(config_yaml)

    def test_generated_config_is_valid_yaml(self):
        """Generated config must be valid YAML."""
        config_yaml = generate_config(mode="full")
        try:
            config = yaml.safe_load(config_yaml)
            assert isinstance(config, dict), "Config must be a dict"
        except yaml.YAMLError as e:
            pytest.fail(f"Generated config is not valid YAML: {e}")

    def test_generated_config_passes_validation(self):
        """Generated config must pass ConfigValidator."""
        config_yaml = generate_config(mode="full")
        config = yaml.safe_load(config_yaml)
        errors = ConfigValidator.validate(config, validate_handler_names=False)
        assert errors == [], f"Config validation errors: {errors}"

    def test_all_pre_tool_use_handlers_in_config(
        self, discovered_handlers: dict[str, list[str]], full_config: dict
    ):
        """All PreToolUse handlers must be in config (or explicitly excluded)."""
        config_handlers = set(full_config["handlers"].get("pre_tool_use", {}).keys())
        discovered = set(discovered_handlers.get("pre_tool_use", []))

        # Remove excluded handlers
        expected = discovered - self.EXCLUDED_HANDLERS

        missing = expected - config_handlers
        assert not missing, (
            f"PreToolUse handlers missing from default config: {missing}\n"
            f"Add them to init_config.py or EXCLUDED_HANDLERS if intentional"
        )

    def test_all_post_tool_use_handlers_in_config(
        self, discovered_handlers: dict[str, list[str]], full_config: dict
    ):
        """All PostToolUse handlers must be in config (or explicitly excluded)."""
        config_handlers = set(full_config["handlers"].get("post_tool_use", {}).keys())
        discovered = set(discovered_handlers.get("post_tool_use", []))

        expected = discovered - self.EXCLUDED_HANDLERS

        missing = expected - config_handlers
        assert not missing, (
            f"PostToolUse handlers missing from default config: {missing}\n"
            f"Add them to init_config.py or EXCLUDED_HANDLERS if intentional"
        )

    def test_all_session_handlers_in_config(
        self, discovered_handlers: dict[str, list[str]], full_config: dict
    ):
        """All session handlers must be in config (or explicitly excluded)."""
        for event_type in ["session_start", "session_end"]:
            config_handlers = set(full_config["handlers"].get(event_type, {}).keys())
            discovered = set(discovered_handlers.get(event_type, []))

            expected = discovered - self.EXCLUDED_HANDLERS

            missing = expected - config_handlers
            assert not missing, (
                f"{event_type} handlers missing from default config: {missing}\n"
                f"Add them to init_config.py or EXCLUDED_HANDLERS if intentional"
            )

    def test_all_subagent_stop_handlers_in_config(
        self, discovered_handlers: dict[str, list[str]], full_config: dict
    ):
        """All SubagentStop handlers must be in config (or explicitly excluded)."""
        config_handlers = set(full_config["handlers"].get("subagent_stop", {}).keys())
        discovered = set(discovered_handlers.get("subagent_stop", []))

        expected = discovered - self.EXCLUDED_HANDLERS

        missing = expected - config_handlers
        assert not missing, (
            f"SubagentStop handlers missing from default config: {missing}\n"
            f"Add them to init_config.py or EXCLUDED_HANDLERS if intentional"
        )

    def test_all_pre_compact_handlers_in_config(
        self, discovered_handlers: dict[str, list[str]], full_config: dict
    ):
        """All PreCompact handlers must be in config (or explicitly excluded)."""
        config_handlers = set(full_config["handlers"].get("pre_compact", {}).keys())
        discovered = set(discovered_handlers.get("pre_compact", []))

        expected = discovered - self.EXCLUDED_HANDLERS

        missing = expected - config_handlers
        assert not missing, (
            f"PreCompact handlers missing from default config: {missing}\n"
            f"Add them to init_config.py or EXCLUDED_HANDLERS if intentional"
        )

    def test_enabled_handlers_have_priority(self, full_config: dict):
        """All enabled handlers must have a valid priority."""
        for event_type, handlers in full_config["handlers"].items():
            if not isinstance(handlers, dict):
                continue
            for handler_name, handler_config in handlers.items():
                if not isinstance(handler_config, dict):
                    continue
                if handler_config.get("enabled", True):
                    assert (
                        "priority" in handler_config
                    ), f"Handler {event_type}/{handler_name} is enabled but has no priority"
                    priority = handler_config["priority"]
                    assert isinstance(
                        priority, int
                    ), f"Handler {event_type}/{handler_name} priority must be int, got {type(priority)}"
                    assert (
                        1 <= priority <= 100
                    ), f"Handler {event_type}/{handler_name} priority {priority} out of range [1,100]"

    def test_handler_discovery_finds_handlers(self, discovered_handlers: dict[str, list[str]]):
        """Verify handler discovery is working."""
        # Should find at least some handlers in pre_tool_use
        assert (
            len(discovered_handlers.get("pre_tool_use", [])) > 5
        ), "Handler discovery should find multiple PreToolUse handlers"

    def test_no_unknown_handlers_in_config(
        self, discovered_handlers: dict[str, list[str]], full_config: dict
    ):
        """Config should not contain handlers that don't exist in codebase."""
        for event_type, handlers in full_config["handlers"].items():
            if not isinstance(handlers, dict):
                continue

            config_handlers = set(handlers.keys())
            discovered = set(discovered_handlers.get(event_type, []))

            unknown = config_handlers - discovered
            assert not unknown, (
                f"Config has handlers not found in codebase for {event_type}: {unknown}\n"
                f"Remove them from init_config.py or check handler class names"
            )
