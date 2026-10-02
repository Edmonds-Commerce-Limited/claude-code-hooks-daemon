"""An ABSENT handler block defers to the handler's declared default (Plan 00483 N55).

`Handler.default_enabled` is the pre-construction answer to "is this handler
opt-in?". `config_skip_reason` and `handler_is_enabled` consult it only when the
handler has NO block under `handlers.<event>`; a PRESENT block (a mapping or a
bare ``key:``) is enabled unless it says ``enabled: false``.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.handlers.registry import (
    HandlerRegistry,
    _get_config_key,
    config_skip_reason,
    handler_is_enabled,
)

_OFF_BY_DEFAULT = "off by default and not configured"

_OPT_IN_CLASS = "LspEnforcementHandler"
_OPT_IN_KEY = "lsp_enforcement"
_OPT_OUT_CLASS = "DestructiveGitHandler"
_OPT_OUT_KEY = "destructive_git"


def _registered_class_names(config: dict[str, Any] | None) -> set[str]:
    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()
    registry.register_all(router, config=config)
    chain = router.get_chain(EventType.PRE_TOOL_USE)
    return {type(h).__name__ for h in chain.handlers}


class TestConfigSkipReason:
    """The pre-construction predicate."""

    def test_absent_block_of_an_opt_in_handler_is_skipped(self) -> None:
        assert (
            config_skip_reason(None, registry_disabled=False, default_enabled=False, present=False)
            == _OFF_BY_DEFAULT
        )

    def test_absent_block_of_an_opt_out_handler_is_kept(self) -> None:
        assert (
            config_skip_reason(None, registry_disabled=False, default_enabled=True, present=False)
            is None
        )

    def test_bare_key_of_an_opt_in_handler_is_enabled(self) -> None:
        assert (
            config_skip_reason(None, registry_disabled=False, default_enabled=False, present=True)
            is None
        )

    def test_mapping_without_enabled_of_an_opt_in_handler_is_enabled(self) -> None:
        assert (
            config_skip_reason(
                {"priority": 5}, registry_disabled=False, default_enabled=False, present=True
            )
            is None
        )

    def test_explicit_enabled_true_of_an_opt_in_handler_is_enabled(self) -> None:
        assert (
            config_skip_reason(
                {"enabled": True}, registry_disabled=False, default_enabled=False, present=True
            )
            is None
        )

    def test_explicit_enabled_false_wins_over_an_opt_out_default(self) -> None:
        assert (
            config_skip_reason(
                {"enabled": False}, registry_disabled=False, default_enabled=True, present=True
            )
            == "disabled by config"
        )

    def test_registry_disabled_still_skips_a_present_block(self) -> None:
        assert (
            config_skip_reason(
                {"enabled": True}, registry_disabled=True, default_enabled=False, present=True
            )
            == "disabled in the registry"
        )

    def test_defaults_keep_the_old_contract(self) -> None:
        """No new arguments: an absent block with no default given is enabled."""
        assert config_skip_reason(None, registry_disabled=False) is None


class TestHandlerIsEnabled:
    """`would_register`: the checklist's predicate."""

    def test_opt_in_handler_with_no_block_is_not_enabled(self) -> None:
        assert handler_is_enabled({}, "k", [], default_enabled=False) is False

    def test_opt_in_handler_with_bare_key_is_enabled(self) -> None:
        assert handler_is_enabled({"k": None}, "k", [], default_enabled=False) is True

    def test_opt_in_handler_with_enabled_true_is_enabled(self) -> None:
        assert handler_is_enabled({"k": {"enabled": True}}, "k", [], default_enabled=False) is True

    def test_opt_out_handler_with_no_block_is_enabled(self) -> None:
        assert handler_is_enabled({}, "k", [], default_enabled=True) is True

    def test_none_event_config_is_an_absent_block(self) -> None:
        assert handler_is_enabled(None, "k", [], default_enabled=False) is False
        assert handler_is_enabled(None, "k", [], default_enabled=True) is True


class TestRegisterAllHonoursTheDeclaredDefault:
    """`register_all` and `handler_is_enabled` must give the same answer."""

    def test_opt_in_handler_with_no_block_is_not_registered(self) -> None:
        assert _OPT_IN_CLASS not in _registered_class_names({"pre_tool_use": {}})

    def test_opt_in_handler_with_no_config_at_all_is_not_registered(self) -> None:
        assert _OPT_IN_CLASS not in _registered_class_names(None)

    def test_opt_in_handler_with_bare_key_is_registered(self) -> None:
        names = _registered_class_names({"pre_tool_use": {_OPT_IN_KEY: None}})
        assert _OPT_IN_CLASS in names

    def test_opt_in_handler_with_enabled_true_is_registered(self) -> None:
        names = _registered_class_names({"pre_tool_use": {_OPT_IN_KEY: {"enabled": True}}})
        assert _OPT_IN_CLASS in names

    def test_opt_in_handler_with_enabled_false_is_not_registered(self) -> None:
        names = _registered_class_names({"pre_tool_use": {_OPT_IN_KEY: {"enabled": False}}})
        assert _OPT_IN_CLASS not in names

    def test_opt_out_handler_with_no_block_is_still_registered(self) -> None:
        assert _OPT_OUT_CLASS in _registered_class_names({"pre_tool_use": {}})

    def test_opt_out_handler_with_enabled_false_is_not_registered(self) -> None:
        names = _registered_class_names({"pre_tool_use": {_OPT_OUT_KEY: {"enabled": False}}})
        assert _OPT_OUT_CLASS not in names

    @pytest.mark.parametrize(
        ("block", "class_name", "config_key"),
        [
            (None, _OPT_IN_CLASS, _OPT_IN_KEY),
            ("absent", _OPT_IN_CLASS, _OPT_IN_KEY),
            ({"enabled": True}, _OPT_IN_CLASS, _OPT_IN_KEY),
            ("absent", _OPT_OUT_CLASS, _OPT_OUT_KEY),
            ({"enabled": False}, _OPT_OUT_CLASS, _OPT_OUT_KEY),
        ],
    )
    def test_would_register_agrees_with_register_all(
        self, block: Any, class_name: str, config_key: str
    ) -> None:
        event_config: dict[str, Any] = {} if block == "absent" else {config_key: block}
        registry = HandlerRegistry()
        registry.discover()
        cls = registry.get_handler_class(class_name)
        assert cls is not None
        assert _get_config_key(class_name) == config_key
        predicted = handler_is_enabled(
            event_config, config_key, cls().tags, default_enabled=cls().get_default_enabled()
        )
        actual = class_name in _registered_class_names({"pre_tool_use": event_config})
        assert predicted is actual


class TestDeclaredDefaultDrift:
    """The class attribute and the method are one fact."""

    @staticmethod
    def _handler_classes() -> list[type[Handler]]:
        registry = HandlerRegistry()
        registry.discover()
        classes = [registry.get_handler_class(n) for n in registry.list_handlers()]
        return [c for c in classes if c is not None]

    def test_base_default_is_opt_out(self) -> None:
        assert Handler.default_enabled is True

    def test_attribute_set_equals_method_set(self) -> None:
        by_attribute = {c.__name__ for c in self._handler_classes() if c.default_enabled is False}
        by_method = {
            c.__name__
            for c in self._handler_classes()
            if c.get_default_enabled(c.__new__(c)) is False
        }
        assert by_attribute == by_method
        assert by_attribute, "no opt-in handler found; the drift check would be vacuous"
