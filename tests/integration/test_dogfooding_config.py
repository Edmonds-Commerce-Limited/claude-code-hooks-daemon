"""Integration test for dogfooding: Ensure project uses all its own handlers.

This test verifies that the hooks daemon project's own .claude/hooks-daemon.yaml
configuration has ALL production handlers enabled. This is critical for dogfooding -
the project should use all its own features.

CRITICAL: If this test fails, it means we're not dogfooding our own handlers!
Enable missing handlers in .claude/hooks-daemon.yaml.
"""

import importlib
import pkgutil
from pathlib import Path

import pytest
import yaml

from claude_code_hooks_daemon.core.handler import Handler


def discover_all_production_handlers() -> dict[str, list[str]]:
    """Discover all production handler classes (excluding hello_world test handlers).

    Returns:
        Dict mapping event_type to list of handler class names (e.g., "DestructiveGitHandler")
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
            # Skip private modules and test handlers
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
                        and "Base" not in attr.__name__
                    ):
                        handlers_by_event[event_dir].append(attr.__name__)
            except Exception:
                pass

    return handlers_by_event


def load_project_config() -> dict:
    """Load the project's .claude/hooks-daemon.yaml configuration.

    Returns:
        Parsed YAML configuration dictionary
    """
    config_path = Path(__file__).parent.parent.parent / ".claude" / "hooks-daemon.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def class_name_to_snake_case(class_name: str) -> str:
    """Convert ClassName to snake_case config key.

    Examples:
        DestructiveGitHandler -> destructive_git
        SedBlockerHandler -> sed_blocker
        AutoApproveReadsHandler -> auto_approve_reads
    """
    # Remove Handler suffix if present
    if class_name.endswith("Handler"):
        class_name = class_name[:-7]  # Remove "Handler"

    # Convert PascalCase to snake_case
    import re

    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", class_name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


class TestDogfoodingConfiguration:
    """Test that this project dogfoods all its own handlers.

    DOGFOODING PRINCIPLE: ALL handlers discovered in the codebase MUST be
    enabled in .claude/hooks-daemon.yaml. No exceptions. This ensures:
    1. We use every feature we build
    2. Adding a new handler automatically requires enabling it
    3. We catch configuration drift immediately
    """

    def test_all_production_handlers_are_enabled(self):
        """DOGFOODING: All production handlers must be enabled in project config.

        This test dynamically discovers all handler classes and verifies each
        is enabled. If you add a new handler, this test will fail until you
        enable it in .claude/hooks-daemon.yaml.
        """
        # Discover all production handlers in the codebase
        discovered = discover_all_production_handlers()

        # Load project configuration
        config = load_project_config()
        handlers_config = config.get("handlers", {})

        # Opt-in handlers that are intentionally disabled by default.
        # These handlers change fundamental behavior and must be explicitly enabled.
        opt_in_handlers = frozenset(
            {
                "orchestrator_only",  # Blocks all work tools, opt-in only
                "validate_instruction_content",  # False positives on this project's own CLAUDE.md/README.md
            }
        )

        # Track missing handlers
        missing_handlers: dict[str, list[str]] = {}

        for event_type, handler_classes in discovered.items():
            event_config = handlers_config.get(event_type, {})

            # Handle empty sections (e.g., "session_end: {}" becomes None)
            if event_config is None:
                event_config = {}

            for handler_class in handler_classes:
                # Convert handler class name to expected config key
                expected_config_key = class_name_to_snake_case(handler_class)

                # Skip opt-in handlers (intentionally disabled by default)
                if expected_config_key in opt_in_handlers:
                    continue

                # Check if handler exists in config and is enabled
                if expected_config_key in event_config:
                    handler_cfg = event_config[expected_config_key]
                    if not handler_cfg.get("enabled", False):
                        if event_type not in missing_handlers:
                            missing_handlers[event_type] = []
                        missing_handlers[event_type].append(
                            f"{handler_class} (config key: {expected_config_key}) is DISABLED"
                        )
                else:
                    # Handler exists in code but not in config
                    if event_type not in missing_handlers:
                        missing_handlers[event_type] = []
                    missing_handlers[event_type].append(
                        f"{handler_class} is NOT IN CONFIG (expected key: {expected_config_key})"
                    )

        # Assert all handlers are enabled
        if missing_handlers:
            error_msg = [
                "\n❌ DOGFOODING FAILURE: This project is not using all its own handlers!",
                "\nMissing or disabled handlers by event type:",
            ]
            for event_type, handlers in sorted(missing_handlers.items()):
                error_msg.append(f"\n{event_type}:")
                for handler in handlers:
                    error_msg.append(f"  - {handler}")

            error_msg.append(
                "\n\n🔧 ACTION REQUIRED: Enable these handlers in .claude/hooks-daemon.yaml"
            )
            error_msg.append(
                "This project MUST dogfood all its own features (except optional ones)."
            )

            pytest.fail("".join(error_msg))

    def test_strict_mode_is_enabled(self):
        """DOGFOODING: Strict mode must be enabled for FAIL FAST behavior."""
        config = load_project_config()

        daemon_config = config.get("daemon", {})
        input_validation = daemon_config.get("input_validation", {})

        assert input_validation.get("enabled", False) is True, (
            "Input validation must be enabled for dogfooding. "
            "Set daemon.input_validation.enabled: true"
        )

        assert daemon_config.get("strict_mode", False) is True, (
            "Daemon strict mode must be enabled for dogfooding (FAIL FAST on ALL errors). "
            "Set daemon.strict_mode: true"
        )

    def test_hello_world_handlers_are_disabled(self):
        """Test handlers (hello_world) must be disabled in production config."""
        config = load_project_config()

        # Check daemon-level setting
        assert config.get("daemon", {}).get("enable_hello_world_handlers", True) is False, (
            "Hello world test handlers must be disabled. "
            "Set daemon.enable_hello_world_handlers: false"
        )

        # Check individual handler configs
        handlers_config = config.get("handlers", {})
        for event_type, event_handlers in handlers_config.items():
            if isinstance(event_handlers, dict):
                for handler_name, handler_cfg in event_handlers.items():
                    if "hello_world" in handler_name.lower():
                        assert (
                            handler_cfg.get("enabled", True) is False
                        ), f"Test handler {event_type}.{handler_name} must be disabled"

    def test_config_has_all_event_types(self):
        """Config must have sections for all supported event types."""
        config = load_project_config()
        handlers_config = config.get("handlers", {})

        expected_events = {
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
        }

        config_events = set(handlers_config.keys())

        missing_events = expected_events - config_events
        assert not missing_events, (
            f"Config missing sections for event types: {missing_events}\n"
            "Add these sections to .claude/hooks-daemon.yaml"
        )
