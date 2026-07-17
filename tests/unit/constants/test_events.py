"""Tests for the event-identifier catalogue in ``constants/events.py``.

The ``EventID`` catalogue is the single source of truth for what hook events
exist. ``EventKey`` is a static ``Literal`` mirror of every event's
``config_key`` (a ``Literal`` cannot be built from ``all_event_metas()`` at
type-check time, so it is duplicated). These tests pin the mirror to the
catalogue so it can never silently drift again — the exact failure that Plan
00170 left behind, where ``EventKey`` still listed only the original 11 events.
"""

from typing import get_args

from claude_code_hooks_daemon.constants.events import (
    EventID,
    EventKey,
    all_event_metas,
    wired_event_metas,
)


def test_event_key_literal_matches_catalogue() -> None:
    """Every ``EventID`` config_key must appear in the ``EventKey`` literal."""
    literal_members = set(get_args(EventKey))
    catalogue_keys = {meta.config_key for meta in all_event_metas()}
    assert literal_members == catalogue_keys, (
        "EventKey literal drifted from the EventID catalogue. "
        f"missing-from-EventKey: {sorted(catalogue_keys - literal_members)}; "
        f"stale-in-EventKey: {sorted(literal_members - catalogue_keys)}"
    )


def test_event_key_literal_preserves_catalogue_order() -> None:
    """The literal lists config_keys in the same order as the catalogue."""
    assert list(get_args(EventKey)) == [meta.config_key for meta in all_event_metas()]


def test_event_key_members_are_unique() -> None:
    """No duplicate config_key slipped into the literal."""
    members = get_args(EventKey)
    assert len(members) == len(set(members))


def test_wired_events_are_subset_of_catalogue() -> None:
    """Wired events are always a subset of the full catalogue."""
    wired = {meta.config_key for meta in wired_event_metas()}
    catalogue = {meta.config_key for meta in all_event_metas()}
    assert wired <= catalogue


def test_catalogue_config_keys_are_snake_case() -> None:
    """Every config_key is lower snake_case (no hyphens, spaces, or caps)."""
    for meta in all_event_metas():
        key = meta.config_key
        assert key == key.lower()
        assert " " not in key
        assert "-" not in key


def test_all_event_metas_nonempty_and_declared_on_eventid() -> None:
    """The reflection helper returns the metas declared on ``EventID``."""
    metas = all_event_metas()
    assert metas
    for meta in metas:
        assert getattr(EventID, meta.enum_value) is meta
