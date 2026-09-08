"""The config-optimisation checklist is derived from the registry (Plan 00330).

Milestone B: ``optimise`` cannot silently omit a handler. Every registered
handler — built-in and nitpick pseudo-event alike — appears exactly once,
scored against the project's config and its own relevance verdict, and the
rendered report stays readable as coverage grows (Task 2.3): an area whose
relevant handlers are all enabled collapses to a count; only shortfalls and
not-applicable handlers are listed in detail.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config_optimisation.areas import Area
from claude_code_hooks_daemon.config_optimisation.checklist import (
    ChecklistItem,
    ItemStatus,
    build_checklist,
    render_report,
    report_as_json,
)
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.relevance import RelevanceContext
from claude_code_hooks_daemon.handlers.registry import iter_builtin_handler_classes
from claude_code_hooks_daemon.pseudo_events.registry import pseudo_event_handler_classes

_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _project_context() -> None:
    """Some handler constructors read ProjectContext; give them the repo's."""
    ProjectContext.initialize(_REPO_ROOT / ".claude" / "hooks-daemon.yaml")


def _context(root: Path) -> RelevanceContext:
    return RelevanceContext(project_root=root, languages=frozenset())


def _config(**handlers: dict[str, Any]) -> dict[str, Any]:
    """A config with ``handlers.<event>.<key>`` blocks and nitpick enabled."""
    return {
        "handlers": handlers,
        "pseudo_events": {
            "nitpick": {
                "enabled": True,
                "triggers": ["stop:1/1"],
                "handlers": {"hedging_language": {"enabled": True}},
            }
        },
    }


def _by_path(items: list[ChecklistItem]) -> dict[str, ChecklistItem]:
    return {item.config_path: item for item in items}


class TestCoverage:
    def test_every_registered_handler_appears_once(self, tmp_path: Path) -> None:
        items = build_checklist(_config(), _context(tmp_path))
        paths = [item.config_path for item in items]
        assert len(paths) == len(set(paths))

        expected = {
            f"handlers.{ref.event_dir}.{ref.config_key}" for ref in iter_builtin_handler_classes()
        }
        for name, entries in pseudo_event_handler_classes().items():
            expected.update(f"pseudo_events.{name}.handlers.{key}" for key in entries)
        assert set(paths) == expected

    def test_every_item_has_an_area_and_summary(self, tmp_path: Path) -> None:
        for item in build_checklist(_config(), _context(tmp_path)):
            assert isinstance(item.area, Area)
            assert item.summary


