"""Tests for Handler.get_default_enabled() — Plan 00133 Phase 1.

Design contract:
  - Handler base class has get_default_enabled() -> bool method
  - Default implementation returns True (most handlers are opt-out / on-by-default)
  - The method is NOT abstract (so existing + project handlers don't break)
  - Subclasses can override to return False to declare themselves opt-in
    (off-by-default)

This method is the single source of truth for a handler's default enabled
state, consumed by config-template generation so the template no longer
hand-maintains a `{enabled: true/false}` literal per handler.
"""

from __future__ import annotations

import inspect
from typing import Any

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult

# ---------------------------------------------------------------------------
# Concrete test handlers
# ---------------------------------------------------------------------------


class _DefaultHandler(Handler):
    """Handler that does NOT override get_default_enabled() — opt-out by default."""

    def __init__(self) -> None:
        super().__init__(handler_id=HandlerID.TEST_SERVER, priority=Priority.TEST_HANDLER)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        return []


class _OptInHandler(Handler):
    """Handler that overrides get_default_enabled() -> False (off-by-default)."""

    def __init__(self) -> None:
        super().__init__(handler_id=HandlerID.TEST_SERVER, priority=Priority.TEST_HANDLER)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        return []

    def get_default_enabled(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# Tests for default behaviour
# ---------------------------------------------------------------------------


class TestGetDefaultEnabledBase:
    """Handler.get_default_enabled() has a default implementation returning True."""

    def test_method_exists_on_base(self) -> None:
        assert hasattr(Handler, "get_default_enabled")
        assert callable(Handler.get_default_enabled)

    def test_not_abstract(self) -> None:
        """get_default_enabled() is NOT abstract — handlers need not implement it."""
        # _DefaultHandler does not override it and can still be instantiated.
        handler = _DefaultHandler()
        assert isinstance(handler, Handler)

    def test_default_returns_true(self) -> None:
        handler = _DefaultHandler()
        assert handler.get_default_enabled() is True

    def test_returns_bool(self) -> None:
        handler = _DefaultHandler()
        assert isinstance(handler.get_default_enabled(), bool)


class TestGetDefaultEnabledOverride:
    """Handler subclasses can override get_default_enabled() to declare opt-in."""

    def test_override_returns_false(self) -> None:
        handler = _OptInHandler()
        assert handler.get_default_enabled() is False


class TestGetDefaultEnabledAnnotation:
    """get_default_enabled() has the correct return type annotation."""

    def test_annotation_returns_bool(self) -> None:
        sig = inspect.signature(Handler.get_default_enabled)
        assert sig.return_annotation in (bool, "bool")
