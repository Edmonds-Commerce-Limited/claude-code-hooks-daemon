"""Test that handler-specific options go in options dict, not as extra fields.

CRITICAL: HandlerConfig should NOT use extra="allow" to capture arbitrary fields.
Handler-specific options should go in the explicit options: dict field.
"""

import pytest

from claude_code_hooks_daemon.config.models import HandlerConfig


class TestHandlerConfigOptions:
    """Test HandlerConfig options dict structure."""

    def test_handler_specific_options_in_options_dict(self):
        """CRITICAL: Handler-specific options must be in options dict, not top-level."""
        # Correct structure - options in options dict
        config = HandlerConfig(
            enabled=True,
            priority=50,
            options={
                "track_plans_in_project": "CLAUDE/Plan",
                "plan_workflow_docs": "CLAUDE/PlanWorkflow.md",
            },
        )

        assert config.enabled is True
        assert config.priority == 50
        assert config.options["track_plans_in_project"] == "CLAUDE/Plan"
        assert config.options["plan_workflow_docs"] == "CLAUDE/PlanWorkflow.md"

    def test_extra_fields_not_allowed_at_top_level(self):
        """CRITICAL: HandlerConfig should NOT accept extra fields at top level."""
        # This should FAIL - extra fields should not be allowed
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            HandlerConfig(
                enabled=True,
                priority=50,
                track_plans_in_project="CLAUDE/Plan",  # WRONG - should be in options
                plan_workflow_docs="CLAUDE/PlanWorkflow.md",  # WRONG - should be in options
            )

    def test_model_dump_includes_options(self):
        """Verify model_dump() includes options dict."""
        config = HandlerConfig(
            enabled=True,
            priority=50,
            options={
                "track_plans_in_project": "CLAUDE/Plan",
            },
        )

        dump = config.model_dump()
        assert dump["enabled"] is True
        assert dump["priority"] == 50
        assert dump["options"]["track_plans_in_project"] == "CLAUDE/Plan"
        assert "track_plans_in_project" not in dump  # Should NOT be at top level
