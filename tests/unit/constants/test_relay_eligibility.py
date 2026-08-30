"""Regression: relay eligibility must be typed at the event catalogue, not a
stringly file-name set living inside ``forwarder_generator`` (Plan 00290
dogfood field report — commit 9d353fd3, EMERGENCY suspension).

The relay is a pure byte pump (EOF stdin -> socket -> stdout, no JSON
handling). It structurally cannot serve:

- ``raw_stdout`` events, where the legacy transport UNWRAPS the daemon's JSON
  response into a raw value on stdout (``response_mode="status"`` renders
  ``{"text": ...}`` as plain text; ``response_mode="worktree"`` extracts
  ``worktreePath`` — see ``.claude/init.sh``'s ``render_status``/
  ``print_worktree``). A relay-served raw_stdout event hands Claude Code the
  daemon's raw JSON envelope, which is not what either surface expects.
- events requiring CLIENT-SIDE exit-code translation (Stop/SubagentStop),
  where ``forward_stop_event`` turns the daemon's ``decision=block`` JSON
  into an exit-code-2 hard re-entry the relay's `exec` has no equivalent for.

``EventIDMeta.relay_eligible`` is the single typed source of truth for both
exclusions — a consumer can no longer hold an untyped file-name string set
that can silently drift from the catalogue.
"""

from claude_code_hooks_daemon.constants.events import EventID, wired_event_metas

# The exact set of wired events the relay cannot serve, named directly by
# their EventIDMeta constants (not by bash_key strings) so this test breaks
# loudly if a future catalogue edit changes which events are ineligible.
_EXPECTED_INELIGIBLE = frozenset(
    {
        EventID.STATUS_LINE,  # raw_stdout: text unwrap
        EventID.WORKTREE_CREATE,  # raw_stdout: path unwrap
        EventID.STOP,  # requires exit-code translation
        EventID.SUBAGENT_STOP,  # requires exit-code translation
    }
)


class TestRelayEligibleProperty:
    def test_raw_stdout_events_are_relay_ineligible(self) -> None:
        assert EventID.STATUS_LINE.raw_stdout is True
        assert EventID.STATUS_LINE.relay_eligible is False
        assert EventID.WORKTREE_CREATE.raw_stdout is True
        assert EventID.WORKTREE_CREATE.relay_eligible is False

    def test_exit_code_translation_events_are_relay_ineligible(self) -> None:
        assert EventID.STOP.requires_client_translation is True
        assert EventID.STOP.relay_eligible is False
        assert EventID.SUBAGENT_STOP.requires_client_translation is True
        assert EventID.SUBAGENT_STOP.relay_eligible is False

    def test_every_other_wired_event_is_relay_eligible(self) -> None:
        for meta in wired_event_metas():
            if meta in _EXPECTED_INELIGIBLE:
                continue
            assert meta.relay_eligible is True, meta.bash_key
            assert meta.raw_stdout is False, meta.bash_key
            assert meta.requires_client_translation is False, meta.bash_key

    def test_ineligible_set_matches_exactly(self) -> None:
        actual_ineligible = {meta for meta in wired_event_metas() if not meta.relay_eligible}
        assert actual_ineligible == _EXPECTED_INELIGIBLE

    def test_default_requires_client_translation_is_false(self) -> None:
        """A meta that declares neither raw_stdout nor requires_client_translation
        defaults to eligible — the common case for the vast majority of events."""
        assert EventID.PRE_TOOL_USE.requires_client_translation is False
        assert EventID.PRE_TOOL_USE.relay_eligible is True
