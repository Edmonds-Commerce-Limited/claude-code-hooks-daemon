"""Every handler that DRIVES work is gated on autonomy, and nothing else is (Plan 00498).

The inventory in the plan's subagent-reports names the work-driving handlers. This
file is its executable form: the set of handlers that declare `drives_autonomy`
must be exactly that set, so a new handler cannot start driving work unnoticed and
a guard cannot be gated by accident. Each driver is then put through the real
`HandlerChain` on a desktop session (it is never consulted) and in a container (it
is, unchanged).
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Any

import pytest
from tests.support.autonomy import pin_container_containers_only, pin_desktop_containers_only

import claude_code_hooks_daemon.handlers as handlers_package
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.core.handler import Handler

#: The work-driving handlers, by class name. The inventory file lists each with a reason.
EXPECTED_DRIVERS = frozenset(
    {
        "CronStopEnforcerHandler",
        "CronSubagentStopEnforcerHandler",
        "FailsafeCronSessionAdvisorHandler",
        "GoalInjectionHandler",
        "IdleHousekeepingAdvisoryHandler",
        "PersistentCronAssertorHandler",
        "RecoveryCronAdvisorHandler",
        "RoutineQaSweepHandler",
        "SessionActionsDirectiveHandler",
    }
)


def _all_handler_classes() -> dict[str, type[Handler]]:
    found: dict[str, type[Handler]] = {}
    for module_info in pkgutil.walk_packages(
        handlers_package.__path__, prefix=f"{handlers_package.__name__}."
    ):
        module = importlib.import_module(module_info.name)
        for name, cls in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(cls, Handler)
                and not inspect.isabstract(cls)
                and cls.__module__ == (module.__name__)
            ):
                found[name] = cls
    return found


_CLASSES = _all_handler_classes()


def test_the_declared_drivers_are_exactly_the_inventory() -> None:
    declared = {name for name, cls in _CLASSES.items() if cls.drives_autonomy}
    assert declared == EXPECTED_DRIVERS


@pytest.mark.parametrize("name", sorted(EXPECTED_DRIVERS))
def test_a_driver_is_not_consulted_on_a_desktop(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    pin_desktop_containers_only(monkeypatch)
    assert _times_consulted(name, monkeypatch) == 0


@pytest.mark.parametrize("name", sorted(EXPECTED_DRIVERS))
def test_a_driver_is_consulted_unchanged_in_a_container(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    pin_container_containers_only(monkeypatch)
    assert _times_consulted(name, monkeypatch) == 1


def _times_consulted(name: str, monkeypatch: pytest.MonkeyPatch) -> int:
    """How many times the real chain asked the real handler ``name`` whether it matches."""
    handler = _CLASSES[name]()
    asked: list[dict[str, Any]] = []

    def record(hook_input: dict[str, Any]) -> bool:
        asked.append(hook_input)
        return False

    monkeypatch.setattr(handler, "matches", record)
    chain = HandlerChain()
    chain.add(handler)
    chain.execute({"hook_event_name": "Any", "session_id": "s1"})
    return len(asked)
