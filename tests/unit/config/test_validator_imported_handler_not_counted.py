"""The validator's handler scan uses the registry's module-aware predicate.

Validation and registration must agree on what a handler module contains: a
handler class merely IMPORTED into another handler module (the owner-wait stop
guard imports ``AutoContinueStopHandler``) belongs to the module defining it.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.config.validator import ConfigValidator
from claude_code_hooks_daemon.handlers import registry
from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import AutoContinueStopHandler

_IMPORTING_MODULE = "claude_code_hooks_daemon.handlers.stop.owner_wait_stop_guard"


def test_validator_scan_passes_defining_module_and_skips_imported_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, str | None, bool]] = []
    real = registry.is_discoverable_handler

    def recording(attr: Any, defined_in: str | None = None) -> bool:
        result = real(attr, defined_in)
        calls.append((attr, defined_in, result))
        return result

    monkeypatch.setattr(registry, "is_discoverable_handler", recording)
    monkeypatch.setattr(ConfigValidator, "_handler_cache", {})

    names = ConfigValidator.get_available_handlers("stop")

    assert "auto_continue_stop" in names
    handler_calls = [c for c in calls if c[0] is AutoContinueStopHandler]
    assert handler_calls, "scan never looked at the imported class"
    assert all(defined_in is not None for _a, defined_in, _r in handler_calls)
    imported = [c for c in handler_calls if c[1] == _IMPORTING_MODULE]
    assert imported
    assert all(result is False for _a, _d, result in imported)
