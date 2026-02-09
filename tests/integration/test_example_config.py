"""Test that example config exists and has correct structure.

This ensures upgrade script can reference a valid example config
when users need to replace their config due to validation errors.
"""

from pathlib import Path

import pytest
import yaml

from claude_code_hooks_daemon.constants import HandlerID, EventID


@pytest.fixture
def example_config_path() -> Path:
    """Path to example config file."""
    return Path(__file__).parent.parent.parent / ".claude" / "hooks-daemon.yaml.example"


@pytest.fixture
def example_config(example_config_path: Path) -> dict:
    """Load and parse example config."""
    with open(example_config_path) as f:
        return yaml.safe_load(f)


def test_example_config_exists(example_config_path: Path) -> None:
    """Example config file must exist for upgrade script reference."""
    assert example_config_path.exists(), (
        "Missing .claude/hooks-daemon.yaml.example - "
        "upgrade script references this file when config validation fails"
    )


def test_example_config_valid_yaml(example_config: dict) -> None:
    """Example config must be valid YAML."""
    assert isinstance(example_config, dict)
    assert "version" in example_config
    assert "daemon" in example_config
    assert "handlers" in example_config


def test_example_config_no_self_install_mode(example_config: dict) -> None:
    """Example config should NOT have self_install_mode (only for daemon's own dogfooding)."""
    daemon_config = example_config.get("daemon", {})
    assert "self_install_mode" not in daemon_config, (
        "self_install_mode should not be in example config - "
        "it's only for the daemon's own dogfooding"
    )


def test_example_config_safety_handlers_enabled(example_config: dict) -> None:
    """Safety handlers should be enabled by default in example config."""
    pre_tool_use = example_config["handlers"]["pre_tool_use"]

    safety_handlers = [
        "destructive_git",
        "sed_blocker",
        "absolute_path",
        "curl_pipe_shell",
        "pipe_blocker",
        "dangerous_permissions",
        "git_stash",
        "lock_file_edit_blocker",
        "pip_break_system",
        "sudo_pip",
    ]

    for handler in safety_handlers:
        assert handler in pre_tool_use, f"Safety handler {handler} missing from example config"
        assert pre_tool_use[handler]["enabled"] is True, (
            f"Safety handler {handler} should be enabled by default"
        )


def test_example_config_workflow_handlers_disabled(example_config: dict) -> None:
    """Workflow handlers should be disabled by default (project-specific)."""
    pre_tool_use = example_config["handlers"]["pre_tool_use"]

    workflow_handlers = [
        "plan_number_helper",
        "plan_workflow",
        "validate_plan_number",
        "plan_time_estimates",
        "plan_completion_advisor",
        "markdown_organization",
        "tdd_enforcement",
    ]

    for handler in workflow_handlers:
        if handler in pre_tool_use:
            assert pre_tool_use[handler]["enabled"] is False, (
                f"Workflow handler {handler} should be disabled by default "
                "(project-specific configuration)"
            )


def test_example_config_qa_handlers_disabled(example_config: dict) -> None:
    """QA suppression blockers should be disabled by default (opt-in strict mode)."""
    pre_tool_use = example_config["handlers"]["pre_tool_use"]

    qa_handlers = [
        "python_qa_suppression_blocker",
        "php_qa_suppression_blocker",
        "go_qa_suppression_blocker",
        "eslint_disable",
    ]

    for handler in qa_handlers:
        if handler in pre_tool_use:
            assert pre_tool_use[handler]["enabled"] is False, (
                f"QA handler {handler} should be disabled by default (opt-in for strict mode)"
            )


def test_example_config_all_events_covered(example_config: dict) -> None:
    """All event types should be present in example config."""
    handlers = example_config["handlers"]

    required_event_types = [
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

    for event_type in required_event_types:
        assert event_type in handlers, f"Event type {event_type} missing from example config"


def test_example_config_status_line_handlers_enabled(example_config: dict) -> None:
    """Status line handlers should be enabled by default."""
    status_line = example_config["handlers"]["status_line"]

    status_handlers = [
        "model_context",
        "git_branch",
        "git_repo_name",
        "daemon_stats",
        "account_display",
        "thinking_mode",
        "usage_tracking",
    ]

    for handler in status_handlers:
        assert handler in status_line, f"Status handler {handler} missing from example config"
        assert status_line[handler]["enabled"] is True, (
            f"Status handler {handler} should be enabled by default"
        )


def test_example_config_has_version_2(example_config: dict) -> None:
    """Example config should use version 2.0 format."""
    assert example_config["version"] == "2.0"


def test_example_config_input_validation_enabled(example_config: dict) -> None:
    """Input validation should be enabled by default."""
    daemon = example_config["daemon"]
    input_validation = daemon.get("input_validation", {})

    assert input_validation.get("enabled") is True
    assert input_validation.get("strict_mode") is True
    assert input_validation.get("log_validation_errors") is True


def test_example_config_includes_all_library_handlers(example_config: dict) -> None:
    """All library handlers must be present in example config (enabled or disabled).

    This test dynamically discovers all handlers from HandlerID constants
    and verifies each one is present in the example config.

    Excluded handlers:
    - Test handlers (hello_world_*, test_server)
    - Internal-only handlers (orchestrator_only)
    """
    # Get all handler constants from HandlerID class
    all_handlers = []
    for attr_name in dir(HandlerID):
        if attr_name.startswith("_"):
            continue
        attr = getattr(HandlerID, attr_name)
        if hasattr(attr, "config_key"):
            all_handlers.append(attr.config_key)

    # Exclude test and internal handlers
    excluded_handlers = {
        "hello_world_pre_tool_use",
        "hello_world_post_tool_use",
        "hello_world_session_start",
        "hello_world_session_end",
        "hello_world_stop",
        "hello_world_subagent_stop",
        "hello_world_user_prompt_submit",
        "hello_world_pre_compact",
        "hello_world_notification",
        "hello_world_permission_request",
        "test_server",
        "orchestrator_only",
    }

    library_handlers = [h for h in all_handlers if h not in excluded_handlers]

    # Flatten all handlers from example config
    config_handlers = set()
    for event_type, handlers in example_config["handlers"].items():
        for handler_name in handlers.keys():
            config_handlers.add(handler_name)

    # Check each library handler is present
    missing_handlers = []
    for handler in library_handlers:
        if handler not in config_handlers:
            missing_handlers.append(handler)

    assert not missing_handlers, (
        f"Example config missing {len(missing_handlers)} library handlers:\n"
        f"{', '.join(sorted(missing_handlers))}\n\n"
        f"All library handlers must be present (enabled or disabled) "
        f"so users know what's available."
    )


def test_example_config_no_test_handlers(example_config: dict) -> None:
    """Example config should not include test handlers (hello_world, etc).

    Test handlers are for development/debugging only and should not
    be in the example config that users copy.
    """
    # Flatten all handlers from example config
    config_handlers = set()
    for event_type, handlers in example_config["handlers"].items():
        for handler_name in handlers.keys():
            config_handlers.add(handler_name)

    test_handlers = [
        "hello_world_pre_tool_use",
        "hello_world_post_tool_use",
        "hello_world_session_start",
        "hello_world_session_end",
        "hello_world_stop",
        "hello_world_subagent_stop",
        "hello_world_user_prompt_submit",
        "hello_world_pre_compact",
        "hello_world_notification",
        "hello_world_permission_request",
        "test_server",
        "orchestrator_only",
    ]

    found_test_handlers = [h for h in test_handlers if h in config_handlers]

    assert not found_test_handlers, (
        f"Example config should not include test handlers: {', '.join(found_test_handlers)}"
    )
