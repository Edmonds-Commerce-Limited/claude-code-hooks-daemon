"""A handler imported into another handler's module is not registered twice.

``owner_wait_stop_guard`` imports ``AutoContinueStopHandler`` to reuse its
static helpers. Discovery scans every attribute of each handler module, so the
imported class was found in BOTH modules and ``auto-continue-stop`` ended up on
the Stop chain twice. A class belongs to the module that defines it.
"""

from __future__ import annotations

from collections import Counter
from types import ModuleType

from claude_code_hooks_daemon.core import Handler
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.handlers.registry import (
    HandlerRegistry,
    is_discoverable_handler,
    iter_builtin_handler_classes,
)
from claude_code_hooks_daemon.handlers.stop import owner_wait_stop_guard
from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import AutoContinueStopHandler


def test_imported_handler_class_is_not_discoverable_from_the_importing_module() -> None:
    module: ModuleType = owner_wait_stop_guard
    assert module.AutoContinueStopHandler is AutoContinueStopHandler
    assert is_discoverable_handler(AutoContinueStopHandler)
    assert not is_discoverable_handler(AutoContinueStopHandler, defined_in=module.__name__)


def test_every_builtin_handler_class_is_enumerated_once() -> None:
    counts = Counter(ref.handler_cls for ref in iter_builtin_handler_classes())
    duplicated = sorted(cls.__name__ for cls, n in counts.items() if n > 1)
    assert duplicated == []


def test_stop_chain_holds_auto_continue_stop_once() -> None:
    router = EventRouter()
    HandlerRegistry().register_all(router)
    handlers: list[Handler] = list(router.get_chain(EventType.STOP).handlers)
    names = [h.name for h in handlers if h.name == "auto-continue-stop"]
    assert names == ["auto-continue-stop"]
