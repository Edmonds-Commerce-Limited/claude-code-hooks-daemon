"""Regression: per-event listeners must synthesise WIRE event names.

Field report (live session, relay dogfood): every status-line render
returned ``HOOKS DAEMON ERROR ... invalid_request: 1 validation error for
HookEvent — input_value='StatusLine'``. The per-event socket listener
synthesised ``{"event": meta.json_key}``, but the wire protocol value the
daemon's own ``EventType`` enum (and the legacy bash forwarder's
``send_request_stdin "Status"``) uses is ``Status`` — ``json_key`` is NOT
universally the wire name.

The fix is typed at the source: ``EventIDMeta.wire_key`` returns an
``EventType`` MEMBER, so a consumer cannot hold an unvalidated wire name.
These tests pin the property's semantics; the type checker enforces the
rest at every consumer.
"""

from claude_code_hooks_daemon.constants.events import EventID, EventType, wired_event_metas


class TestWireKeys:
    def test_every_wired_meta_resolves_a_typed_wire_key(self) -> None:
        for meta in wired_event_metas():
            # Property raises ValueError for an unresolvable name — resolving
            # at all IS the assertion; the isinstance pins the typed contract.
            assert isinstance(meta.wire_key, EventType), meta.bash_key

    def test_status_line_wire_key_is_status_not_json_key(self) -> None:
        assert EventID.STATUS_LINE.wire_key is EventType.STATUS_LINE
        assert EventID.STATUS_LINE.wire_key.value == "Status"
        assert EventID.STATUS_LINE.json_key == "StatusLine"

    def test_wire_key_matches_json_key_for_all_other_wired_events(self) -> None:
        for meta in wired_event_metas():
            if meta is EventID.STATUS_LINE:
                continue
            assert meta.wire_key.value == meta.json_key, meta.bash_key
