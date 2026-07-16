"""Hook-coverage completeness gate (Plan 00170).

The daemon's raison d'etre is intercepting Claude Code hook events. If Claude
Code fires an event the daemon does not wire, that event is invisible and a
client project cannot even attach a handler to it. This test is the enforcement
gate: it fails if any of the coupled wiring surfaces disagree, or if the daemon's
event catalogue drifts from the authoritative Claude Code hook-event set.

Surfaces cross-locked here (see Plan 00170 map):

- ``EventID`` catalogue (``constants/events.py``) — the SSoT of *what events exist*
- ``EventType`` dispatch enum (``core/event.py``) — must agree with the *wired* set
- On-disk forwarders (``.claude/hooks/<bash_key>``)
- ``.claude/settings.json`` hook registrations (via ``HOOK_EVENTS_IN_SETTINGS``)
- Input/response schema registries (``INPUT_SCHEMAS`` / ``RESPONSE_SCHEMAS``)

Governance (Plan 00170): every catalogue event is either fully **wired** or listed
in ``EXPECTED_UNWIRED`` (the tracked burn-down list). A newly discovered Claude
Code event that is neither catalogued nor acknowledged makes this test RED — which
is the point: coverage drift can never be silent.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from claude_code_hooks_daemon.constants.events import EventID, EventIDMeta
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.input_schemas import INPUT_SCHEMAS
from claude_code_hooks_daemon.core.response_schemas import RESPONSE_SCHEMAS
from claude_code_hooks_daemon.utils.hook_registration import HOOK_EVENTS_IN_SETTINGS

# ---------------------------------------------------------------------------
# Authoritative ground truth: the complete set of Claude Code hook events.
# Source: https://code.claude.com/docs/en/hooks (verified 2026-07-16, 30 events).
# StatusLine is a SEPARATE surface (top-level ``statusLine`` key, not a "hook"
# event) so it is intentionally excluded from this set and handled specially.
#
# When Claude Code adds a hook event, add it here AND to EventID. Until it is
# fully wired, add its json_key to EXPECTED_UNWIRED below.
# ---------------------------------------------------------------------------
CLAUDE_CODE_HOOK_EVENTS: frozenset[str] = frozenset(
    {
        "SessionStart",
        "Setup",
        "UserPromptSubmit",
        "UserPromptExpansion",
        "PreToolUse",
        "PermissionRequest",
        "PermissionDenied",
        "PostToolUse",
        "PostToolUseFailure",
        "PostToolBatch",
        "Notification",
        "MessageDisplay",
        "SubagentStart",
        "SubagentStop",
        "TaskCreated",
        "TaskCompleted",
        "Stop",
        "StopFailure",
        "TeammateIdle",
        "InstructionsLoaded",
        "ConfigChange",
        "CwdChanged",
        "FileChanged",
        "WorktreeCreate",
        "WorktreeRemove",
        "PreCompact",
        "PostCompact",
        "Elicitation",
        "ElicitationResult",
        "SessionEnd",
    }
)

# The StatusLine surface: catalogued in EventID but not a "hook" event. It carries
# known dual-naming — EventID.json_key is "StatusLine", while EventType, the schema
# registries, and settings.json use "Status" / "statusLine". It is therefore
# excluded from the hook-event cross-checks and asserted separately.
_STATUS_EVENTID_KEY = "StatusLine"
_STATUS_EVENTTYPE_VALUE = "Status"

# Burn-down list (Plan 00170): documented events not yet wired end-to-end.
# Each entry MUST have ``wired=False`` in EventID. As an event is wired, remove
# it from BOTH places in the same change. When this set is empty, the daemon
# wires every Claude Code hook event and the final-coverage assertion locks it.
EXPECTED_UNWIRED: frozenset[str] = frozenset(
    {
        "MessageDisplay",
    }
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOKS_DIR = _REPO_ROOT / ".claude" / "hooks"


def _all_metas() -> list[EventIDMeta]:
    """Return every EventIDMeta declared on EventID."""
    metas: list[EventIDMeta] = []
    for name in dir(EventID):
        attr = getattr(EventID, name)
        if isinstance(attr, EventIDMeta):
            metas.append(attr)
    return metas


def _wired_metas() -> list[EventIDMeta]:
    return [m for m in _all_metas() if m.wired]


def _wired_hook_metas() -> list[EventIDMeta]:
    """Wired events excluding the bespoke StatusLine surface."""
    return [m for m in _wired_metas() if m.json_key != _STATUS_EVENTID_KEY]


# ---------------------------------------------------------------------------
# Catalogue vs Claude Code ground truth
# ---------------------------------------------------------------------------


def test_catalogue_covers_every_claude_code_event() -> None:
    """EventID must catalogue exactly the Claude Code hook-event set (+ StatusLine)."""
    catalogue = {m.json_key for m in _all_metas()} - {_STATUS_EVENTID_KEY}
    missing = CLAUDE_CODE_HOOK_EVENTS - catalogue
    extra = catalogue - CLAUDE_CODE_HOOK_EVENTS
    assert not missing, f"EventID is missing Claude Code events: {sorted(missing)}"
    assert not extra, f"EventID has events not in the Claude Code catalogue: {sorted(extra)}"


def test_status_line_is_catalogued() -> None:
    """The StatusLine surface remains catalogued (separate from hook events)."""
    assert _STATUS_EVENTID_KEY in {m.json_key for m in _all_metas()}


# ---------------------------------------------------------------------------
# Wired / pending partition (burn-down governance)
# ---------------------------------------------------------------------------


def test_unwired_events_match_tracked_burndown() -> None:
    """Unwired catalogue events must equal the acknowledged burn-down set.

    Prevents silent drift in either direction: a newly-added event cannot be left
    unwired without acknowledgement, and an event cannot be quietly de-wired.
    """
    unwired = {m.json_key for m in _all_metas() if not m.wired}
    assert unwired == EXPECTED_UNWIRED, (
        "Unwired events diverged from the tracked burn-down list. "
        f"Only-in-code: {sorted(unwired - EXPECTED_UNWIRED)}; "
        f"only-in-list: {sorted(EXPECTED_UNWIRED - unwired)}"
    )


def test_pending_events_are_real_claude_code_events() -> None:
    """Every pending event is an actual Claude Code event (no typos)."""
    assert EXPECTED_UNWIRED <= CLAUDE_CODE_HOOK_EVENTS


# ---------------------------------------------------------------------------
# No half-wired event: every wired event agrees across ALL surfaces
# ---------------------------------------------------------------------------


def test_event_type_enum_matches_wired_catalogue() -> None:
    """The dispatch enum (EventType) must equal the wired EventID hook events.

    Compared excluding the StatusLine surface, which EventID names "StatusLine"
    but EventType values as "Status".
    """
    event_type_values = {e.value for e in EventType} - {_STATUS_EVENTTYPE_VALUE}
    wired_json_keys = {m.json_key for m in _wired_hook_metas()}
    assert event_type_values == wired_json_keys, (
        "EventType (dispatch) and wired EventID (catalogue) disagree. "
        f"Only-in-EventType: {sorted(event_type_values - wired_json_keys)}; "
        f"only-in-EventID: {sorted(wired_json_keys - event_type_values)}"
    )


def test_status_line_surface_is_wired() -> None:
    """The bespoke StatusLine surface is dispatchable and schema-backed."""
    assert _STATUS_EVENTTYPE_VALUE in {e.value for e in EventType}
    assert _STATUS_EVENTTYPE_VALUE in INPUT_SCHEMAS
    assert _STATUS_EVENTTYPE_VALUE in RESPONSE_SCHEMAS


def test_wired_events_have_executable_forwarder() -> None:
    """Every wired event has an executable forwarder script on disk."""
    for meta in _wired_metas():
        forwarder = _HOOKS_DIR / meta.bash_key
        assert forwarder.is_file(), f"Missing forwarder for {meta.json_key}: {forwarder}"
        assert os.access(forwarder, os.X_OK), f"Forwarder not executable: {forwarder}"


def test_wired_events_have_input_and_response_schemas() -> None:
    """Every wired hook event has both an input and a response schema registered."""
    for meta in _wired_hook_metas():
        assert meta.json_key in INPUT_SCHEMAS, f"No INPUT_SCHEMAS entry for {meta.json_key}"
        assert meta.json_key in RESPONSE_SCHEMAS, f"No RESPONSE_SCHEMAS entry for {meta.json_key}"


def test_wired_hook_events_registered_in_settings() -> None:
    """Every wired hook event (excluding StatusLine) is registered in settings.json."""
    settings_path = _REPO_ROOT / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    registered = set(settings.get("hooks", {}).keys())

    for meta in _wired_hook_metas():
        assert (
            meta.json_key in HOOK_EVENTS_IN_SETTINGS
        ), f"{meta.json_key} absent from HOOK_EVENTS_IN_SETTINGS (EventID-derived)"
        assert meta.json_key in registered, f"{meta.json_key} not registered in settings.json hooks"


def test_status_line_registered_in_settings() -> None:
    """StatusLine registers under the top-level ``statusLine`` key, not ``hooks``."""
    settings_path = _REPO_ROOT / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "statusLine" in settings, "statusLine missing from settings.json"


def test_settings_map_excludes_unwired_events() -> None:
    """Unwired events must NOT leak into the settings requirement set.

    HOOK_EVENTS_IN_SETTINGS drives the live hook_registration_checker; an unwired
    event appearing there would (wrongly) demand a settings entry that does not
    yet exist.
    """
    for json_key in EXPECTED_UNWIRED:
        assert (
            json_key not in HOOK_EVENTS_IN_SETTINGS
        ), f"Unwired event {json_key} leaked into HOOK_EVENTS_IN_SETTINGS"
