"""The shipped config template must ship the priorities the constants declare.

Ledger 00422 N1 (inherited from 00419 N8). ``constants/priority.py`` is where a
handler's priority is decided and explained, and every handler class takes its
default from it. ``ConfigTemplate.generate_full`` is what a fresh ``init``
writes, and it states a priority for every handler it lists. A value there
OVERRIDES the constant for every project that took the default config, so a
constant the template disagrees with is a constant that governs nothing.

They disagreed for months without any check noticing, because nothing compared
them. The visible cost was the status line: the template shifted
``git_repo_name`` from 3 to 5, and ``environment_indicator`` — which the
template does not list, so it runs at its constant of 4 — rendered before the
repository name on every fresh install, against the constant's own comment
("After repo name, before account display").

This is the whole-template comparison, with no allow-list. A divergence is
fixed on whichever side is wrong, never exempted here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
import yaml

from claude_code_hooks_daemon.constants.config import ConfigKey
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.init_config import ConfigTemplate
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry, _get_config_key

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: ``claude_code_hooks_daemon.handlers.<event>.<module>`` — the event directory
#: is the third dotted part, and it is the same name the template keys on.
_EVENT_PART: Final[int] = 2

#: A realistic floor: a parser that matched nothing would pass every check.
_MIN_TEMPLATE_ENTRIES: Final[int] = 100

_HandlerKey = tuple[str, str]


@pytest.fixture(autouse=True)
def _project_context() -> None:
    """Real config, so every handler can be constructed to read its default."""
    if not ProjectContext.is_initialized():
        ProjectContext.initialize(_REPO_ROOT / ".claude" / "hooks-daemon.yaml")


def _template_priorities() -> dict[_HandlerKey, int]:
    """(event, config_key) -> the priority the full template ships."""
    parsed = yaml.safe_load(ConfigTemplate.generate_full())
    shipped: dict[_HandlerKey, int] = {}
    for event, handlers in (parsed.get("handlers") or {}).items():
        if not isinstance(handlers, dict):
            continue
        for name, cfg in handlers.items():
            if isinstance(cfg, dict) and isinstance(cfg.get(ConfigKey.PRIORITY), int):
                shipped[(event, name)] = cfg[ConfigKey.PRIORITY]
    return shipped


def _handler_classes() -> dict[_HandlerKey, list[type]]:
    """(event, config_key) -> every discovered handler class at that key."""
    registry = HandlerRegistry()
    registry.discover()
    classes: dict[_HandlerKey, list[type]] = {}
    for class_name in registry.list_handlers():
        cls = registry.get_handler_class(class_name)
        if cls is None:
            continue
        event = cls.__module__.split(".")[_EVENT_PART]
        classes.setdefault((event, _get_config_key(class_name)), []).append(cls)
    return classes


class TestTheComparisonReadsBothSides:
    """Controls: an empty or unresolvable side would read as agreement."""

    def test_the_template_parse_finds_a_realistic_number_of_priorities(self) -> None:
        assert len(_template_priorities()) > _MIN_TEMPLATE_ENTRIES

    def test_every_template_entry_resolves_to_exactly_one_handler_class(self) -> None:
        classes = _handler_classes()
        unresolved = sorted(
            f"{event}.{name}: {len(classes.get((event, name), []))} classes"
            for event, name in _template_priorities()
            if len(classes.get((event, name), [])) != 1
        )
        assert not unresolved, (
            "template entries that do not name exactly one handler class — the "
            f"priority comparison cannot judge them: {unresolved}"
        )


class TestTheTemplateShipsTheConstants:
    def test_every_template_priority_equals_the_handler_default(self) -> None:
        classes = _handler_classes()
        divergent = sorted(
            f"{event}.{name}: template ships {shipped}, "
            f"the constant says {classes[(event, name)][0]().priority}"
            for (event, name), shipped in _template_priorities().items()
            if len(classes.get((event, name), [])) == 1
            and classes[(event, name)][0]().priority != shipped
        )
        assert not divergent, (
            "the config template overrides these handlers' Priority constants for "
            "every project that took the default config. Fix whichever side is "
            f"wrong; do not allow-list: {divergent}"
        )
