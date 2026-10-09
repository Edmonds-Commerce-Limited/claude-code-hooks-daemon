"""Every deny a handler returns in a test carries a declared ``BLOCKED [R-...]`` ID.

TOOLING-SPEC 5.3 / DETECTOR-SPEC 4.3 (Plan 00484 G5): a denial a reader cannot
look up with ``hooks-daemon explain-rule`` is a denial that teaches nothing. The
parity test checks that a denying handler declares rules; it cannot see whether
a particular deny REASON prints one, nor whether the printed ID is one the
handler declares (a reason built outside the handler module, or in an
off-format ``R-X: ...`` shape, passes it).

This plugin wraps ``handle`` on every library and project handler class once
collection has imported them, so every deny a test provokes is judged wherever
its reason was built. A deny whose reason lacks the headline, or names an ID
the handler's ``get_rules()`` does not declare, fails the test that provoked it
at teardown. A handler in the shared allowlist
(``tests/support/deny_allowlist.py``) is exempt only while it declares no rule.

Loaded from ``tests/conftest.py`` (``pytest_plugins``) and from the
project-handler conftest (``register``).
"""

from __future__ import annotations

import functools
import importlib
import inspect
import os
import pkgutil
import re
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any, Final

import pytest

from claude_code_hooks_daemon import handlers as handlers_package
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision
from tests.support.deny_allowlist import (
    _DENY_WITHOUT_RULES_ALLOWLIST,
    _PROJECT_DENY_WITHOUT_RULES_ALLOWLIST,
)

__all__ = ["PLUGIN_NAME", "register"]

PLUGIN_NAME: Final[str] = "tests.plugins.deny_carries_rule_id"

_HEADLINE: Final[re.Pattern[str]] = re.compile(r"BLOCKED \[(R-[A-Z0-9-]+)\]")
_PROJECT_HANDLERS_DIR: Final[Path] = (
    Path(__file__).resolve().parents[2] / ".claude" / "project-handlers"
)
_WRAPPED_MARK: Final[str] = "_deny_carries_rule_id_wrapped"
_ALLOWLISTED: Final[frozenset[str]] = frozenset(
    {*_DENY_WITHOUT_RULES_ALLOWLIST, *_PROJECT_DENY_WITHOUT_RULES_ALLOWLIST}
)

#: Violations recorded since the running test began; drained at its teardown.
_violations: list[str] = []
#: Each wrapped class with the ``handle`` it had, to restore at unconfigure.
_wrapped: list[tuple[type[Handler], Callable[..., Any]]] = []


def _in_scope(cls: type[Handler]) -> bool:
    """True for a library handler or one of this repository's project handlers."""
    if cls.__module__.startswith(handlers_package.__name__ + "."):
        return True
    try:
        source = inspect.getsourcefile(cls)
    except (TypeError, OSError):
        return False
    return source is not None and Path(source).resolve().is_relative_to(_PROJECT_HANDLERS_DIR)


def _judge(handler: Handler, result: Any) -> str | None:
    """The complaint about a deny result, or ``None`` if it is acceptable."""
    if getattr(result, "decision", None) is not Decision.DENY:
        return None
    declared = {rule.rule_id for rule in handler.get_rules()}
    name = type(handler).__name__
    if not declared and name in _ALLOWLISTED:
        return None
    reason = getattr(result, "reason", None) or ""
    first_line = reason.strip().splitlines()[0] if reason.strip() else "(empty reason)"
    match = _HEADLINE.search(reason)
    if match is None:
        return f"{name}: deny reason has no `BLOCKED [R-...]` headline: {first_line!r}"
    if match.group(1) not in declared:
        return (
            f"{name}: deny names {match.group(1)}, which its get_rules() does not "
            f"declare ({sorted(declared)})"
        )
    return None


def _wrap(cls: type[Handler]) -> None:
    """Replace the ``handle`` ``cls`` defines itself with a judging wrapper."""
    original = vars(cls).get("handle")
    if not callable(original) or getattr(original, _WRAPPED_MARK, False):
        return

    @functools.wraps(original)
    def judged(self: Handler, *args: Any, **kwargs: Any) -> Any:
        result = original(self, *args, **kwargs)
        complaint = _judge(self, result)
        if complaint is not None:
            _violations.append(f"{os.environ.get('PYTEST_CURRENT_TEST', '?')}: {complaint}")
        return result

    setattr(judged, _WRAPPED_MARK, True)
    type.__setattr__(cls, "handle", judged)
    _wrapped.append((cls, original))


def _all_handler_classes() -> list[type[Handler]]:
    """Every concrete Handler subclass defined so far, transitively."""
    found: list[type[Handler]] = []
    pending = list(Handler.__subclasses__())
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        if not inspect.isabstract(cls):
            found.append(cls)
    return found


def pytest_collection_finish(session: pytest.Session) -> None:
    """Wrap every in-scope handler class: the library's and this project's own.

    Collection has imported every test module, and a project handler is
    imported by its co-located test, so waiting until now sees them all.
    """
    for _finder, module_name, _ispkg in pkgutil.walk_packages(
        handlers_package.__path__, prefix=handlers_package.__name__ + "."
    ):
        importlib.import_module(module_name)
    for cls in _all_handler_classes():
        if _in_scope(cls):
            _wrap(cls)


def pytest_unconfigure(config: pytest.Config) -> None:
    """Restore every wrapped ``handle``."""
    for cls, original in _wrapped:
        type.__setattr__(cls, "handle", original)
    _wrapped.clear()


@pytest.fixture(autouse=True)
def every_deny_carries_a_declared_rule_id() -> Generator[None, None, None]:
    """Fail a test whose handler denied without a declared ``BLOCKED [R-...]`` ID."""
    _violations.clear()
    yield
    found = list(dict.fromkeys(_violations))
    _violations.clear()
    if found:
        raise AssertionError(
            "A handler denied without a declared rule identifier "
            "(TOOLING-SPEC 5.3 / DETECTOR-SPEC 4.3). Build the reason with "
            "RuleFormatter().headline(rule) or BlockingResult.under_rule(rule):\n"
            + "\n".join(found)
        )


def register(config: pytest.Config) -> None:
    """Register this plugin once, for a conftest that cannot use ``pytest_plugins``."""
    if not config.pluginmanager.has_plugin(PLUGIN_NAME):
        config.pluginmanager.import_plugin(PLUGIN_NAME)
