"""Tests for plan_workflow config injection via PLANNING tag.

These tests verify that handlers with the PLANNING tag receive plan_workflow
configuration (directory, workflow_docs) from the top-level plan_workflow
config section, replacing the old shares_options_with inheritance pattern.
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import Config, PlanWorkflowConfig
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry


@pytest.fixture(autouse=True)
def mock_project_context():
    """Mock ProjectContext for handler instantiation tests."""
    with patch("claude_code_hooks_daemon.core.project_context.ProjectContext.project_root") as mock:
        mock.return_value = Path("/tmp/test")
        yield mock


def _make_pre_tool_use_config(**overrides: dict[str, Any]) -> dict[str, Any]:
    """Build a minimal pre_tool_use config dict."""
    base: dict[str, Any] = {
        "markdown_organization": {"enabled": True},
        "plan_number_helper": {"enabled": True},
        "validate_plan_number": {"enabled": True},
    }
    base.update(overrides)
    return base


def test_plan_workflow_injected_into_planning_tagged_handlers() -> None:
    """Plan workflow config is injected into handlers with PLANNING tag."""
    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()

    plan_workflow = PlanWorkflowConfig(
        enabled=True,
        directory="CLAUDE/Plan",
        workflow_docs="CLAUDE/PlanWorkflow.md",
    )

    count = registry.register_all(
        router,
        config={"pre_tool_use": _make_pre_tool_use_config()},
        plan_workflow=plan_workflow,
    )

    assert count > 0

    handlers = router.get_chain(EventType.PRE_TOOL_USE).handlers

    # plan_number_helper should receive plan_workflow values
    plan_helper = next((h for h in handlers if h.name == "plan-number-helper"), None)
    assert plan_helper is not None
    assert plan_helper._track_plans_in_project == "CLAUDE/Plan"
    assert plan_helper._plan_workflow_docs == "CLAUDE/PlanWorkflow.md"

    # validate_plan_number should also receive plan_workflow values
    validator = next((h for h in handlers if h.name == "validate-plan-number"), None)
    assert validator is not None
    assert validator._track_plans_in_project == "CLAUDE/Plan"

    # markdown_organization should also receive plan_workflow values (has PLANNING tag)
    md_org = next((h for h in handlers if h.name == "enforce-markdown-organization"), None)
    assert md_org is not None
    assert md_org._track_plans_in_project == "CLAUDE/Plan"
    assert md_org._plan_workflow_docs == "CLAUDE/PlanWorkflow.md"


def test_plan_workflow_disabled_sets_none() -> None:
    """When plan_workflow.enabled is False, handlers get None for plan attributes."""
    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()

    plan_workflow = PlanWorkflowConfig(
        enabled=False,
        directory="CLAUDE/Plan",
        workflow_docs="CLAUDE/PlanWorkflow.md",
    )

    count = registry.register_all(
        router,
        config={"pre_tool_use": _make_pre_tool_use_config()},
        plan_workflow=plan_workflow,
    )

    assert count > 0

    handlers = router.get_chain(EventType.PRE_TOOL_USE).handlers

    plan_helper = next((h for h in handlers if h.name == "plan-number-helper"), None)
    assert plan_helper is not None
    assert plan_helper._track_plans_in_project is None
    assert plan_helper._plan_workflow_docs is None


def test_plan_workflow_not_provided_uses_handler_options() -> None:
    """When plan_workflow is None, handler options still work (backward compat)."""
    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()

    # No plan_workflow, but handler has options
    count = registry.register_all(
        router,
        config={
            "pre_tool_use": {
                "markdown_organization": {
                    "enabled": True,
                    "options": {
                        "track_plans_in_project": "Custom/Plans",
                        "plan_workflow_docs": "Custom/Workflow.md",
                    },
                },
            }
        },
        plan_workflow=None,
    )

    assert count > 0

    handlers = router.get_chain(EventType.PRE_TOOL_USE).handlers
    md_org = next((h for h in handlers if h.name == "enforce-markdown-organization"), None)
    assert md_org is not None
    assert md_org._track_plans_in_project == "Custom/Plans"
    assert md_org._plan_workflow_docs == "Custom/Workflow.md"


def test_plan_workflow_overrides_handler_options() -> None:
    """Top-level plan_workflow overrides handler-level options (source of truth)."""
    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()

    plan_workflow = PlanWorkflowConfig(
        enabled=True,
        directory="TopLevel/Plans",
        workflow_docs="TopLevel/Workflow.md",
    )

    # Handler also has options — plan_workflow should win
    count = registry.register_all(
        router,
        config={
            "pre_tool_use": {
                "markdown_organization": {
                    "enabled": True,
                    "options": {
                        "track_plans_in_project": "Handler/Plans",
                        "plan_workflow_docs": "Handler/Workflow.md",
                    },
                },
            }
        },
        plan_workflow=plan_workflow,
    )

    assert count > 0

    handlers = router.get_chain(EventType.PRE_TOOL_USE).handlers
    md_org = next((h for h in handlers if h.name == "enforce-markdown-organization"), None)
    assert md_org is not None
    # plan_workflow should take precedence
    assert md_org._track_plans_in_project == "TopLevel/Plans"
    assert md_org._plan_workflow_docs == "TopLevel/Workflow.md"


def test_non_planning_handler_not_affected_by_plan_workflow() -> None:
    """Handlers without PLANNING tag are not affected by plan_workflow."""
    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()

    plan_workflow = PlanWorkflowConfig(
        enabled=True,
        directory="CLAUDE/Plan",
    )

    count = registry.register_all(
        router,
        config={
            "pre_tool_use": {
                "destructive_git": {"enabled": True},
            }
        },
        plan_workflow=plan_workflow,
    )

    assert count > 0
    handlers = router.get_chain(EventType.PRE_TOOL_USE).handlers
    git_handler = next((h for h in handlers if h.name == "prevent-destructive-git"), None)
    assert git_handler is not None
    assert "planning" not in git_handler.tags


def test_handlers_independent_no_shares_options_with() -> None:
    """Plan handlers no longer use shares_options_with (decoupled)."""
    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()

    plan_workflow = PlanWorkflowConfig(enabled=True, directory="CLAUDE/Plan")

    # markdown_organization disabled, plan_number_helper enabled — should work fine
    count = registry.register_all(
        router,
        config={
            "pre_tool_use": {
                "markdown_organization": {"enabled": False},
                "plan_number_helper": {"enabled": True},
            }
        },
        plan_workflow=plan_workflow,
    )

    assert count > 0
    handlers = router.get_chain(EventType.PRE_TOOL_USE).handlers
    plan_helper = next((h for h in handlers if h.name == "plan-number-helper"), None)
    assert plan_helper is not None
    assert plan_helper.shares_options_with is None
    # Still receives plan_workflow config via PLANNING tag
    assert plan_helper._track_plans_in_project == "CLAUDE/Plan"


def test_config_migration_from_handler_options() -> None:
    """Config migration creates plan_workflow from old handler options."""
    config_data = {
        "version": "2.0",
        "handlers": {
            "pre_tool_use": {
                "markdown_organization": {
                    "enabled": True,
                    "options": {
                        "track_plans_in_project": "CLAUDE/Plan",
                        "plan_workflow_docs": "CLAUDE/PlanWorkflow.md",
                    },
                },
            }
        },
    }

    config = Config.model_validate(config_data)
    assert config.plan_workflow.enabled is True
    assert config.plan_workflow.directory == "CLAUDE/Plan"
    assert config.plan_workflow.workflow_docs == "CLAUDE/PlanWorkflow.md"


def test_config_migration_skipped_when_plan_workflow_explicit() -> None:
    """Migration doesn't override explicit plan_workflow section."""
    config_data = {
        "version": "2.0",
        "plan_workflow": {
            "enabled": True,
            "directory": "Explicit/Plans",
            "workflow_docs": "Explicit/Workflow.md",
        },
        "handlers": {
            "pre_tool_use": {
                "markdown_organization": {
                    "enabled": True,
                    "options": {
                        "track_plans_in_project": "Handler/Plans",
                        "plan_workflow_docs": "Handler/Workflow.md",
                    },
                },
            }
        },
    }

    config = Config.model_validate(config_data)
    # Explicit plan_workflow should NOT be overridden by handler options
    assert config.plan_workflow.directory == "Explicit/Plans"
    assert config.plan_workflow.workflow_docs == "Explicit/Workflow.md"


def test_config_no_handler_options_uses_defaults() -> None:
    """Without handler options or plan_workflow, defaults are used."""
    config_data = {
        "version": "2.0",
        "handlers": {
            "pre_tool_use": {
                "markdown_organization": {"enabled": True},
            }
        },
    }

    config = Config.model_validate(config_data)
    assert config.plan_workflow.enabled is True
    assert config.plan_workflow.directory == "CLAUDE/Plan"
    assert config.plan_workflow.workflow_docs == "CLAUDE/PlanWorkflow.md"
