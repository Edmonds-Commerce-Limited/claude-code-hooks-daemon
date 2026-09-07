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


def _flush_sequence(count: int) -> list[object]:
    """Drive one AWAIT episode and return the decision of each flush attempt."""
    machine = CompactStateMachine(_policy())
    machine.evaluate(_reading(), idle=True, now=1000.0)
    return [
        machine.evaluate(_reading(), idle=True, now=1000.0 + 65.0 * (attempt + 1)).decision
        for attempt in range(count)
    ]


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
        reason = _flush_sequence(2)
        assert reason  # sequence drove far enough to produce the resubmit
        machine = CompactStateMachine(_policy())
        machine.evaluate(_reading(), idle=True, now=1000.0)
        machine.evaluate(_reading(), idle=True, now=1065.0)
        resubmit = machine.evaluate(_reading(), idle=True, now=1130.0)

        assert "unsubmitted" in resubmit.reason.lower()
        assert "2/5" in resubmit.reason


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
