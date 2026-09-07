"""A stalled `/compact` may be UNSUBMITTED, not queued — and ESC cannot fix that.

Reported live: the supervisor's compaction message sat in Claude Code's input
box with a newline after it, never submitted.

`_perform_injection` writes the payload, sleeps `_SUBMIT_DELAY_SECONDS` (0.2s),
then writes a standalone ``\\r``. That delay is on the WRITE side, but whether
the two writes are seen as one burst is decided at the READER. Probing a real
Claude Code established what the burst then does: a large one is treated as
PASTED TEXT, and a carriage return inside pasted text is a literal newline
rather than a submit — see `test_paste_framed_injection.py` for the
measurements and the framing that fixes it.

This module covers the SAFETY NET rather than that fix: whatever the reason, a
line that reaches the box unsubmitted needs an Enter, because ESC cannot submit
it.

The supervisor cannot see this happen. Its own injections are deliberately kept
out of the `HumanInputLine` box model (so they can never mark the box
non-empty), so the one observable that distinguishes the two stall causes is
excluded by design:

* **queued behind an in-flight turn** — the line WAS submitted; ``[esc]``
  flushes it. Proven in the field, and the existing `TestEscapeFlush` contract.
* **never submitted** — the line is sitting in the box; ``[esc]`` does nothing
  for it. All five escapes burn, the machine returns to MONITOR, and after the
  cooldown it injects a SECOND `/compact` on top of the first — which is how the
  box ends up holding a compaction message, a newline, and more text.

Each escape also refreshes ``_last_action_ts``, which both `_escape_due` and
`_await_timed_out` measure from, so the await timeout can never cut the
sequence short: the full escape budget always burns before anything else.

The fix is additive, not a replacement. ESC stays the FIRST remedy — it is the
proven one for the proven cause — and a standalone Enter is ALTERNATED in from
the second attempt, so a stuck box is submitted by the time ESC has visibly
failed once. Both remedies are already gated on an empty human input box,
because the machine only flushes when ``idle`` is True and the caller ANDs
``input_line_empty`` into it.
"""

from __future__ import annotations

from tests.unit.supervise._load import load_supervisor_module

_mod = load_supervisor_module()
CompactPolicy = _mod.CompactPolicy
CompactStateMachine = _mod.CompactStateMachine
Decision = _mod.Decision
SupervisorState = _mod.SupervisorState


def _reading(**overrides: object) -> object:
    """A red, non-compacting sidecar reading — the AWAIT_COMPACTING input."""
    fields: dict[str, object] = {
        "red": True,
        "critical": True,
        "compact_urgent": True,
        "tier": "red",
        "pct": 95.0,
        "session_id": "s",
        "ts": 1000.0,
        "seq": 1,
        "writer_pid": 1,
        "compacting": False,
        "stale": False,
    }
    fields.update(overrides)
    return _mod.SidecarReading(**fields)


def _policy(**overrides: object) -> object:
    fields: dict[str, object] = {
        "escape_after_seconds": 60,
        "await_timeout_seconds": 600,
        "max_escapes": 5,
    }
    fields.update(overrides)
    return CompactPolicy(**fields)


def _flush_attempts(count: int, *, policy: object | None = None) -> list[tuple[object, float]]:
    """Drive one AWAIT episode, returning each flush attempt and WHEN it fired.

    Steps the clock in poll-sized ticks rather than jumping a fixed interval, so
    the timing between attempts is observed rather than assumed -- which is the
    whole point once the interval before a resubmit differs from the interval
    before an escape.
    """
    machine = CompactStateMachine(policy or _policy())
    now = 1000.0
    machine.evaluate(_reading(), idle=True, now=now)
    attempts: list[tuple[object, float]] = []
    while len(attempts) < count and now < 1000.0 + 2000.0:
        now += 1.0
        decision = machine.evaluate(_reading(), idle=True, now=now).decision
        if decision is not Decision.NOOP:
            attempts.append((decision, now))
    return attempts


def _flush_sequence(count: int) -> list[object]:
    """Just the decisions, for tests that do not care about timing."""
    return [decision for decision, _ in _flush_attempts(count)]


