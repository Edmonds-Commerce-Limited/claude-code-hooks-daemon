"""No handler or decision path can return ``ask`` (Plan 00474).

Claude Code keeps its critical-path removal prompt on, even in a bypass session,
when a PermissionRequest hook or a Bash/Edit/Read deny rule exists (vendored
``remote-docs/code.claude.com/docs/en/permission-modes.md``). The daemon's
position when the surface is omitted is that it never prompts a human itself: its
PreToolUse handlers allow or deny. This pins that, so a handler cannot start
returning ``ask`` and quietly make a bypass session interactive.

Decision capabilities the daemon knows (``Decision``): allow, continue, deny,
ask, defer. Only ``ask`` is pinned absent here; ``deny`` is the enforcement
route that replaces the omitted rules.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

from claude_code_hooks_daemon import handlers as handlers_pkg
from claude_code_hooks_daemon.core.decision_capability import decisions_referenced_by
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision


def _concrete_handlers() -> list[type[Handler]]:
    found: list[type[Handler]] = []
    for _finder, module_name, _ispkg in pkgutil.walk_packages(
        handlers_pkg.__path__, prefix=handlers_pkg.__name__ + "."
    ):
        module = importlib.import_module(module_name)
        for attribute in vars(module).values():
            if (
                inspect.isclass(attribute)
                and issubclass(attribute, Handler)
                and attribute is not Handler
                and attribute.__module__ == module.__name__
                and not getattr(attribute, "__abstractmethods__", None)
            ):
                found.append(attribute)
    return found


class TestNoHandlerAsks:
    def test_the_scan_reaches_the_shipped_handlers(self) -> None:
        assert len(_concrete_handlers()) > 60

    def test_the_scan_sees_decisions_at_all(self) -> None:
        seen = {d for cls in _concrete_handlers() for d in decisions_referenced_by(cls)}
        assert Decision.DENY in seen
        assert Decision.ALLOW in seen

    def test_no_handler_returns_ask(self) -> None:
        asking = [
            cls.__name__
            for cls in _concrete_handlers()
            if Decision.ASK in decisions_referenced_by(cls)
        ]
        assert asking == []
