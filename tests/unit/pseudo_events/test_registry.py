"""Tests for the shared pseudo-event handler registry (Plan 00237).

The registry exists so every handler-enumeration surface reads the same list.
These tests cover the mapping and the config filtering directly; the
integration suite (`tests/integration/test_pseudo_event_handler_visibility.py`)
covers the outcome that actually matters — a pseudo-event handler appearing in
the generated artefacts.

The mapping is keyed by the key used under `pseudo_events.<name>.handlers` in
`hooks-daemon.yaml`, which is NOT the handler's `HandlerID.config_key`
(`dismissive_language` vs `dismissive_language_nitpick`). Two spellings for one
handler already existed; the registry picks the one the config file uses,
because that is the one a filter has to match.
"""

from __future__ import annotations

from typing import Any

from claude_code_hooks_daemon.pseudo_events.registry import (
    NITPICK,
    enabled_pseudo_event_handler_classes,
    pseudo_event_handler_classes,
)

_DISMISSIVE_KEY = "dismissive_language"
_HEDGING_KEY = "hedging_language"
_DISMISSIVE_CLASS = "DismissiveLanguageNitpickHandler"
_HEDGING_CLASS = "HedgingLanguageNitpickHandler"


def _config(
    *,
    enabled: bool = True,
    dismissive: bool = True,
    hedging: bool = True,
) -> dict[str, Any]:
    return {
        NITPICK: {
            "enabled": enabled,
            "triggers": ["pre_tool_use:1/5"],
            "handlers": {
                _DISMISSIVE_KEY: {"enabled": dismissive},
                _HEDGING_KEY: {"enabled": hedging},
            },
        }
    }


class TestPseudoEventHandlerClasses:
    """The unfiltered mapping."""

    def test_nitpick_is_registered(self) -> None:
        assert NITPICK in pseudo_event_handler_classes()

    def test_keyed_by_the_config_file_spelling(self) -> None:
        """Not HandlerID.config_key — a filter must match what the yaml says."""
        assert set(pseudo_event_handler_classes()[NITPICK]) == {
            _DISMISSIVE_KEY,
            _HEDGING_KEY,
        }

    def test_maps_to_the_shipped_handler_classes(self) -> None:
        entries = pseudo_event_handler_classes()[NITPICK]
        assert entries[_DISMISSIVE_KEY].__name__ == _DISMISSIVE_CLASS
        assert entries[_HEDGING_KEY].__name__ == _HEDGING_CLASS

    def test_returns_classes_not_instances(self) -> None:
        """Callers differ in what they need; construction is theirs to choose."""
        for cls in pseudo_event_handler_classes()[NITPICK].values():
            assert isinstance(cls, type)


class TestEnabledFiltering:
    """Both gates, applied where every surface can see them."""

    def test_all_enabled_returns_both(self) -> None:
        result = enabled_pseudo_event_handler_classes(_config())
        assert set(result[NITPICK]) == {_DISMISSIVE_KEY, _HEDGING_KEY}

    def test_disabled_pseudo_event_yields_nothing(self) -> None:
        assert enabled_pseudo_event_handler_classes(_config(enabled=False)) == {}

    def test_a_disabled_handler_is_dropped(self) -> None:
        result = enabled_pseudo_event_handler_classes(_config(hedging=False))
        assert set(result[NITPICK]) == {_DISMISSIVE_KEY}

    def test_all_handlers_disabled_omits_the_name_entirely(self) -> None:
        """So a caller can treat an empty result as 'nothing to render'."""
        result = enabled_pseudo_event_handler_classes(_config(dismissive=False, hedging=False))
        assert result == {}

    def test_none_config_yields_nothing(self) -> None:
        assert enabled_pseudo_event_handler_classes(None) == {}

    def test_empty_config_yields_nothing(self) -> None:
        """An unconfigured pseudo-event is never registered, unlike handlers:."""
        assert enabled_pseudo_event_handler_classes({}) == {}

    def test_enabled_defaults_to_true_when_absent(self) -> None:
        """Matches PseudoEventConfig's own default."""
        config: dict[str, Any] = {NITPICK: {"triggers": ["stop:1/1"], "handlers": {}}}
        result = enabled_pseudo_event_handler_classes(config)
        assert set(result[NITPICK]) == {_DISMISSIVE_KEY, _HEDGING_KEY}


class TestMalformedConfigIsToleratedNotFatal:
    """These generators run against whatever is on disk.

    A report that crashes on a malformed config block is worse than one that
    over-reports: the crash takes the whole document with it. Unreadable
    entries fall back to the daemon's own default of enabled.
    """

    def test_handlers_block_of_the_wrong_type(self) -> None:
        config: dict[str, Any] = {NITPICK: {"enabled": True, "handlers": "not-a-dict"}}
        result = enabled_pseudo_event_handler_classes(config)
        assert set(result[NITPICK]) == {_DISMISSIVE_KEY, _HEDGING_KEY}

    def test_handler_entry_of_the_wrong_type(self) -> None:
        config: dict[str, Any] = {NITPICK: {"enabled": True, "handlers": {_DISMISSIVE_KEY: True}}}
        result = enabled_pseudo_event_handler_classes(config)
        assert set(result[NITPICK]) == {_DISMISSIVE_KEY, _HEDGING_KEY}

    def test_pseudo_event_block_of_the_wrong_type(self) -> None:
        config: dict[str, Any] = {NITPICK: "enabled"}
        assert enabled_pseudo_event_handler_classes(config) == {}

    def test_an_unknown_pseudo_event_name_is_ignored(self) -> None:
        config: dict[str, Any] = {"not-a-real-pseudo-event": {"enabled": True}}
        assert enabled_pseudo_event_handler_classes(config) == {}