class TestTheStallRemedyCoversBothCauses:
    """ESC alone cannot submit a line sitting unsubmitted in the input box."""

    def test_the_first_flush_is_still_an_escape(self) -> None:
        """Regression guard: the proven remedy for the proven cause is unchanged.

        A queued `/compact` is the cause that has actually been observed
        resolving in the field (decision.log: escape 1/5, compaction detected
        two seconds later). Reordering that away to chase the second cause
        would trade a confirmed fix for a hypothesis.
        """
        assert _flush_sequence(1) == [Decision.WOULD_ESCAPE]

    def test_a_resubmit_follows_once_escape_has_visibly_failed(self) -> None:
        """The second attempt presses Enter, because ESC did not work.

        By this point the escape remedy has had a full interval and the
        compaction still has not started, so the queued-command explanation is
        no longer the leading one.
        """
        assert _flush_sequence(2)[1] is Decision.WOULD_RESUBMIT

    def test_the_remedies_alternate_so_neither_cause_is_starved(self) -> None:
        """Neither cause can be diagnosed, so both remedies must keep firing."""
        assert _flush_sequence(5) == [
            Decision.WOULD_ESCAPE,
            Decision.WOULD_RESUBMIT,
            Decision.WOULD_ESCAPE,
            Decision.WOULD_RESUBMIT,
            Decision.WOULD_ESCAPE,
        ]

    def test_resubmits_count_against_the_budget_and_the_episode_still_ends(self) -> None:
        """The point of max_escapes is that a wedged session stops escalating.

        Adding a second remedy must not double the budget or the give-up
        behaviour silently doubles in duration.
        """
        machine = CompactStateMachine(_policy(max_escapes=2))
        machine.evaluate(_reading(), idle=True, now=1000.0)

        first = machine.evaluate(_reading(), idle=True, now=1065.0)
        second = machine.evaluate(_reading(), idle=True, now=1130.0)
        gave_up = machine.evaluate(_reading(), idle=True, now=1200.0)

        assert first.decision is Decision.WOULD_ESCAPE
        assert second.decision is Decision.WOULD_RESUBMIT
        assert gave_up.decision is Decision.NOOP
        assert machine.state is SupervisorState.MONITOR

    def test_the_reason_names_the_cause_it_is_addressing(self) -> None:
        """decision.log is the only record; an unexplained Enter is a mystery."""
        machine = CompactStateMachine(_policy())
        machine.evaluate(_reading(), idle=True, now=1000.0)
        machine.evaluate(_reading(), idle=True, now=1065.0)
        resubmit = machine.evaluate(_reading(), idle=True, now=1130.0)

        assert "unsubmitted" in resubmit.reason.lower()
        assert "2/5" in resubmit.reason


class TestTheEnterFollowsItsEscapeCloselyEnoughToBeSafe:
    """A blind Enter CONFIRMS a modal dialog. Measured, not supposed.

    Driving a real Claude Code v2.1.263 over a PTY with the `/model` picker
    open — the picker states the bindings itself, "Enter to set as default ·
    s to use this session only · Esc to cancel":

    * **Enter** answered "Set model to Opus 5 and saved as your default for new
      sessions" — a persisted change the human never asked for.
    * **ESC** answered "Kept model as Opus 5" — dismissed, nothing changed.

    So ESC-before-Enter is a real mitigation, and the ordering already had it:
    ESC is always attempt 1. What it did NOT have was proximity. The remedies
    alternated at `escape_after_seconds`, so a dialog opened AFTER the escape
    was still on screen for the Enter a full interval later — a 60-second
    window in which the supervisor confirms whatever is highlighted.

    The fix is to keep the alternation and shorten only the wait BEFORE a
    resubmit, so an Enter is always closely preceded by an ESC that would have
    dismissed any dialog. Verified on the same rig: with a dialog open,
    ESC-pause-Enter left the default unconfirmed; with text in the box, the
    same pair still submitted it (one ESC does not clear the box); and Enter on
    an empty box is a no-op.

    Deliberately NOT done: emitting a single new "escape then enter" decision.
    The payload and decision names are the worker→host protocol, and the host
    NEVER hot-reloads — a new worker talks to the OLD host until the ccy
    session restarts, and that host would either reject an unknown decision
    value or paste a raw ESC as literal text. Shortening an interval changes
    nothing either side has to understand.
    """

    def test_the_resubmit_follows_its_escape_within_the_short_interval(self) -> None:
        attempts = _flush_attempts(2)
        (first, first_at), (second, second_at) = attempts

        assert first is Decision.WOULD_ESCAPE
        assert second is Decision.WOULD_RESUBMIT
        assert second_at - first_at <= _mod._RESUBMIT_FOLLOW_SECONDS

    def test_the_escape_still_waits_the_full_configured_interval(self) -> None:
        """Only the wait before an ENTER is shortened; escalation pacing holds."""
        attempts = _flush_attempts(3)
        _, first_at = attempts[0]
        _, third_at = attempts[2]

        assert first_at - 1000.0 >= 60.0
        assert third_at - first_at >= 60.0

    def test_no_enter_ever_fires_long_after_its_escape(self) -> None:
        """The invariant that makes the blind Enter safe, across a whole episode."""
        attempts = _flush_attempts(5)
        last_escape_at: float | None = None
        for decision, when in attempts:
            if decision is Decision.WOULD_ESCAPE:
                last_escape_at = when
                continue
            assert last_escape_at is not None, "an Enter fired with no preceding ESC"
            assert when - last_escape_at <= _mod._RESUBMIT_FOLLOW_SECONDS

    def test_the_follow_interval_still_lets_a_tick_land(self) -> None:
        """Shorter than a poll interval would mean the resubmit never fires."""
        assert _mod._RESUBMIT_FOLLOW_SECONDS >= _mod._DEFAULT_POLL_SECONDS


