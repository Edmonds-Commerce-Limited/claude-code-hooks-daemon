"""A config option can only set a declared option attribute (ledger 00466 N50).

``apply_handler_options`` sets ``self._<key>``. A stale or renamed option whose
``_<key>`` is a method (``_human_docs_dir``, ``_pauses_path``) used to replace
that method with the option's value, so the next call crashed. Such an option
is now refused, reported on ``option_failures`` like any other invalid option,
and never applied.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.handlers.pre_tool_use.markdown_organization import (
    MarkdownOrganizationHandler,
)
from claude_code_hooks_daemon.handlers.registry import (
    HandlerRegistry,
    apply_handler_options,
    unsettable_option_reasons,
)
from claude_code_hooks_daemon.handlers.stop.cron_stop_enforcer import CronStopEnforcerHandler

_MD_KEY = "PreToolUse.markdown_organization"
_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def _project_context() -> Iterator[None]:
    """Some handlers need a live project context to construct; the daemon has one."""
    ProjectContext.initialize(_REPO_ROOT / ".claude" / "hooks-daemon.yaml")
    yield
    ProjectContext.reset()


class _Sample:
    """A handler-shaped object with one data attribute, one method, one property."""

    def __init__(self) -> None:
        self._limit = 3

    def _helper(self) -> str:
        return "helper"

    @property
    def _computed(self) -> str:
        return "computed"

    @property
    def _validated(self) -> int:
        return self._stored

    @_validated.setter
    def _validated(self, value: int) -> None:
        self._stored = value


def test_a_data_option_is_still_applied() -> None:
    sample = _Sample()
    apply_handler_options(sample, {"limit": 9})
    assert sample._limit == 9


def test_an_option_naming_a_method_does_not_replace_it() -> None:
    sample = _Sample()
    apply_handler_options(sample, {"helper": "boom"})
    assert sample._helper() == "helper"


def test_an_option_naming_a_read_only_property_is_not_applied() -> None:
    sample = _Sample()
    apply_handler_options(sample, {"computed": "boom"})
    assert sample._computed == "computed"


def test_an_option_naming_a_settable_property_is_applied() -> None:
    sample = _Sample()
    apply_handler_options(sample, {"validated": 5})
    assert sample._validated == 5


def test_an_underscore_prefixed_option_is_not_applied() -> None:
    sample = _Sample()
    apply_handler_options(sample, {"_limit": 99, "_helper": 1})
    assert sample._limit == 3
    assert sample._helper() == "helper"


def test_reasons_name_every_refused_key_and_none_of_the_valid_ones() -> None:
    reasons = unsettable_option_reasons(_Sample, {"limit": 1, "helper": 2, "_x": 3})
    assert set(reasons) == {"helper", "_x"}


@pytest.mark.parametrize(
    ("handler_cls", "option"),
    [
        (MarkdownOrganizationHandler, "human_docs_dir"),
        (CronStopEnforcerHandler, "pauses_path"),
    ],
)
def test_the_shipped_handlers_methods_are_protected(
    handler_cls: type, option: str, _project_context: None
) -> None:
    handler = handler_cls()
    apply_handler_options(handler, {option: "stale-value"})
    assert callable(getattr(handler, f"_{option}"))


def test_register_all_reports_the_refused_option_and_the_handler_still_works(
    _project_context: None,
) -> None:
    config: dict[str, Any] = {
        "pre_tool_use": {
            "markdown_organization": {"enabled": True, "options": {"human_docs_dir": "docs"}}
        }
    }
    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()
    registry.register_all(router, config=config)

    assert "human_docs_dir" in registry.option_failures[_MD_KEY]
    handlers = [
        h
        for h in router.get_chain(EventType.PRE_TOOL_USE).handlers
        if isinstance(h, MarkdownOrganizationHandler)
    ]
    assert handlers
    assert callable(handlers[0]._human_docs_dir)
