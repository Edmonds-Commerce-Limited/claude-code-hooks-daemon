"""Tests for handler dependency system (shares_options_with).

These tests verify that handlers can inherit configuration options from parent
handlers and that dependency validation works correctly at config load time.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry


@pytest.fixture(autouse=True)
def mock_project_context():
    """Mock ProjectContext for tests that validate config.

    Config validation instantiates handlers to check dependencies.
    Handlers may call ProjectContext.project_root() in __init__().
    This fixture mocks it to return a dummy path.
    """
    with patch("claude_code_hooks_daemon.core.project_context.ProjectContext.project_root") as mock:
        mock.return_value = Path("/tmp/test")
        yield mock


def test_shares_options_with_parent_enabled() -> None:
    """Test that child handler inherits options from parent when both are enabled."""
    # Create config with parent and child both enabled
    config_data = {
        "version": "1.0",
        "handlers": {
            "pre_tool_use": {
                "markdown_organization": {
                    "enabled": True,
                    "options": {
                        "track_plans_in_project": "CLAUDE/Plan",
                        "plan_workflow_docs": "CLAUDE/PlanWorkflow.md",
                    },
                },
                "plan_number_helper": {
                    "enabled": True,
                    "options": {},  # Should inherit from parent
                },
            }
        },
    }

    # Validate config (should not raise)
    config = Config.model_validate(config_data)
    assert config is not None

    # Register handlers and verify child got parent's options
    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()

    count = registry.register_all(
        router,
        config={
            "pre_tool_use": {
                "markdown_organization": {
                    "enabled": True,
                    "options": {
                        "track_plans_in_project": "CLAUDE/Plan",
                        "plan_workflow_docs": "CLAUDE/PlanWorkflow.md",
                    },
                },
                "plan_number_helper": {
                    "enabled": True,
                    "options": {},
                },
            }
        },
    )

    assert count > 0

    # Verify child handler has parent's options
    handlers = router.get_chain(EventType.PRE_TOOL_USE).handlers
    plan_helper = next((h for h in handlers if h.name == "plan-number-helper"), None)
    assert plan_helper is not None
    assert hasattr(plan_helper, "_track_plans_in_project")
    assert plan_helper._track_plans_in_project == "CLAUDE/Plan"  # type: ignore[attr-defined]
    assert hasattr(plan_helper, "_plan_workflow_docs")
    assert plan_helper._plan_workflow_docs == "CLAUDE/PlanWorkflow.md"  # type: ignore[attr-defined]


def test_shares_options_with_parent_disabled_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Test that config validation FAILS FAST if child is enabled but parent is disabled.

    This is FAIL FAST behavior - config should raise ValueError with helpful message.
    Per user feedback: config should fail fast and loud so it can be properly fixed.
    """
    from pydantic import ValidationError

    config_data = {
        "version": "1.0",
        "handlers": {
            "pre_tool_use": {
                "markdown_organization": {
                    "enabled": False,  # Parent disabled
                },
                "plan_number_helper": {
                    "enabled": True,  # Child enabled - should FAIL
                },
            }
        },
    }

    # Config should FAIL with ValidationError (FAIL FAST behavior)
    with pytest.raises(ValidationError) as exc_info:
        config = Config.model_validate(config_data)

    # Error message should be helpful and mention both handlers
    error_message = str(exc_info.value)
    assert "plan_number_helper" in error_message
    assert "markdown_organization" in error_message

    # Should provide helpful guidance about enabling/disabling
    assert "enable" in error_message.lower()
    assert "disable" in error_message.lower()


def test_child_options_override_parent() -> None:
    """Test that child handler can override specific parent options."""
    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()

    # Child overrides track_plans_in_project but inherits plan_workflow_docs
    count = registry.register_all(
        router,
        config={
            "pre_tool_use": {
                "markdown_organization": {
                    "enabled": True,
                    "options": {
                        "track_plans_in_project": "CLAUDE/Plan",
                        "plan_workflow_docs": "CLAUDE/PlanWorkflow.md",
                    },
                },
                "plan_number_helper": {
                    "enabled": True,
                    "options": {
                        "track_plans_in_project": "CustomPath/Plans",  # Override
                    },
                },
            }
        },
    )

    assert count > 0

    # Verify child has overridden value and inherited value
    handlers = router.get_chain(EventType.PRE_TOOL_USE).handlers
    plan_helper = next((h for h in handlers if h.name == "plan-number-helper"), None)
    assert plan_helper is not None
    assert (
        plan_helper._track_plans_in_project == "CustomPath/Plans"
    )  # Overridden  # type: ignore[attr-defined]
    assert (
        plan_helper._plan_workflow_docs == "CLAUDE/PlanWorkflow.md"
    )  # Inherited  # type: ignore[attr-defined]


def test_parent_and_child_both_disabled_succeeds() -> None:
    """Test that both parent and child disabled is valid (no dependency check needed)."""
    config_data = {
        "version": "1.0",
        "handlers": {
            "pre_tool_use": {
                "markdown_organization": {
                    "enabled": False,
                },
                "plan_number_helper": {
                    "enabled": False,  # Both disabled - OK
                },
            }
        },
    }

    # Should not raise
    config = Config.model_validate(config_data)
    assert config is not None


def test_parent_enabled_child_disabled_succeeds() -> None:
    """Test that parent enabled, child disabled is valid."""
    config_data = {
        "version": "1.0",
        "handlers": {
            "pre_tool_use": {
                "markdown_organization": {
                    "enabled": True,
                },
                "plan_number_helper": {
                    "enabled": False,  # Child disabled - OK
                },
            }
        },
    }

    # Should not raise
    config = Config.model_validate(config_data)
    assert config is not None


def test_handler_without_parent_dependency_works() -> None:
    """Test that handlers without shares_options_with work normally."""
    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()

    # Enable handler without parent dependency
    count = registry.register_all(
        router,
        config={
            "pre_tool_use": {
                "destructive_git": {
                    "enabled": True,
                },
            }
        },
    )

    assert count > 0
    handlers = router.get_chain(EventType.PRE_TOOL_USE).handlers
    assert any(h.name == "prevent-destructive-git" for h in handlers)


def test_missing_parent_in_config_uses_defaults() -> None:
    """Test that if parent is not in config, it defaults to enabled (validation passes)."""
    config_data = {
        "version": "1.0",
        "handlers": {
            "pre_tool_use": {
                # markdown_organization not in config (defaults to enabled)
                "plan_number_helper": {
                    "enabled": True,  # Should be OK since parent defaults to enabled
                },
            }
        },
    }

    # Should not raise since parent defaults to enabled
    config = Config.model_validate(config_data)
    assert config is not None
