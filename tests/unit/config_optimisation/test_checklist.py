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
from collections.abc import Iterator
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
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.relevance import RelevanceContext
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.handlers.registry import (
    BuiltinHandlerRef,
    HandlerRegistry,
    iter_builtin_handler_classes,
)
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


def _registered_class_names(handlers_config: dict[str, Any]) -> set[str]:
    """The handler classes ``register_all`` actually puts on the router."""
    router = EventRouter()
    HandlerRegistry().register_all(router, config=handlers_config)
    names: set[str] = set()
    for event_type in EventType:
        names.update(type(handler).__name__ for handler in router.get_chain(event_type).handlers)
    return names


class TestTheRegistrysGatesAreTheOnlyGates:
    """The checklist must not re-implement ``register_all``'s enablement rule.

    A second copy does not fail when it drifts — the report simply starts
    disagreeing with the daemon about which handlers are on, silently. The
    cross-check below is the pin: for one config, every built-in handler's
    ``enabled`` must match whether registration actually registered it.
    """

    def test_the_checklist_agrees_with_the_registry_for_every_builtin(self, tmp_path: Path) -> None:
        config = _config(
            pre_tool_use={"destructive_git": {"enabled": False}, "disable_tags": ["planning"]},
            post_tool_use={"lint_on_edit": {"enabled": False}},
        )
        registered = _registered_class_names(config["handlers"])
        items = _by_path(build_checklist(config, _context(tmp_path)))
        for ref in iter_builtin_handler_classes():
            item = items[f"handlers.{ref.event_dir}.{ref.config_key}"]
            assert item.enabled is (ref.handler_cls.__name__ in registered), ref.config_key

    def test_a_scalar_enable_tags_gates_exactly_as_the_registry_does(self, tmp_path: Path) -> None:
        """YAML ``enable_tags: safety`` is a STRING, not a list.

        The registry treats ANY truthy value as tags, so a scalar matches
        nothing and the whole event goes dark. A checklist that required a
        ``list`` read the same config as "no tag filter" and reported the
        opposite.
        """
        config = _config(pre_tool_use={"enable_tags": "safety"})
        registered = _registered_class_names(config["handlers"])
        item = _by_path(build_checklist(config, _context(tmp_path)))[
            "handlers.pre_tool_use.destructive_git"
        ]
        assert "DestructiveGitHandler" not in registered
        assert item.enabled is False

    def test_a_list_enable_tags_still_selects_by_tag(self, tmp_path: Path) -> None:
        config = _config(pre_tool_use={"enable_tags": ["safety"]})
        items = _by_path(build_checklist(config, _context(tmp_path)))
        assert items["handlers.pre_tool_use.destructive_git"].enabled is True
        assert items["handlers.pre_tool_use.plan_number_helper"].enabled is False

    def test_a_registry_disabled_handler_reads_as_disabled(self, tmp_path: Path) -> None:
        """The fourth gate: runtime state, not config, and previously unmirrored."""
        items = _by_path(
            build_checklist(
                _config(),
                _context(tmp_path),
                disabled_handlers=frozenset({"DestructiveGitHandler"}),
            )
        )
        assert items["handlers.pre_tool_use.destructive_git"].enabled is False
        assert items["handlers.pre_tool_use.sed_blocker"].enabled is True

    def test_no_disabled_set_leaves_the_fourth_gate_open(self, tmp_path: Path) -> None:
        items = _by_path(build_checklist(_config(), _context(tmp_path)))
        assert items["handlers.pre_tool_use.destructive_git"].enabled is True


class _ExplodingHandler(Handler):
    """A handler that cannot be constructed."""

    def __init__(self) -> None:
        raise RuntimeError("boom at construction")

    def matches(self, hook_input: dict[str, Any]) -> bool:
        raise NotImplementedError

    def handle(self, hook_input: dict[str, Any]) -> Any:
        raise NotImplementedError

    def get_claude_md(self) -> str | None:
        raise NotImplementedError

    def get_acceptance_tests(self) -> list[Any]:
        raise NotImplementedError


class TestAConstructorFailureIsReportedNotFatal:
    """One handler that cannot be built must not cost the other 113 verdicts.

    ``register_all`` already wraps its own instantiation. A report is the
    LOWER-stakes context of the two, which argues for more tolerance here,
    not less — and a handler that cannot be constructed is exactly the thing
    a review should surface, so it appears as visibly unassessed rather than
    silently absent.
    """

    @pytest.fixture
    def with_an_exploder(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real = iter_builtin_handler_classes

        def including_the_exploder() -> Iterator[BuiltinHandlerRef]:
            yield from real()
            yield BuiltinHandlerRef(
                event_dir="pre_tool_use",
                config_key="exploding",
                handler_cls=_ExplodingHandler,
            )

        monkeypatch.setattr(
            "claude_code_hooks_daemon.config_optimisation.checklist.iter_builtin_handler_classes",
            including_the_exploder,
        )

    def test_the_report_is_still_built(self, tmp_path: Path, with_an_exploder: None) -> None:
        items = build_checklist(_config(), _context(tmp_path))
        assert (
            len(items)
            == len(list(iter_builtin_handler_classes()))
            + sum(len(entries) for entries in pseudo_event_handler_classes().values())
            + 1
        )

    def test_the_failed_handler_is_visible_with_its_error(
        self, tmp_path: Path, with_an_exploder: None
    ) -> None:
        item = _by_path(build_checklist(_config(), _context(tmp_path)))[
            "handlers.pre_tool_use.exploding"
        ]
        assert item.status is ItemStatus.UNASSESSED
        assert "boom at construction" in item.construction_error

    def test_an_unassessed_handler_is_neither_a_shortfall_nor_a_pass(
        self, tmp_path: Path, with_an_exploder: None
    ) -> None:
        items = build_checklist(_config(), _context(tmp_path))
        data = report_as_json(items)
        assert data["summary"]["unassessed"] == 1
        assert data["summary"]["relevant"] + data["summary"]["not_applicable"] + 1 == len(items)

    def test_the_render_names_it(self, tmp_path: Path, with_an_exploder: None) -> None:
        report = render_report(build_checklist(_config(), _context(tmp_path)))
        assert "handlers.pre_tool_use.exploding" in report
        assert "boom at construction" in report


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
