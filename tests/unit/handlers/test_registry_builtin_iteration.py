"""``iter_builtin_handler_classes`` enumerates exactly what ``register_all`` would.

Plan 00330. The config-optimisation checklist is derived from this iterator,
so it must see every handler class the registry would register, keyed by the
same event directory and config key ``register_all`` uses — otherwise the
checklist could score a handler under a name no config can address.
"""

from __future__ import annotations

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.handlers.registry import (
    EVENT_TYPE_MAPPING,
    BuiltinHandlerRef,
    HandlerRegistry,
    iter_builtin_handler_classes,
)
from claude_code_hooks_daemon.pseudo_events.registry import pseudo_event_handler_classes


def _refs() -> list[BuiltinHandlerRef]:
    return list(iter_builtin_handler_classes())


def test_yields_every_discovered_handler_once() -> None:
    """Every class ``discover()`` finds, minus the pseudo-event handlers.

    ``discover()`` walks the whole package, including ``handlers/nitpick/``,
    which is a pseudo-event with no ``EVENT_TYPE_MAPPING`` entry and its own
    registry (``pseudo_events.registry``); ``register_all`` never registers
    those, so neither does this iterator.
    """
    registry = HandlerRegistry()
    registry.discover()
    pseudo = {
        cls.__name__
        for entries in pseudo_event_handler_classes().values()
        for cls in entries.values()
    }
    discovered = set(registry.list_handlers()) - pseudo
    yielded = [ref.handler_cls.__name__ for ref in _refs()]
    assert sorted(yielded) == sorted(discovered)
    assert len(yielded) == len(set(yielded))


def test_event_dir_is_a_known_event_directory() -> None:
    for ref in _refs():
        assert ref.event_dir in EVENT_TYPE_MAPPING
        assert issubclass(ref.handler_cls, Handler)


def test_config_key_matches_handler_id_constant() -> None:
    live = {getattr(HandlerID, attr).config_key for attr in dir(HandlerID) if attr.isupper()}
    unknown = sorted(ref.config_key for ref in _refs() if ref.config_key not in live)
    assert not unknown, f"config keys with no HandlerID constant: {unknown}"


def test_config_paths_are_unique() -> None:
    paths = [f"{ref.event_dir}.{ref.config_key}" for ref in _refs()]
    assert len(paths) == len(set(paths))
