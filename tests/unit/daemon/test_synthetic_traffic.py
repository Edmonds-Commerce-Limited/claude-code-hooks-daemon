"""Tests for the synthetic-vs-real traffic discriminator (Plan 00418 Task 2.2).

The defect this closes: `verdicts.jsonl` recorded acceptance-playbook probes
and socket integration-test fires in the same undifferentiated stream as a
real agent session, and nothing in the record said which was which. Every
figure Plan 00418 Task 2.1 quoted was ~50% synthetic as a result, and it
passed every check because nothing said the two should be told apart.

Two ways in, deliberately, and their precedence is the interesting part:

1. A producer MARKS its own events (`synthetic_source`). This is the truthful
   route — the harness knows it is a harness.
2. A known synthetic SESSION SHAPE is recognised. This is the fallback that
   classifies records written before the marker existed, and events from a
   producer that cannot be changed.

An unmarked, unrecognised session is REAL. Guessing in the other direction
would silently discard an agent's own traffic, which is the failure the
record exists to avoid.
"""

from claude_code_hooks_daemon.daemon.synthetic_traffic import (
    PLAYBOOK_PROBE,
    SOCKET_STDIN_TEST,
    SYNTHETIC_SOURCE_FIELD,
    VERDICT_SYNTHETIC_FIELD,
    classify_synthetic,
    event_synthetic_source,
    is_synthetic_event,
    record_synthetic_source,
)


class TestClassifySynthetic:
    """The one predicate every surface shares, so none can disagree."""

    def test_nothing_known_is_real(self) -> None:
        assert classify_synthetic(marker=None, session_id="9679b063-aaaa") is None

    def test_an_explicit_marker_names_the_source(self) -> None:
        assert classify_synthetic(marker="my-harness", session_id="s") == "my-harness"

    def test_a_marker_wins_over_the_session_shape(self) -> None:
        """The producer knows what it is; a shape match is only ever a guess."""
        assert classify_synthetic(marker="my-harness", session_id="playbook-probe-r1-7") == (
            "my-harness"
        )

    def test_a_playbook_probe_session_is_recognised(self) -> None:
        assert classify_synthetic(marker=None, session_id="playbook-probe-r1-7") == PLAYBOOK_PROBE

    def test_the_socket_stdin_test_session_is_recognised(self) -> None:
        assert classify_synthetic(marker=None, session_id="socket-stdin-test") == SOCKET_STDIN_TEST

    def test_an_absent_session_is_real_not_synthetic(self) -> None:
        """`default` means the session id was absent, which is not evidence.

        The decision document counted these alongside the probes; that was a
        convenience, not a finding. A dispatch with no session id can come
        from a real agent just as easily as from a test, so classifying it
        synthetic would discard real traffic on no evidence at all.
        """
        assert classify_synthetic(marker=None, session_id=None) is None
        assert classify_synthetic(marker=None, session_id="default") is None

    def test_a_non_string_marker_is_ignored_rather_than_stringified(self) -> None:
        """The value reaches a log, so only a real string may become a label."""
        assert classify_synthetic(marker=17, session_id="s") is None
        assert classify_synthetic(marker={"a": 1}, session_id="s") is None

    def test_an_empty_marker_is_not_a_source(self) -> None:
        assert classify_synthetic(marker="", session_id="s") is None

    def test_a_non_string_session_is_ignored(self) -> None:
        assert classify_synthetic(marker=None, session_id=17) is None


class TestEventSyntheticSource:
    def test_a_marked_event_is_synthetic(self) -> None:
        hook_input = {
            "tool_name": "Write",
            SYNTHETIC_SOURCE_FIELD: PLAYBOOK_PROBE,
            "session_id": "playbook-probe-r1-7",
        }
        assert event_synthetic_source(hook_input) == PLAYBOOK_PROBE
        assert is_synthetic_event(hook_input) is True

    def test_an_unmarked_probe_session_is_still_recognised(self) -> None:
        hook_input = {"tool_name": "Write", "session_id": "playbook-probe-r1-7"}
        assert event_synthetic_source(hook_input) == PLAYBOOK_PROBE

    def test_a_real_agent_event_is_not_synthetic(self) -> None:
        hook_input = {"tool_name": "Write", "session_id": "9679b063-1111-2222"}
        assert event_synthetic_source(hook_input) is None
        assert is_synthetic_event(hook_input) is False

    def test_an_event_with_no_session_at_all_is_not_synthetic(self) -> None:
        assert is_synthetic_event({"tool_name": "Write"}) is False


class TestRecordSyntheticSource:
    """A written verdict record uses different field names from an event."""

    def test_a_recorded_marker_names_the_source(self) -> None:
        record = {"session": "s", VERDICT_SYNTHETIC_FIELD: PLAYBOOK_PROBE}
        assert record_synthetic_source(record) == PLAYBOOK_PROBE

    def test_a_pre_marker_record_is_classified_from_its_session(self) -> None:
        """The whole window written before the marker existed stays readable."""
        record = {"session": "playbook-probe-r1-7"}
        assert record_synthetic_source(record) == PLAYBOOK_PROBE

    def test_a_real_session_record_is_real(self) -> None:
        assert record_synthetic_source({"session": "9679b063-1111"}) is None

    def test_an_explicit_null_marker_does_not_override_the_session_shape(self) -> None:
        """A record written by the new writer for a probe with no marker."""
        record = {"session": "playbook-probe-r1-7", VERDICT_SYNTHETIC_FIELD: None}
        assert record_synthetic_source(record) == PLAYBOOK_PROBE
