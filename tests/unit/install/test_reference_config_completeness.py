"""The reference config lists every handler the registry knows, for every event.

Plan 00362 Task 1.2. ``.claude/hooks-daemon.yaml.example`` is the "new default"
the upgrade merges a client's customisations onto, so a handler it omits is one
no upgraded install can be offered. The client report (§2) found keys the
reference did not list; the one it was actually missing was the whole
``pseudo_events.nitpick`` block, which is why nothing could carry the two
relocated detectors to their new home.

The registry is the truth here, not the file: the assertion is built from what
the daemon discovers, so a handler added to the code without a reference entry
fails this test rather than shipping undocumented.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from claude_code_hooks_daemon.config.validator import ConfigValidator
from claude_code_hooks_daemon.install.handler_key_audit import audit_handler_keys
from claude_code_hooks_daemon.pseudo_events.registry import pseudo_event_handler_classes

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REFERENCE_CONFIG = _REPO_ROOT / ".claude" / "hooks-daemon.yaml.example"


@pytest.fixture(scope="module")
def reference() -> dict[str, Any]:
    loaded = yaml.safe_load(_REFERENCE_CONFIG.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_every_registered_handler_is_listed_for_its_event(reference: dict[str, Any]) -> None:
    handlers = reference["handlers"]
    missing: dict[str, list[str]] = {}
    for event in sorted(ConfigValidator.VALID_EVENT_TYPES):
        registered = ConfigValidator.get_available_handlers(event)
        listed = set((handlers.get(event) or {}).keys())
        absent = sorted(registered - listed)
        if absent:
            missing[event] = absent
    assert missing == {}, f"reference config omits registered handlers: {missing}"


def test_reference_config_lists_no_unregistered_handler(reference: dict[str, Any]) -> None:
    """The reference must not itself carry a retired or misplaced key."""
    assert audit_handler_keys(reference) == []


def test_every_pseudo_event_handler_is_listed(reference: dict[str, Any]) -> None:
    pseudo_events = reference.get("pseudo_events")
    assert isinstance(pseudo_events, dict), "reference config has no pseudo_events section"
    for name, classes in pseudo_event_handler_classes().items():
        block = pseudo_events.get(name)
        assert isinstance(block, dict), f"reference config has no pseudo_events.{name} block"
        assert block.get("triggers"), f"pseudo_events.{name} needs triggers to ever fire"
        listed = set((block.get("handlers") or {}).keys())
        assert (
            set(classes) <= listed
        ), f"pseudo_events.{name}.handlers omits {sorted(set(classes) - listed)}"