class TestTheResubmitInheritsEveryExistingGuard:
    """A blind Enter is dangerous; it must be no less guarded than the ESC."""

    def test_no_resubmit_while_the_session_is_busy(self) -> None:
        """`idle` also carries the empty-input-box guard from the caller.

        `_evaluate_tick` computes ``can_inject = facts.idle and
        facts.input_line_empty`` and passes it as ``idle``, so a False here is
        exactly the case where the human has typed something — and an Enter
        would submit THEIR half-written message.
        """
        machine = CompactStateMachine(_policy())
        machine.evaluate(_reading(), idle=True, now=1000.0)
        machine.evaluate(_reading(), idle=True, now=1065.0)

        assert machine.evaluate(_reading(), idle=False, now=1130.0).decision is Decision.NOOP

    def test_no_resubmit_for_a_human_originated_compact(self) -> None:
        """The human owns flushing their own `/compact`, by either remedy."""
        machine = CompactStateMachine(_policy())
        machine.evaluate(_reading(), idle=True, now=1000.0, human_compact_submitted=True)

        for now in (1065.0, 1130.0, 1195.0):
            assert machine.evaluate(_reading(), idle=True, now=now).decision is Decision.NOOP

    def test_a_started_compaction_stops_the_sequence(self) -> None:
        """Once compaction is under way neither remedy may fire again.

        An Enter here would submit an empty box mid-compaction; an ESC would
        interrupt it, which the owner ruled out.
        """
        machine = CompactStateMachine(_policy())
        machine.evaluate(_reading(), idle=True, now=1000.0)
        machine.evaluate(_reading(), idle=True, now=1065.0)

        started = machine.evaluate(_reading(compacting=True), idle=True, now=1130.0)

        assert started.decision is not Decision.WOULD_RESUBMIT
        assert started.decision is not Decision.WOULD_ESCAPE


class TestTheResubmitPayloadIsABareEnter:
    """It is a keypress, not a line — so it must not be Enter-submitted itself."""

    def test_armed_resubmit_is_a_lone_carriage_return(self) -> None:
        assert _mod._resolve_payload(Decision.WOULD_RESUBMIT, dry_run=False) == "\r"

    def test_dry_run_resubmit_is_a_visible_marker_not_a_real_enter(self) -> None:
        """Dry-run must never press a real Enter into a live session."""
        payload = _mod._resolve_payload(Decision.WOULD_RESUBMIT, dry_run=True)

        assert payload is not None
        assert "\r" not in payload
        assert _mod._BOT_PREFIX in payload

    def test_the_armed_resubmit_writes_exactly_one_carriage_return(self) -> None:
        """Submitting the submit would send TWO Enters and submit an empty box.

        The ESC path already models this: a raw keypress is injected with
        ``submit=False``. The resubmit is the same shape.
        """
        written: list[bytes] = []
        _mod._perform_injection(written.append, "\r", submit=False, sleep=lambda _: None)

        assert written == [b"\r"]