class TestEnabledResolution:
    def test_absent_handler_block_counts_as_enabled(self, tmp_path: Path) -> None:
        item = _by_path(build_checklist(_config(), _context(tmp_path)))[
            "handlers.pre_tool_use.destructive_git"
        ]
        assert item.enabled is True
        assert item.status is ItemStatus.OPTIMAL

    def test_disabled_relevant_handler_is_a_shortfall(self, tmp_path: Path) -> None:
        config = _config(pre_tool_use={"destructive_git": {"enabled": False}})
        item = _by_path(build_checklist(config, _context(tmp_path)))[
            "handlers.pre_tool_use.destructive_git"
        ]
        assert item.enabled is False
        assert item.status is ItemStatus.SHORTFALL

    def test_disabled_irrelevant_handler_is_not_applicable(self, tmp_path: Path) -> None:
        config = _config(post_tool_use={"goal_injection": {"enabled": False}})
        item = _by_path(build_checklist(config, _context(tmp_path)))[
            "handlers.post_tool_use.goal_injection"
        ]
        assert item.relevance.applicable is False
        assert item.status is ItemStatus.NOT_APPLICABLE

    def test_default_off_but_relevant_is_recommended(self, tmp_path: Path) -> None:
        """Decision 2: a default-off handler is conditional, not inferior."""
        ccy = tmp_path / ".claude" / "ccy"
        ccy.mkdir(parents=True)
        (ccy / "ccy.env").write_text(
            'export CCY_CLAUDE_WRAPPER="$PWD/.claude/ccy/claude-supervise.py"\n'
        )
        config = _config(post_tool_use={"goal_injection": {"enabled": False}})
        item = _by_path(build_checklist(config, _context(tmp_path)))[
            "handlers.post_tool_use.goal_injection"
        ]
        assert item.default_enabled is False
        assert item.status is ItemStatus.SHORTFALL

    def test_disable_tags_disable_the_handler(self, tmp_path: Path) -> None:
        config = _config(pre_tool_use={"disable_tags": ["safety"]})
        item = _by_path(build_checklist(config, _context(tmp_path)))[
            "handlers.pre_tool_use.destructive_git"
        ]
        assert item.enabled is False

    def test_nitpick_handler_follows_both_gates(self, tmp_path: Path) -> None:
        items = _by_path(build_checklist(_config(), _context(tmp_path)))
        assert items["pseudo_events.nitpick.handlers.hedging_language"].enabled is True
        # Absent from the handlers block: the pseudo-event registry treats an
        # unlisted handler as enabled, so the checklist must agree.
        assert items["pseudo_events.nitpick.handlers.dismissive_language"].enabled is True

        config = _config()
        config["pseudo_events"]["nitpick"]["enabled"] = False
        items = _by_path(build_checklist(config, _context(tmp_path)))
        assert items["pseudo_events.nitpick.handlers.hedging_language"].enabled is False

    def test_missing_pseudo_event_section_means_disabled(self, tmp_path: Path) -> None:
        items = _by_path(build_checklist({"handlers": {}}, _context(tmp_path)))
        assert items["pseudo_events.nitpick.handlers.hedging_language"].enabled is False
        assert items["pseudo_events.nitpick.handlers.hedging_language"].area is (
            Area.AGENT_BEHAVIOUR
        )


class TestRender:
    def test_fully_enabled_area_collapses_to_a_count(self, tmp_path: Path) -> None:
        report = render_report(build_checklist(_config(), _context(tmp_path)))
        assert "Safety" in report
        assert "destructive_git" not in report, "an optimal handler must not be listed"
        assert "PASS" in report

    def test_shortfalls_and_not_applicable_are_listed(self, tmp_path: Path) -> None:
        config = _config(
            pre_tool_use={"destructive_git": {"enabled": False}},
            post_tool_use={"goal_injection": {"enabled": False}},
        )
        report = render_report(build_checklist(config, _context(tmp_path)))
        assert "handlers.pre_tool_use.destructive_git" in report
        assert "handlers.post_tool_use.goal_injection" in report
        assert "not applicable" in report
        assert "Recommendations" in report
        assert "[1]" in report

    def test_totals_are_computed(self, tmp_path: Path) -> None:
        items = build_checklist(_config(), _context(tmp_path))
        relevant = [item for item in items if item.relevance.applicable]
        enabled = [item for item in relevant if item.enabled]
        report = render_report(items)
        assert f"{len(enabled)}/{len(relevant)}" in report

    def test_no_shortfall_says_so(self, tmp_path: Path) -> None:
        items = build_checklist(_config(), _context(tmp_path))
        shortfalls = [item for item in items if item.status is ItemStatus.SHORTFALL]
        report = render_report(items)
        if shortfalls:
            assert "Recommendations" in report
        else:
            assert "No recommendations" in report

    def test_json_is_serialisable_and_complete(self, tmp_path: Path) -> None:
        items = build_checklist(_config(), _context(tmp_path))
        data = report_as_json(items)
        json.dumps(data)
        assert len(data["items"]) == len(items)
        assert set(data["items"][0]) >= {
            "config_path",
            "area",
            "enabled",
            "default_enabled",
            "applicable",
            "reason",
            "status",
            "summary",
        }
        assert data["summary"]["relevant"] == sum(1 for i in items if i.relevance.applicable)
