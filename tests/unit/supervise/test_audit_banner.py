"""Plan 00318 — the supervisor's audit trail is a banner, not a chat injection.

Announcing the actions the supervisor took on the user's behalf used to cost a
whole model turn and a permanent transcript entry, for a notice whose only
audience is the human watching the terminal. It now goes out on the same
transient status-line channel as the Ctrl+C hint, with a longer TTL and a
visible countdown so it plainly announces its own transience.

`decision.log` stays the durable, complete audit record — the banner is the
glance-able surface, not the archive.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()

_NOW = 50_000.0
_SESSION = "banner-sess-1"


def _write_sidecar(sidecar_dir: Path, *, model_id: str = "claude-fable-5") -> None:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    (sidecar_dir / f"{_SESSION}.json").write_text(
        json.dumps(
            {
                "red": False,
                "critical": False,
                "compact_urgent": False,
                "tier": "ok",
                "pct": 20.0,
                "session_id": _SESSION,
                "ts": _NOW - 1.0,
                "seq": 1,
                "writer_pid": 42,
                "compacting": False,
                "model_id": model_id,
                "effort": "low",
            }
        ),
        encoding="utf-8",
    )


def _facts(*, input_line_empty: bool = True) -> object:
    return _mod.TickFacts(
        now_wall=_NOW,
        idle=True,
        input_line_empty=input_line_empty,
        human_compact_submitted=False,
        work_idle=True,
    )


def _flush(tmp_path: Path, *, items: tuple[str, ...], input_line_empty: bool = True) -> object:
    """Arm ``items`` and run the tick that flushes them."""
    sidecar_dir = tmp_path / "cs"
    _write_sidecar(sidecar_dir)
    machine = _mod.CompactStateMachine(_mod.CompactPolicy())
    for item in items:
        machine.arm_audit(item)
    return _mod.decide_once(
        machine,
        sidecar_dir=sidecar_dir,
        facts=_facts(input_line_empty=input_line_empty),
        dry_run=False,
        freshness_seconds=_mod.CompactPolicy().freshness_seconds,
    )


def _banner_payload(tmp_path: Path) -> dict[str, object]:
    path = tmp_path / _mod._LOG_SUBDIRECTORY / _mod._STATUS_MESSAGE_FILENAME
    return json.loads(path.read_text(encoding="utf-8"))


class TestAuditBannerText:
    def test_banner_is_the_actions_only_no_chat_preamble(self) -> None:
        banner = _mod._format_audit_banner(
            ("/effort low (coupled to model switch)", "/model fable (auto-restore after downgrade)")
        )
        assert banner.startswith(_mod._AUDIT_BANNER_GLYPH)
        assert f"{_mod._AUDIT_ACTION_EFFORT_GLYPH} effort low" in banner
        assert f"{_mod._AUDIT_ACTION_MODEL_GLYPH} model fable" in banner
        # The status line is width-constrained: the per-item reason, the
        # provenance preamble and the log path all belong to decision.log.
        assert "coupled to model switch" not in banner
        assert "decision.log" not in banner
        assert "NOT a human" not in banner

    def test_actions_are_comma_separated(self) -> None:
        """CSV, so a stacked banner scans as a list rather than a sentence."""
        banner = _mod._format_audit_banner(("/compact (a)", "/model fable (b)"))
        assert ", " in banner
        assert "; " not in banner


class TestRepeatsBecomeATally:
    """Plan 00355: `esc (20), compact (15)` — a count, not twenty repetitions."""

    def test_a_repeated_action_collapses_to_one_entry_with_a_count(self) -> None:
        banner = _mod._format_audit_banner(tuple(f"/compact (attempt {n})" for n in range(15)))
        assert "compact (15)" in banner
        assert banner.count("compact") == 1

    def test_a_single_action_carries_no_count(self) -> None:
        """`esc (1)` is noise; the bare name says the same thing."""
        banner = _mod._format_audit_banner(("/compact (once)",))
        assert "(1)" not in banner
        assert "compact" in banner

    def test_distinct_actions_keep_their_own_tallies(self) -> None:
        items = tuple(f"{_mod._ESC_AUDIT_LABEL} (flush {n})" for n in range(20)) + tuple(
            f"/compact (attempt {n})" for n in range(15)
        )
        banner = _mod._format_audit_banner(items)
        assert "esc (20)" in banner
        assert "compact (15)" in banner

    def test_nothing_is_truncated_away(self) -> None:
        """A tally is short by construction, so `+N more` has nothing to hide."""
        items = tuple(f"/effort {level} (x)" for level in ("low", "medium", "high", "xhigh"))
        banner = _mod._format_audit_banner(items)
        assert "more" not in banner
        for level in ("low", "medium", "high", "xhigh"):
            assert f"effort {level}" in banner

    def test_first_armed_action_is_shown_first(self) -> None:
        """Order tells the human what happened first; a set would not."""
        banner = _mod._format_audit_banner(("/model fable (a)", "/compact (b)"))
        assert banner.index("model fable") < banner.index("compact")


class TestAuditFlushPostsBanner:
    def test_flush_posts_a_countdown_banner_and_injects_nothing(self, tmp_path: Path) -> None:
        outcome = _flush(tmp_path, items=("/effort low (coupled to model switch)",))
        assert outcome.decision_value == _mod.Decision.WOULD_AUDIT.value
        # The whole point: no chat line, so no model turn and no context cost.
        assert outcome.payload is None
        payload = _banner_payload(tmp_path)
        assert payload["countdown"] is True
        assert payload["expires_at"] == _NOW + _mod._AUDIT_BANNER_TTL_SECONDS
        assert "effort low" in str(payload["text"])

    def test_flush_records_the_audit_in_the_decision_log_line(self, tmp_path: Path) -> None:
        outcome = _flush(tmp_path, items=("/model fable (auto-restore after downgrade)",))
        assert outcome.noop_reason_log is not None
        assert "audit" in outcome.noop_reason_log
        assert "/model fable" in outcome.noop_reason_log

    def test_flush_clears_the_pending_items(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        _write_sidecar(sidecar_dir)
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        machine.arm_audit("/effort low (coupled to model switch)")
        _mod.decide_once(
            machine,
            sidecar_dir=sidecar_dir,
            facts=_facts(),
            dry_run=False,
            freshness_seconds=_mod.CompactPolicy().freshness_seconds,
        )
        assert machine.audit_pending == ()

    def test_banner_posts_even_while_the_user_is_typing(self, tmp_path: Path) -> None:
        """A banner writes a file, not the PTY — it needs no empty input box."""
        outcome = _flush(
            tmp_path,
            items=("/effort low (coupled to model switch)",),
            input_line_empty=False,
        )
        assert outcome.decision_value == _mod.Decision.WOULD_AUDIT.value
        assert "effort low" in str(_banner_payload(tmp_path)["text"])

    def test_no_pending_items_posts_nothing(self, tmp_path: Path) -> None:
        outcome = _flush(tmp_path, items=())
        assert outcome.decision_value != _mod.Decision.WOULD_AUDIT.value
        assert not (tmp_path / _mod._LOG_SUBDIRECTORY / _mod._STATUS_MESSAGE_FILENAME).exists()


class TestAKeystrokeIsAnnouncedToo:
    """Plan 00355. The one family with no chat trace was the one that was silent.

    `/compact` and the resume nudge type visible text into the transcript, so a
    human can scroll back and see them. A raw ESC leaves nothing anywhere but
    `decision.log` — which is exactly why it reads as a random keypress, and why
    it is the family that most needs the banner.
    """

    def test_the_escape_label_is_a_plain_action_name(self) -> None:
        """It is a KEY, not a slash command, so it must not gain a slash."""
        assert not _mod._ESC_AUDIT_LABEL.startswith("/")
        assert not _mod._RESUBMIT_AUDIT_LABEL.startswith("/")

    def test_an_escape_item_renders_with_the_keystroke_glyph(self) -> None:
        banner = _mod._format_audit_banner((f"{_mod._ESC_AUDIT_LABEL} (flush a stalled /compact)",))
        assert f"{_mod._AUDIT_ACTION_KEYSTROKE_GLYPH} {_mod._ESC_AUDIT_LABEL}" in banner
        assert "stalled" not in banner

    def test_the_reason_still_reaches_the_decision_log(self, tmp_path: Path) -> None:
        """The banner drops it; the durable record must not."""
        outcome = _flush(tmp_path, items=(f"{_mod._ESC_AUDIT_LABEL} (flush a stalled /compact)",))
        assert outcome.noop_reason_log is not None
        assert "stalled" in outcome.noop_reason_log


def _urgent_sidecar(sidecar_dir: Path, *, now: float) -> None:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    (sidecar_dir / "fg.json").write_text(
        json.dumps(
            {
                "red": True,
                "critical": True,
                "compact_urgent": True,
                "tier": "critical",
                "pct": 96.0,
                "session_id": "fg",
                "ts": now,
                "seq": 1,
                "writer_pid": 1,
                "compacting": False,
            }
        ),
        encoding="utf-8",
    )


def _tick(
    machine: object,
    sidecar_dir: Path,
    *,
    now: float,
    dry_run: bool = False,
) -> object:
    return _mod.decide_once(
        machine,
        sidecar_dir=sidecar_dir,
        facts=_mod.TickFacts(
            now_wall=now,
            idle=True,
            input_line_empty=True,
            human_compact_submitted=False,
            work_idle=True,
        ),
        dry_run=dry_run,
        freshness_seconds=_mod.CompactPolicy().freshness_seconds,
    )


def _escape_episode(tmp_path: Path, *, dry_run: bool = False) -> tuple[object, object, Path]:
    """Drive the machine to a real ``WOULD_ESCAPE`` tick.

    An urgent sidecar makes the first tick compact; 61s later the queued
    compaction has not started, so the machine escapes to flush it. This is the
    exact path all 122 escapes in the reported session took.
    """
    sidecar_dir = tmp_path / "cs"
    _urgent_sidecar(sidecar_dir, now=1000.0)
    machine = _mod.CompactStateMachine(_mod.CompactPolicy())
    first = _tick(machine, sidecar_dir, now=1000.0, dry_run=dry_run)
    second = _tick(machine, sidecar_dir, now=1061.0, dry_run=dry_run)
    return first, second, sidecar_dir


class TestAKeystrokeFlushesWhenItIsSent:
    """Plan 00355 — the flush rule, which is the whole difficulty.

    00318 flushes only on a NOOP tick in MONITOR, so a `/model` + coupled
    `/effort` sequence surfaces as ONE banner once the sequence completes. But
    an ESC fires in AWAIT_COMPACTING, so an escape armed under that rule would
    surface minutes later in an unrelated state, or never. A keystroke
    therefore announces itself on the tick that sends it — without collapsing
    00318's batching for the slash-command families.
    """

    def test_a_real_escape_posts_its_banner_on_the_same_tick(self, tmp_path: Path) -> None:
        _, escape, _ = _escape_episode(tmp_path)
        assert escape.decision_value == _mod.Decision.WOULD_ESCAPE.value
        assert escape.payload == _mod._ESC_PAYLOAD
        assert _mod._ESC_AUDIT_LABEL in str(_banner_payload(tmp_path)["text"])

    def test_the_escape_banner_still_counts_down(self, tmp_path: Path) -> None:
        _escape_episode(tmp_path)
        payload = _banner_payload(tmp_path)
        assert payload["countdown"] is True
        assert payload["expires_at"] == 1061.0 + _mod._AUDIT_BANNER_TTL_SECONDS

    def test_announcing_does_not_displace_the_escape_decision(self, tmp_path: Path) -> None:
        """The banner rides along; it must not turn the tick into an audit NOOP."""
        _, escape, _ = _escape_episode(tmp_path)
        assert escape.decision_value != _mod.Decision.WOULD_AUDIT.value
        assert escape.payload is not None

    def test_the_escape_keeps_its_own_reason_in_the_decision_log(self, tmp_path: Path) -> None:
        """The banner is a convenience surface; the log is the record.

        The flush composes its own reason string. Letting that overwrite the
        escape's reason would replace `queued /compact stalled -> would inject
        [esc]` with `audit trail flush (1 item(s))` — destroying the exact line
        that made the 122 escapes diagnosable in the first place.
        """
        _, escape, _ = _escape_episode(tmp_path)
        assert "esc" in escape.reason
        assert "audit trail flush" not in escape.reason
        # Nor may it masquerade as a NOOP diagnostic: the tick injected a key.
        assert escape.noop_reason_log is None

    def test_a_dry_run_marker_is_not_a_keystroke(self, tmp_path: Path) -> None:
        """It types visible text and changes nothing — tallying it would lie."""
        _, escape, _ = _escape_episode(tmp_path, dry_run=True)
        assert escape.decision_value == _mod.Decision.WOULD_ESCAPE.value
        assert not (tmp_path / _mod._LOG_SUBDIRECTORY / _mod._STATUS_MESSAGE_FILENAME).exists()

    def test_a_yielded_banner_keeps_its_items_for_the_next_tick(self, tmp_path: Path) -> None:
        """Plan 00319 F9: yielding to a live Ctrl+C hint must not DROP the audit.

        Clearing on a suppressed write would silently lose the notice — and
        after Plan 00355 that suppression is routine rather than exceptional,
        since every escape now writes a banner. Retaining is also what lets a
        stack accumulate into `esc (20)` instead of vanishing one at a time.
        """
        sidecar_dir = tmp_path / "cs"
        _urgent_sidecar(sidecar_dir, now=1000.0)
        # A live WARNING (a Ctrl+C hint) is already on screen at tick time.
        _mod.write_status_message(
            tmp_path,
            text="ctrl+c hint",
            expires_at=2000.0,
            level=_mod._STATUS_LEVEL_WARNING,
        )
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        _tick(machine, sidecar_dir, now=1000.0)
        escape = _tick(machine, sidecar_dir, now=1061.0)

        assert escape.decision_value == _mod.Decision.WOULD_ESCAPE.value
        # The keystroke still went out; only its banner was held back.
        assert escape.payload == _mod._ESC_PAYLOAD
        assert _banner_payload(tmp_path)["text"] == "ctrl+c hint"
        assert machine.audit_pending != ()

    def test_a_slash_command_still_waits_for_its_sequence_to_finish(self, tmp_path: Path) -> None:
        """00318's batching: an armed /effort must NOT flush on an injection tick."""
        sidecar_dir = tmp_path / "cs"
        _urgent_sidecar(sidecar_dir, now=1000.0)
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        machine.arm_audit("/effort low (coupled to model switch)")

        outcome = _tick(machine, sidecar_dir, now=1000.0)

        assert outcome.decision_value == _mod.Decision.WOULD_COMPACT.value
        assert not (tmp_path / _mod._LOG_SUBDIRECTORY / _mod._STATUS_MESSAGE_FILENAME).exists()
        assert machine.audit_pending == ("/effort low (coupled to model switch)",)
