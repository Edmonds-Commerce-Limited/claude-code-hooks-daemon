"""Tests for the measured schema token costs table (Plan 00293).

The Phase 1 measurements (RESEARCH-tool-disable.md) are the report's token
grounding; the disable routes must match what the research established —
bare-name deny/settings switches remove schemas, specifier rules do not.
"""

from claude_code_hooks_daemon.tool_report.costs import (
    DEFERRED_NAME_TOKENS,
    MEASURED_SCHEMA_TOKENS,
    disable_route_for,
)


class TestMeasuredCosts:
    def test_artifact_measurement_is_present_and_upfront(self) -> None:
        cost = MEASURED_SCHEMA_TOKENS["Artifact"]
        assert cost.tokens == 6038
        assert cost.loading == "upfront"

    def test_deferred_tools_cost_the_name_line_only(self) -> None:
        cost = MEASURED_SCHEMA_TOKENS["WebFetch"]
        assert cost.loading == "deferred"
        assert cost.tokens == DEFERRED_NAME_TOKENS

    def test_every_loading_class_is_a_known_value(self) -> None:
        assert {cost.loading for cost in MEASURED_SCHEMA_TOKENS.values()} <= {
            "upfront",
            "deferred",
        }


class TestDisableRoutes:
    def test_artifact_route_names_the_settings_switch(self) -> None:
        route = disable_route_for("Artifact")
        assert "enableArtifact" in route
        assert "source_disable" in route

    def test_generic_route_names_permissions_deny_with_the_tool(self) -> None:
        route = disable_route_for("NotebookEdit")
        assert "permissions.deny" in route
        assert "NotebookEdit" in route
