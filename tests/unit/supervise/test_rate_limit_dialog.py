"""Plan 00523: the supervisor answers Claude Code's rate-limit options dialog.

The screen fixtures below are RECONSTRUCTED, not captured live. No real
capture of the dialog exists yet; the text is built from the strings in the
Claude Code 2.1.330 bundle (dialog title ``What do you want to do?``, row
label ``Stop and wait for limit to reset``, the ``You've hit your <limit> ·
resets <time>`` message and its time formats). The row shape (pointer, ``1. label``)
follows Claude Code's Select rendering. The supervisor saves the first
unrecognised dialog-like screen to ``supervise-rate-limit-unrecognised.txt``
so a real incident can replace these fixtures.

The detector must be strict: it may type keys, so anything it does not
recognise exactly is left alone.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from tests.unit.supervise._load import load_supervisor_module

_mod = load_supervisor_module()

_TARGET = "Stop and wait for limit to reset"
_POINTER = chr(0x276F)  # Claude Code's Select pointer glyph
_LONDON = ZoneInfo("Europe/London")
# 2026-11-23 10:00 Europe/London (UTC+0 in November).
_NOW = datetime(2026, 11, 23, 10, 0, tzinfo=_LONDON).timestamp()

_TRANSCRIPT = [
    "● Running the targeted tests now.",
    "",
    "  ⎿  You've hit your 5-hour limit · resets 3pm (Europe/London)",
    "",
]


def _dialog(
    options: list[str],
    *,
    pointer: int = 0,
    boxed: bool = True,
    footer: tuple[str, ...] = ("Enter to confirm · Esc to cancel",),
) -> str:
    """A rendered screen ending in the dialog (reconstructed, see module doc)."""
    body = ["What do you want to do?", ""]
    for index, label in enumerate(options):
        marker = _POINTER if index == pointer else " "
        body.append(f"{marker} {index + 1}. {label}")
    if boxed:
        width = 60
        rows = ["╭" + "─" * width + "╮"]
        rows += [f"│ {line.ljust(width - 2)} │" for line in body]
        rows.append("╰" + "─" * width + "╯")
    else:
        rows = ["─" * 60, *body]
    return "\n".join([*_TRANSCRIPT, *rows, *footer]) + "\n"


_STANDARD = [_TARGET, "Wait here, then continue automatically at 3pm", "Upgrade your plan"]


class TestRecogniseDialog:
    def test_boxed_dialog_pointer_on_target(self) -> None:
        dialog = _mod.recognise_rate_limit_dialog(_dialog(_STANDARD))
        assert dialog is not None
        assert dialog.options == tuple(_STANDARD)
        assert dialog.selected == 0
        assert dialog.target == 0

    def test_unboxed_dialog_is_recognised(self) -> None:
        dialog = _mod.recognise_rate_limit_dialog(_dialog(_STANDARD, boxed=False))
        assert dialog is not None
        assert dialog.target == 0

    def test_flag_moved_target_row_is_found_by_label(self) -> None:
        options = ["Upgrade your plan", "Add funds to continue with usage credits", _TARGET]
        dialog = _mod.recognise_rate_limit_dialog(_dialog(options, pointer=0))
        assert dialog is not None
        assert dialog.target == 2
        assert dialog.selected == 0

    def test_trailing_checkmark_on_a_row_is_tolerated(self) -> None:
        screen = _dialog(_STANDARD).replace(f"1. {_TARGET}", f"1. {_TARGET} ✔")
        dialog = _mod.recognise_rate_limit_dialog(screen)
        assert dialog is not None
        assert dialog.target == 0

    def test_no_footer_is_tolerated(self) -> None:
        assert _mod.recognise_rate_limit_dialog(_dialog(_STANDARD, footer=())) is not None

    def test_signature_changes_with_the_pointer(self) -> None:
        first = _mod.recognise_rate_limit_dialog(_dialog(_STANDARD, pointer=0))
        second = _mod.recognise_rate_limit_dialog(_dialog(_STANDARD, pointer=1))
        assert first is not None and second is not None
        assert first.signature != second.signature


class TestRecogniseDialogNegatives:
    def test_plain_stop_label_is_not_recognised(self) -> None:
        options = ["Stop", "Upgrade your plan"]
        assert _mod.recognise_rate_limit_dialog(_dialog(options)) is None

    def test_truncated_label_is_not_recognised(self) -> None:
        options = ["Stop and wait for limit to re…", "Upgrade your plan"]
        assert _mod.recognise_rate_limit_dialog(_dialog(options)) is None

    def test_trial_expired_dialog_is_not_recognised(self) -> None:
        options = ["Upgrade your plan", "Wait for limit to reset"]
        assert _mod.recognise_rate_limit_dialog(_dialog(options)) is None

    def test_title_only_is_not_recognised(self) -> None:
        screen = "\n".join([*_TRANSCRIPT, "What do you want to do?"]) + "\n"
        assert _mod.recognise_rate_limit_dialog(screen) is None

    def test_two_pointers_are_not_recognised(self) -> None:
        screen = _dialog(_STANDARD).replace("  2. Wait", f"{_POINTER} 2. Wait")
        assert _mod.recognise_rate_limit_dialog(screen) is None

    def test_no_pointer_is_not_recognised(self) -> None:
        screen = _dialog(_STANDARD).replace(f"{_POINTER} 1. {_TARGET}", f"  1. {_TARGET}")
        assert _mod.recognise_rate_limit_dialog(screen) is None

    def test_duplicate_target_rows_are_not_recognised(self) -> None:
        assert _mod.recognise_rate_limit_dialog(_dialog([_TARGET, _TARGET])) is None

    def test_misnumbered_rows_are_not_recognised(self) -> None:
        screen = _dialog(_STANDARD).replace("  2. Wait", "  5. Wait")
        assert _mod.recognise_rate_limit_dialog(screen) is None

    def test_quoted_dialog_above_a_visible_composer_is_not_recognised(self) -> None:
        screen = _dialog(_STANDARD, footer=()) + "\n".join(
            ["", "─" * 60, "> ", "─" * 60, "  ? for shortcuts"]
        )
        assert _mod.recognise_rate_limit_dialog(screen) is None

    def test_dialog_scrolled_up_by_later_output_is_not_recognised(self) -> None:
        later = [f"● line {n}" for n in range(8)]
        screen = _dialog(_STANDARD) + "\n".join(later) + "\n"
        assert _mod.recognise_rate_limit_dialog(screen) is None

    def test_prose_mention_is_not_recognised(self) -> None:
        screen = (
            "\n".join(
                [
                    "● The dialog asks What do you want to do? and offers",
                    f"  {_TARGET} as the first row.",
                    "",
                    "> ",
                ]
            )
            + "\n"
        )
        assert _mod.recognise_rate_limit_dialog(screen) is None

    def test_empty_screen_is_not_recognised(self) -> None:
        assert _mod.recognise_rate_limit_dialog("") is None

    def test_near_miss_flags_the_label_without_a_dialog(self) -> None:
        options = ["Stop and wait for limit to re…", "Upgrade your plan"]
        assert _mod.rate_limit_dialog_near_miss(_dialog(options))
        assert _mod.rate_limit_dialog_near_miss(_dialog(_STANDARD).replace(_POINTER, " "))
        assert not _mod.rate_limit_dialog_near_miss("● nothing to see\n> \n")


class TestParseReset:
    def test_time_only_today(self) -> None:
        reset = _mod.parse_rate_limit_reset(_dialog(_STANDARD), _NOW)
        assert reset == datetime(2026, 11, 23, 15, 0, tzinfo=_LONDON).timestamp()

    def test_time_with_minutes(self) -> None:
        screen = _dialog(_STANDARD).replace("resets 3pm", "resets 3:30pm")
        reset = _mod.parse_rate_limit_reset(screen, _NOW)
        assert reset == datetime(2026, 11, 23, 15, 30, tzinfo=_LONDON).timestamp()

    def test_time_only_earlier_than_now_means_tomorrow(self) -> None:
        screen = _dialog(_STANDARD).replace("resets 3pm", "resets 8am")
        reset = _mod.parse_rate_limit_reset(screen, _NOW)
        assert reset == datetime(2026, 11, 24, 8, 0, tzinfo=_LONDON).timestamp()

    def test_date_and_time(self) -> None:
        screen = _dialog(_STANDARD).replace("resets 3pm", "resets Nov 29, 3pm")
        reset = _mod.parse_rate_limit_reset(screen, _NOW)
        assert reset == datetime(2026, 11, 29, 15, 0, tzinfo=_LONDON).timestamp()

    def test_date_with_year(self) -> None:
        screen = _dialog(_STANDARD).replace("resets 3pm", "resets Jan 2, 2027, 3:30pm")
        reset = _mod.parse_rate_limit_reset(screen, _NOW)
        assert reset == datetime(2027, 1, 2, 15, 30, tzinfo=_LONDON).timestamp()

    def test_date_without_year_past_new_year_rolls_forward(self) -> None:
        now = datetime(2026, 12, 30, 10, 0, tzinfo=_LONDON).timestamp()
        screen = _dialog(_STANDARD).replace("resets 3pm", "resets Jan 2, 3pm")
        reset = _mod.parse_rate_limit_reset(screen, now)
        assert reset == datetime(2027, 1, 2, 15, 0, tzinfo=_LONDON).timestamp()

    def test_other_timezone(self) -> None:
        screen = _dialog(_STANDARD).replace("(Europe/London)", "(America/New_York)")
        reset = _mod.parse_rate_limit_reset(screen, _NOW)
        new_york = ZoneInfo("America/New_York")
        # 10:00 London is 05:00 New York, so 3pm New York is later today.
        assert reset == datetime(2026, 11, 23, 15, 0, tzinfo=new_york).timestamp()

    def test_unknown_timezone_is_refused(self) -> None:
        screen = _dialog(_STANDARD).replace("(Europe/London)", "(Mars/Olympus)")
        assert _mod.parse_rate_limit_reset(screen, _NOW) is None

    def test_no_limit_message_is_none(self) -> None:
        assert _mod.parse_rate_limit_reset("● hello\n> \n", _NOW) is None

    def test_garbled_time_is_none(self) -> None:
        screen = _dialog(_STANDARD).replace("resets 3pm", "resets soon")
        assert _mod.parse_rate_limit_reset(screen, _NOW) is None

    def test_latest_message_wins(self) -> None:
        screen = _dialog(_STANDARD).replace(
            "● Running", "  ⎿  You've hit your weekly limit · resets 9am (Europe/London)\n● Running"
        )
        reset = _mod.parse_rate_limit_reset(screen, _NOW)
        assert reset == datetime(2026, 11, 23, 15, 0, tzinfo=_LONDON).timestamp()


class TestComposerText:
    def test_empty_composer(self) -> None:
        screen = "● done\n" + "─" * 40 + "\n> \n" + "─" * 40 + "\n  ? for shortcuts\n"
        assert _mod.rate_limit_composer_text(screen) == ""

    def test_prefilled_composer(self) -> None:
        screen = "● done\n" + "─" * 40 + "\n> continue\n" + "─" * 40 + "\n"
        assert _mod.rate_limit_composer_text(screen) == "continue"

    def test_no_composer_visible(self) -> None:
        assert _mod.rate_limit_composer_text("● done\n") is None


def test_screen_dump_survives_the_worker_json() -> None:
    facts = _mod.TickFacts(
        now_wall=_NOW,
        idle=True,
        input_line_empty=True,
        human_compact_submitted=False,
        work_idle=True,
        screen_dump="row one\nrow two",
    )
    assert _mod._facts_from_json(_mod._facts_to_json(facts)).screen_dump == "row one\nrow two"


_CHILD = 4242
_SETTLED = 10.0


def _dialog_facts(
    dump: str,
    *,
    now: float = _NOW,
    quiet: float = _SETTLED,
    child_pid: int | None = _CHILD,
    raw: bytes = b"",
    **overrides: Any,
) -> Any:
    fields: dict[str, Any] = {
        "now_wall": now,
        "idle": True,
        "input_line_empty": True,
        "human_compact_submitted": False,
        "work_idle": True,
        "output_quiet_seconds": quiet,
        "child_pid": child_pid,
        "screen_dump": dump,
        "human_raw_input": base64.b64encode(raw).decode("ascii"),
    }
    fields.update(overrides)
    return _mod.TickFacts(**fields)


def _write_red_sidecar(sidecar_dir: Path, *, now: float = _NOW) -> None:
    """A context reading that, absent the dialog, makes the supervisor compact."""
    (sidecar_dir / "fg.json").write_text(
        json.dumps(
            {
                "red": True,
                "critical": False,
                "compact_urgent": True,
                "tier": "urgent",
                "pct": 80.0,
                "session_id": "fg",
                "ts": now,
                "seq": 1,
                "writer_pid": 1,
                "compacting": False,
            }
        ),
        encoding="utf-8",
    )


def _state_path(sidecar_dir: Path, child_pid: int = _CHILD) -> Path:
    path = _mod._rate_limit_state_path(sidecar_dir.parent, child_pid)
    assert path is not None
    return Path(path)


# Every fake child "started" at the epoch with start ticks derived from its pid,
# unless a test says otherwise; a missing entry reads as an unreadable /proc.
@pytest.fixture(autouse=True)
def _child_starts(monkeypatch: pytest.MonkeyPatch) -> dict[int, tuple[int, float]]:
    starts: dict[int, tuple[int, float]] = {_CHILD: (_CHILD * 100, 0.0), 7: (700, 0.0)}
    monkeypatch.setattr(_mod, "_rate_limit_child_start", lambda pid: starts.get(pid), raising=False)
    # The worker has seen a dialog-free screen since the human's last key, for
    # each fake child; a child not in this map is a fresh worker's (keys assumed).
    monkeypatch.setattr(
        _mod,
        "_RATE_LIMIT_KEYS_SINCE_DUMP",
        {
            f"supervise-rate-limit-dialog.{pid}-{ticks}.json": False
            for pid, (ticks, _) in starts.items()
        },
        raising=False,
    )
    return starts


@pytest.fixture
def sidecar_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "context-sidecar"
    directory.mkdir()
    return directory


@pytest.fixture
def machine() -> Any:
    return _mod.CompactStateMachine(_mod.CompactPolicy())


def _tick(sidecar_dir: Path, machine: Any, facts: Any, *, dry_run: bool = False) -> Any:
    policy = _mod.CompactPolicy()
    return _mod.decide_once(
        machine,
        sidecar_dir=sidecar_dir,
        facts=facts,
        dry_run=dry_run,
        freshness_seconds=policy.freshness_seconds,
    )


_ON_TARGET = _dialog(_STANDARD, pointer=0)
_KEY = "would-rate-limit-key"


class TestDialogKeys:
    def test_enter_only_on_the_second_stable_tick(self, sidecar_dir: Path, machine: Any) -> None:
        first = _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET))
        assert first.payload is None
        assert first.decision_value == "noop"
        second = _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + 1))
        assert second.decision_value == _KEY
        assert second.payload == "\r"
        assert second.submit is False

    def test_arrow_never_enter_when_pointer_is_off_target(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        options = ["Upgrade your plan", "Add funds", _TARGET]
        for offset in range(2):
            outcome = _tick(
                sidecar_dir, machine, _dialog_facts(_dialog(options), now=_NOW + offset)
            )
            assert outcome.payload == "\x1b[B"
        above = _dialog([_TARGET, "Upgrade your plan"], pointer=1)
        outcome = _tick(sidecar_dir, machine, _dialog_facts(above, now=_NOW + 2))
        assert outcome.payload == "\x1b[A"

    def test_unsettled_screen_is_a_noop_that_suppresses_other_families(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        _write_red_sidecar(sidecar_dir)
        outcome = _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, quiet=1.0))
        assert outcome.payload is None
        assert outcome.decision_value == "noop"
        assert "rate-limit dialog" in (outcome.noop_reason_log or "")

    def test_dialog_without_a_red_sidecar_still_types_nothing_else(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        _write_red_sidecar(sidecar_dir)
        outcome = _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET))
        assert outcome.decision_value == "noop"

    def test_dry_run_types_nothing(self, sidecar_dir: Path, machine: Any) -> None:
        outcomes = [
            _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + offset), dry_run=True)
            for offset in range(3)
        ]
        assert all(outcome.payload is None for outcome in outcomes)
        assert "would press" in (outcomes[-1].noop_reason_log or "")

    def test_env_off_leaves_the_dialog_alone(
        self, sidecar_dir: Path, machine: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CCY_RATE_LIMIT_DIALOG", "off")
        for offset in range(2):
            outcome = _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + offset))
            assert outcome.decision_value != _KEY
        assert not _state_path(sidecar_dir).exists()

    def test_legacy_empty_dump_touches_no_state(self, sidecar_dir: Path, machine: Any) -> None:
        _tick(sidecar_dir, machine, _dialog_facts(""))
        assert not _state_path(sidecar_dir).exists()

    def test_no_child_pid_means_off(self, sidecar_dir: Path, machine: Any) -> None:
        for offset in range(2):
            outcome = _tick(
                sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + offset, child_pid=None)
            )
            assert outcome.decision_value != _KEY
        assert list(sidecar_dir.parent.glob("supervise-rate-limit-dialog.*")) == []

    def test_another_child_does_not_see_the_state(self, sidecar_dir: Path, machine: Any) -> None:
        _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET))
        other = _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + 1, child_pid=7))
        assert other.payload is None
        assert _state_path(sidecar_dir).exists()
        assert _state_path(sidecar_dir, 7).exists()


class TestOncePerWindow:
    def _answer(self, sidecar_dir: Path, machine: Any) -> None:
        _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET))
        assert _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + 1)).payload == "\r"

    def test_dialog_back_after_going_away_is_left_alone(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        self._answer(sidecar_dir, machine)
        _tick(sidecar_dir, machine, _dialog_facts(_prompt_screen(""), now=_NOW + 5))
        outcomes = [
            _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + offset))
            for offset in range(6, 9)
        ]
        assert all(outcome.payload is None for outcome in outcomes)
        assert "already answered" in (outcomes[-1].noop_reason_log or "")

    def test_lost_enter_is_pressed_again(self, sidecar_dir: Path, machine: Any) -> None:
        self._answer(sidecar_dir, machine)
        payloads = [
            _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + offset)).payload
            for offset in range(2, 4)
        ]
        assert "\r" in payloads

    def test_occurrence_key_cap(self, sidecar_dir: Path, machine: Any) -> None:
        stuck = _dialog(["Upgrade your plan", _TARGET], pointer=0)
        payloads = [
            _tick(sidecar_dir, machine, _dialog_facts(stuck, now=_NOW + offset)).payload
            for offset in range(10)
        ]
        assert payloads.count("\x1b[B") == 6
        assert payloads[-1] is None


class TestHumanAndNearMiss:
    def test_human_typing_abandons_the_window(self, sidecar_dir: Path, machine: Any) -> None:
        _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET))
        typed = _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + 1, raw=b"\x1b[B"))
        assert typed.payload is None
        later = _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + 2))
        assert later.payload is None

    def test_focus_reports_are_not_typing(self, sidecar_dir: Path, machine: Any) -> None:
        _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET))
        outcome = _tick(
            sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + 1, raw=b"\x1b[O\x1b[I")
        )
        assert outcome.payload == "\r"

    def test_near_miss_screen_is_saved(self, sidecar_dir: Path, machine: Any) -> None:
        screen = "What do you want to do?\n  1. Stop and wait for limit to re…\n" + _prompt_screen(
            ""
        )
        outcome = _tick(sidecar_dir, machine, _dialog_facts(screen))
        assert outcome.decision_value != _KEY
        saved = sidecar_dir.parent / "supervise-rate-limit-unrecognised.txt"
        assert saved.read_text(encoding="utf-8").endswith(screen[-200:])


def _prompt_screen(text: str) -> str:
    """The main prompt after the dialog closed, with ``text`` in the input box."""
    rule = "─" * 40
    return "\n".join([*_TRANSCRIPT, rule, f"> {text}".rstrip(), rule, "  ? for shortcuts"]) + "\n"


def test_legacy_host_json_has_no_dump() -> None:
    line = json.dumps(
        {
            "now_wall": _NOW,
            "idle": True,
            "input_line_empty": True,
            "human_compact_submitted": False,
            "work_idle": True,
        }
    )
    assert _mod._facts_from_json(line).screen_dump == ""


# ── Unit 2b: the late `continue` after the reset ─────────────────────────────

# The fixtures' limit resets at 3pm Europe/London on the same day as _NOW.
_RESET = datetime(2026, 11, 23, 15, 0, tzinfo=_LONDON).timestamp()
_AFTER = _RESET + 180.0  # past the resume grace
_CONTINUE = "would-rate-limit-continue"
_BACKSPACES = "\x7f" * len("continue")
_QUIET_SINCE_ANSWER = _NOW + 5.0  # the last output: the dialog closing


def _resume_facts(text: str, *, now: float = _AFTER, **overrides: Any) -> Any:
    """A settled prompt screen after the answer, no output since the dialog closed."""
    overrides.setdefault("quiet", now - _QUIET_SINCE_ANSWER)
    return _dialog_facts(_prompt_screen(text), now=now, **overrides)


def _answer_and_close(sidecar_dir: Path, machine: Any) -> None:
    """Answer the dialog, then see it gone (the occurrence closes)."""
    _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET))
    assert _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + 1)).payload == "\r"
    closed = _tick(sidecar_dir, machine, _dialog_facts(_prompt_screen("continue"), now=_NOW + 5))
    assert closed.payload is None


def _resume(sidecar_dir: Path, machine: Any, facts: Any, *, dry_run: bool = False) -> Any:
    """A tick with a fresh green context reading, so only the resume speaks in the log."""
    (sidecar_dir / "fg.json").write_text(
        json.dumps(
            {
                "red": False,
                "critical": False,
                "compact_urgent": False,
                "tier": "",
                "pct": 30.0,
                "session_id": "fg",
                "ts": facts.now_wall,
                "seq": 1,
                "writer_pid": 1,
                "compacting": False,
            }
        ),
        encoding="utf-8",
    )
    return _tick(sidecar_dir, machine, facts, dry_run=dry_run)


def _phase(sidecar_dir: Path) -> Any:
    return json.loads(_state_path(sidecar_dir).read_text(encoding="utf-8"))["phase"]


class TestResumeAfterReset:
    def test_clear_then_continue_then_nothing(self, sidecar_dir: Path, machine: Any) -> None:
        _answer_and_close(sidecar_dir, machine)
        clear = _resume(sidecar_dir, machine, _resume_facts("continue"))
        assert clear.decision_value == _KEY
        assert clear.payload == _BACKSPACES
        assert clear.submit is False
        # Our own backspaces redraw the box: the next tick sees fresh output.
        sent = _resume(sidecar_dir, machine, _resume_facts("", now=_AFTER + 2, quiet=1.5))
        assert sent.decision_value == _CONTINUE
        assert sent.submit is True
        assert sent.payload is not None
        assert sent.payload.endswith(" continue")
        assert "[ccy-supervisor " in sent.payload
        assert _phase(sidecar_dir) == "done"
        for offset in range(4, 40, 5):
            later = _resume(sidecar_dir, machine, _resume_facts("", now=_AFTER + offset))
            assert later.decision_value not in (_KEY, _CONTINUE)

    def test_empty_box_goes_straight_to_continue(self, sidecar_dir: Path, machine: Any) -> None:
        _answer_and_close(sidecar_dir, machine)
        sent = _resume(sidecar_dir, machine, _resume_facts(""))
        assert sent.decision_value == _CONTINUE

    def test_nothing_before_the_reset(self, sidecar_dir: Path, machine: Any) -> None:
        _answer_and_close(sidecar_dir, machine)
        outcomes = [
            _resume(sidecar_dir, machine, _resume_facts("continue", now=now))
            for now in (_NOW + 60, _RESET - 1, _RESET + 60)
        ]
        assert all(outcome.decision_value not in (_KEY, _CONTINUE) for outcome in outcomes)
        assert "waiting for the limit to reset" in (outcomes[-1].noop_reason_log or "")

    def test_redraw_after_the_reset_then_quiet_still_resumes(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        # An idle status-line redraw after the reset leaves the pre-fill in the
        # box: nobody submitted anything, so the resume goes on once settled.
        _answer_and_close(sidecar_dir, machine)
        clear = _resume(sidecar_dir, machine, _resume_facts("continue", quiet=30.0))
        assert clear.payload == _BACKSPACES
        sent = _resume(sidecar_dir, machine, _resume_facts("", now=_AFTER + 2, quiet=1.5))
        assert sent.decision_value == _CONTINUE
        later = [
            _resume(sidecar_dir, machine, _resume_facts("", now=_AFTER + offset, quiet=3.0))
            for offset in (5, 30, 900)
        ]
        assert all(outcome.decision_value not in (_KEY, _CONTINUE) for outcome in later)

    def test_output_after_the_reset_waits_for_a_settled_screen(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        _answer_and_close(sidecar_dir, machine)
        outcome = _resume(sidecar_dir, machine, _resume_facts("continue", quiet=1.0))
        assert outcome.payload is None
        assert _phase(sidecar_dir) == "answered"

    def test_empty_box_after_output_never_continues_and_abandons_at_the_deadline(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        # Output then an empty box: the human may already have continued.
        _answer_and_close(sidecar_dir, machine)
        waiting = [
            _resume(sidecar_dir, machine, _resume_facts("", now=_AFTER + offset, quiet=30.0))
            for offset in (0, 60, 300)
        ]
        assert all(outcome.payload is None for outcome in waiting)
        assert _phase(sidecar_dir) == "answered"
        deadline = _AFTER + _mod._RATE_LIMIT_RECHECK_SECONDS
        late = _resume(sidecar_dir, machine, _resume_facts("", now=deadline, quiet=30.0))
        assert late.payload is None
        assert "output after the reset" in (late.noop_reason_log or "")
        assert _phase(sidecar_dir) == "abandoned"

    def test_prefill_after_the_deadline_abandons(self, sidecar_dir: Path, machine: Any) -> None:
        _answer_and_close(sidecar_dir, machine)
        first = _resume(sidecar_dir, machine, _resume_facts("continue", quiet=1.0))
        assert first.payload is None
        deadline = _AFTER + _mod._RATE_LIMIT_RECHECK_SECONDS
        late = _resume(sidecar_dir, machine, _resume_facts("continue", now=deadline, quiet=30.0))
        assert late.payload is None
        assert _phase(sidecar_dir) == "abandoned"

    def test_no_parsed_reset_never_continues(self, sidecar_dir: Path, machine: Any) -> None:
        unparsed = _ON_TARGET.replace("resets 3pm (Europe/London)", "resets soon")
        _tick(sidecar_dir, machine, _dialog_facts(unparsed))
        assert _tick(sidecar_dir, machine, _dialog_facts(unparsed, now=_NOW + 1)).payload == "\r"
        _tick(sidecar_dir, machine, _dialog_facts(_prompt_screen(""), now=_NOW + 5))
        outcome = _resume(sidecar_dir, machine, _resume_facts(""))
        assert outcome.decision_value not in (_KEY, _CONTINUE)
        assert _phase(sidecar_dir) == "done"

    def test_stored_reset_is_used_not_a_reparse(self, sidecar_dir: Path, machine: Any) -> None:
        # Past 3pm a re-parse of "resets 3pm" would mean tomorrow; the stored
        # window says today, so the continue goes now.
        _answer_and_close(sidecar_dir, machine)
        late = _RESET + 3600.0
        sent = _resume(sidecar_dir, machine, _resume_facts("", now=late))
        assert sent.decision_value == _CONTINUE

    def test_box_still_prefilled_after_the_clear_attempts_abandons(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        _answer_and_close(sidecar_dir, machine)
        first = _resume(sidecar_dir, machine, _resume_facts("continue")).payload
        payloads = [first] + [
            _resume(
                sidecar_dir, machine, _resume_facts("continue", now=_AFTER + i, quiet=1.0)
            ).payload
            for i in range(1, 4)
        ]
        assert payloads.count(_BACKSPACES) == 2
        assert _phase(sidecar_dir) == "abandoned"

    def test_foreign_text_in_the_box_abandons(self, sidecar_dir: Path, machine: Any) -> None:
        _answer_and_close(sidecar_dir, machine)
        outcome = _resume(sidecar_dir, machine, _resume_facts("half a thought"))
        assert outcome.payload is None
        assert _phase(sidecar_dir) == "abandoned"

    def test_no_visible_box_waits(self, sidecar_dir: Path, machine: Any) -> None:
        _answer_and_close(sidecar_dir, machine)
        outcome = _tick(
            sidecar_dir,
            machine,
            _dialog_facts("just transcript\n", now=_AFTER, quiet=_AFTER - _QUIET_SINCE_ANSWER),
        )
        assert outcome.payload is None
        assert _phase(sidecar_dir) == "answered"

    def test_human_typing_blocks_the_resume(self, sidecar_dir: Path, machine: Any) -> None:
        _answer_and_close(sidecar_dir, machine)
        outcome = _resume(sidecar_dir, machine, _resume_facts("", idle=False))
        assert outcome.payload is None
        assert _phase(sidecar_dir) == "answered"

    def test_busy_footer_blocks_the_resume(self, sidecar_dir: Path, machine: Any) -> None:
        _answer_and_close(sidecar_dir, machine)
        busy = _prompt_screen("") + "  2 background tasks\n"
        outcome = _tick(
            sidecar_dir,
            machine,
            _dialog_facts(busy, now=_AFTER, quiet=_AFTER - _QUIET_SINCE_ANSWER),
        )
        assert outcome.payload is None

    def test_dry_run_types_nothing_and_finishes(self, sidecar_dir: Path, machine: Any) -> None:
        _answer_and_close(sidecar_dir, machine)
        outcome = _resume(sidecar_dir, machine, _resume_facts(""), dry_run=True)
        assert outcome.payload is None
        assert "would send continue (dry-run)" in (outcome.noop_reason_log or "")
        assert _phase(sidecar_dir) == "done"


_GATE_SESSION = "fg"


class TestResumeGates:
    def test_control_without_a_gate_continues(self, sidecar_dir: Path, machine: Any) -> None:
        _answer_and_close(sidecar_dir, machine)
        sent = _resume(sidecar_dir, machine, _resume_facts(""))
        assert sent.decision_value == _CONTINUE

    def test_no_continue_under_a_usage_pause(self, sidecar_dir: Path, machine: Any) -> None:
        from claude_code_hooks_daemon.utils import usage_pause
        from claude_code_hooks_daemon.utils.usage_pause import UsagePause

        _answer_and_close(sidecar_dir, machine)
        usage_pause.write_usage_pause(
            sidecar_dir.parent,
            UsagePause(
                session_id=_GATE_SESSION,
                paused_at=_AFTER - 60.0,
                resume_at=_AFTER + 3600.0,
                window=usage_pause.WINDOW_FIVE_HOUR,
                used_percentage=93.0,
                ceiling=90.0,
                reason="five_hour window at 93% (ceiling 90%)",
            ),
        )
        assert _mod.load_usage_pause(sidecar_dir, now=_AFTER, own_sessions=None) is not None
        outcome = _resume(sidecar_dir, machine, _resume_facts(""))
        assert outcome.decision_value != _CONTINUE
        assert outcome.payload is None or "continue" not in outcome.payload.split()[-1:]

    def test_no_continue_under_blocked(self, sidecar_dir: Path, machine: Any) -> None:
        from claude_code_hooks_daemon.core.session_mode_registry import SessionModeRegistry
        from claude_code_hooks_daemon.utils.session_modes import declared_blocked_entry

        _answer_and_close(sidecar_dir, machine)
        SessionModeRegistry(sidecar_dir, clock=lambda: _AFTER).enter(
            declared_blocked_entry(_GATE_SESSION, entered_at=_AFTER - 60.0)
        )
        assert _mod.load_session_modes(sidecar_dir, now=_AFTER, own_sessions=None).gate_closed
        outcome = _resume(sidecar_dir, machine, _resume_facts(""))
        assert outcome.decision_value != _CONTINUE
        assert outcome.payload is None


# ── Unit 3: the host sends the bottom of the rendered screen ─────────────────


def _dump_stub(tmp_path: Path) -> Path:
    """A hooks-screen stand-in: 50 numbered rows for --dump, counting its runs."""
    import stat

    counter = tmp_path / "runs"
    script = tmp_path / "hooks-screen-stub"
    script.write_text(
        "#!/bin/bash\n"
        "cat > /dev/null\n"
        f"echo run >> {counter}\n"
        'if [[ " $* " == *" --dump "* ]]; then\n'
        '  for i in $(seq 1 50); do echo "row $i"; done\n'
        "else\n"
        "  echo main\n"
        "fi\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _runs(tmp_path: Path) -> int:
    counter = tmp_path / "runs"
    return len(counter.read_text().splitlines()) if counter.exists() else 0


class TestHostScreenDump:
    def _check(self, binary: Path | None, **kw: Any) -> tuple[Any, Any]:
        buffer = _mod.ScreenBuffer()
        buffer.append(b"frame one")
        check = _mod.ScreenFocusCheck(buffer, binary=binary, size_fn=lambda: (100, 30), **kw)
        return check, buffer

    def test_bottom_forty_rows(self, tmp_path: Path) -> None:
        check, _ = self._check(_dump_stub(tmp_path))
        dump = check.recent_dump()
        rows = dump.splitlines()
        assert len(rows) == 40
        assert rows[0] == "row 11"
        assert rows[-1] == "row 50"

    def test_cached_until_new_output(self, tmp_path: Path) -> None:
        check, buffer = self._check(_dump_stub(tmp_path))
        check.recent_dump()
        check.recent_dump()
        assert _runs(tmp_path) == 1
        buffer.append(b"frame two")
        check.recent_dump()
        assert _runs(tmp_path) == 2

    def test_missing_binary_gives_empty(self) -> None:
        check, _ = self._check(None)
        assert check.recent_dump() == ""

    def test_missing_binary_is_resolved_again_at_most_once_a_minute(self, tmp_path: Path) -> None:
        clock = [1000.0]
        calls: list[float] = []
        stub = _dump_stub(tmp_path)

        def resolve() -> Path | None:
            calls.append(clock[0])
            return stub if clock[0] >= 1070.0 else None

        check, buffer = self._check(None, clock=lambda: clock[0], resolve_binary=resolve)
        assert check.recent_dump() == ""
        clock[0] = 1030.0
        buffer.append(b"x")
        assert check.recent_dump() == ""
        assert calls == []
        clock[0] = 1061.0
        buffer.append(b"y")
        assert check.recent_dump() == ""
        assert calls == [1061.0]
        clock[0] = 1125.0
        buffer.append(b"z")
        assert check.recent_dump().endswith("row 50")
        assert calls == [1061.0, 1125.0]

    def test_sent_only_after_two_quiet_seconds(self, tmp_path: Path) -> None:
        check, _ = self._check(_dump_stub(tmp_path))
        assert _mod._rate_limit_screen_dump(check, output_quiet_seconds=1.9) == ""
        assert _runs(tmp_path) == 0
        assert _mod._rate_limit_screen_dump(check, output_quiet_seconds=2.0).endswith("row 50")

    def test_not_sent_without_a_check_or_with_the_switch_off(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert _mod._rate_limit_screen_dump(None, output_quiet_seconds=10.0) == ""
        check, _ = self._check(_dump_stub(tmp_path))
        monkeypatch.setenv("CCY_RATE_LIMIT_DIALOG", "off")
        assert _mod._rate_limit_screen_dump(check, output_quiet_seconds=10.0) == ""
        assert _runs(tmp_path) == 0


# ── Open risk 1: nothing else is typed onto Claude Code's pre-filled box ─────


def _prefill_state(status_dir: Path, *, phase: str, reset: float) -> None:
    """A closed occurrence for this child, in ``phase``, resetting at ``reset``."""
    state = _mod._new_rate_limit_window(reset, reset - 3600.0)
    state.update(phase=phase)
    _mod._save_rate_limit_state(_mod._rate_limit_state_path(status_dir, _CHILD), state)


class TestPrefillHold:
    """A restore or usage-pause compact must wait while ``continue`` sits in the box."""

    def _ready(self, tmp_path: Path) -> tuple[Path, Any, float]:
        from claude_code_hooks_daemon.utils.session_signal_paths import SIGNAL_SUBDIR
        from tests.unit.supervise import test_model_restore as restore

        sidecar_dir = tmp_path / SIGNAL_SUBDIR
        machine, later = restore._restore_ready_machine(sidecar_dir)
        return sidecar_dir, machine, later

    def _facts(self, later: float, dump: str) -> Any:
        return _mod.TickFacts(
            now_wall=later,
            idle=True,
            input_line_empty=True,
            human_compact_submitted=False,
            work_idle=True,
            child_pid=_CHILD,
            screen_dump=dump,
            output_quiet_seconds=_SETTLED,
        )

    def test_control_restore_fires_without_rate_limit_state(self, tmp_path: Path) -> None:
        sidecar_dir, machine, later = self._ready(tmp_path)
        outcome = _tick(sidecar_dir, machine, self._facts(later, _prompt_screen("")))
        assert outcome.decision_value == "would-model"

    @pytest.mark.parametrize("phase", ["answered", "cleared"])
    def test_restore_held_while_the_continue_is_pending(self, tmp_path: Path, phase: str) -> None:
        sidecar_dir, machine, later = self._ready(tmp_path)
        _prefill_state(tmp_path, phase=phase, reset=later + 3600.0)
        for dump in (_prompt_screen("continue"), ""):
            outcome = _tick(sidecar_dir, machine, self._facts(later, dump))
            assert outcome.payload is None
            assert outcome.decision_value != "would-model"

    @pytest.mark.parametrize("phase", ["abandoned", "done"])
    def test_restore_held_while_the_prefill_is_left_in_the_box(
        self, tmp_path: Path, phase: str
    ) -> None:
        sidecar_dir, machine, later = self._ready(tmp_path)
        _prefill_state(tmp_path, phase=phase, reset=later - 600.0)
        outcome = _tick(sidecar_dir, machine, self._facts(later, _prompt_screen("continue")))
        assert outcome.payload is None

    def test_restore_held_while_the_answered_dialog_is_still_closing(self, tmp_path: Path) -> None:
        # The Enter sets `answered` with the occurrence still open; the closing
        # redraw sends an empty dump, and the pre-fill is already there.
        sidecar_dir, machine, later = self._ready(tmp_path)
        state = _mod._new_rate_limit_window(later + 3600.0, later - 5.0)
        state.update(phase="answered", occurrence_open=True)
        _mod._save_rate_limit_state(_mod._rate_limit_state_path(tmp_path, _CHILD), state)
        outcome = _tick(sidecar_dir, machine, self._facts(later, ""))
        assert outcome.payload is None

    def test_transcript_continue_above_an_empty_box_does_not_hold(self, tmp_path: Path) -> None:
        sidecar_dir, machine, later = self._ready(tmp_path)
        _prefill_state(tmp_path, phase="abandoned", reset=later - 600.0)
        rule = "─" * 40
        screen = "\n".join([rule, "> continue", "", "● Resuming.", ""]) + _prompt_screen("")
        outcome = _tick(sidecar_dir, machine, self._facts(later, screen))
        assert outcome.decision_value == "would-model"

    def test_restore_fires_once_the_continue_was_sent(self, tmp_path: Path) -> None:
        sidecar_dir, machine, later = self._ready(tmp_path)
        _prefill_state(tmp_path, phase="done", reset=later - 600.0)
        outcome = _tick(sidecar_dir, machine, self._facts(later, _prompt_screen("")))
        assert outcome.decision_value == "would-model"

    def test_usage_pause_compact_held_while_the_continue_is_pending(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.utils import usage_pause
        from claude_code_hooks_daemon.utils.usage_pause import UsagePause
        from tests.unit.supervise import test_model_restore as restore

        sidecar_dir, machine, later = self._ready(tmp_path)
        usage_pause.write_usage_pause(
            tmp_path,
            UsagePause(
                session_id=restore._SESSION,
                paused_at=later - 60.0,
                resume_at=later + 3600.0,
                window=usage_pause.WINDOW_FIVE_HOUR,
                used_percentage=93.0,
                ceiling=90.0,
                reason="five_hour window at 93% (ceiling 90%)",
            ),
        )
        assert _mod.load_usage_pause(sidecar_dir, now=later, own_sessions=None) is not None
        control = _tick(
            sidecar_dir,
            _mod.CompactStateMachine(_mod.CompactPolicy()),
            self._facts(later, _prompt_screen("")),
        )
        assert control.payload is not None
        assert control.payload.startswith("/compact")
        _prefill_state(tmp_path, phase="answered", reset=later + 3600.0)
        held = _tick(sidecar_dir, machine, self._facts(later, _prompt_screen("continue")))
        assert held.payload is None


# ── Review I1: the state belongs to one Claude child, not to a reused pid ─────


class TestStateScopedToTheChild:
    def test_reused_pid_with_another_start_time_does_not_inherit_the_state(
        self, sidecar_dir: Path, machine: Any, _child_starts: dict[int, tuple[int, float]]
    ) -> None:
        # Session A answers at 10:00; the container restarts and session B's
        # Claude child gets the same pid with a different start time.
        _answer_and_close(sidecar_dir, machine)
        _child_starts[_CHILD] = (999_999, _NOW + 60.0)
        facts = _resume_facts("continue", now=_NOW + 600.0)
        assert not _mod._rate_limit_prefill_blocks(facts, sidecar_dir.parent)
        resumed = _resume(sidecar_dir, machine, _resume_facts("continue"))
        assert resumed.decision_value not in (_KEY, _CONTINUE)

    def test_same_pid_and_ticks_but_state_older_than_the_session_is_ignored(
        self, sidecar_dir: Path, machine: Any, _child_starts: dict[int, tuple[int, float]]
    ) -> None:
        # A fresh pid namespace after a host reboot can repeat both the pid and
        # the start ticks; the state's own time then predates the session.
        _answer_and_close(sidecar_dir, machine)
        ticks, _ = _child_starts[_CHILD]
        _child_starts[_CHILD] = (ticks, _NOW + 60.0)
        facts = _resume_facts("continue", now=_NOW + 600.0)
        assert not _mod._rate_limit_prefill_blocks(facts, sidecar_dir.parent)
        resumed = _resume(sidecar_dir, machine, _resume_facts("continue"))
        assert resumed.decision_value not in (_KEY, _CONTINUE)

    def test_unreadable_start_time_types_nothing(
        self, sidecar_dir: Path, machine: Any, _child_starts: dict[int, tuple[int, float]]
    ) -> None:
        del _child_starts[_CHILD]
        for offset in range(3):
            outcome = _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + offset))
            assert outcome.decision_value != _KEY
        assert list(sidecar_dir.parent.glob("supervise-rate-limit-dialog.*")) == []

    def test_state_file_name_carries_the_start_ticks(self, sidecar_dir: Path) -> None:
        assert _state_path(sidecar_dir).name == f"supervise-rate-limit-dialog.{_CHILD}-424200.json"

    def test_expired_state_files_of_other_children_are_swept(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        import os

        stale = sidecar_dir.parent / "supervise-rate-limit-dialog.17-1700.json"
        stale.write_text("{}", encoding="utf-8")
        old = _NOW - 3 * 86400.0
        os.utime(stale, (old, old))
        fresh = sidecar_dir.parent / "supervise-rate-limit-dialog.18-1800.json"
        fresh.write_text("{}", encoding="utf-8")
        os.utime(fresh, (_NOW - 60.0, _NOW - 60.0))
        _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET))
        assert not stale.exists()
        assert fresh.exists()


class TestReadChildStart:
    def _proc(self, tmp_path: Path, stat_line: str, btime: int = 1_700_000_000) -> Path:
        proc = tmp_path / "proc"
        (proc / "4242").mkdir(parents=True)
        (proc / "4242" / "stat").write_text(stat_line, encoding="utf-8")
        (proc / "stat").write_text(f"cpu  1 2 3\nbtime {btime}\nprocesses 9\n", encoding="utf-8")
        return proc

    def test_field_22_after_a_comm_with_spaces_and_parens(self, tmp_path: Path) -> None:
        import os

        fields = ["S"] + [str(n) for n in range(4, 22)] + ["5000"] + ["0"] * 10
        proc = self._proc(tmp_path, "4242 (cla (u) de) " + " ".join(fields) + "\n")
        start = _mod._read_child_start(4242, proc)
        assert start is not None
        ticks, wall = start
        assert ticks == 5000
        assert wall == pytest.approx(1_700_000_000 + 5000 / os.sysconf("SC_CLK_TCK"))

    def test_missing_process_is_none(self, tmp_path: Path) -> None:
        proc = self._proc(tmp_path, "garbage")
        assert _mod._read_child_start(4242, proc) is None
        assert _mod._read_child_start(1, proc) is None

    def test_this_process_reads_from_the_real_proc(self) -> None:
        import os
        import time

        start = _mod._read_child_start(os.getpid())
        assert start is not None
        assert 0 < start[1] <= time.time() + 1


# ── Review I2: a dialog the human took over stays theirs ─────────────────────


class TestTakenOverDialogStaysTaken:
    """Past "resets 3pm" a re-read means tomorrow; the stored window must hold."""

    def _abandon(self, sidecar_dir: Path, machine: Any) -> None:
        _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET))
        typed = _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + 1, raw=b"\x1b[B"))
        assert typed.payload is None
        assert _phase(sidecar_dir) == "abandoned"

    @pytest.mark.parametrize("late", [_RESET + 3600.0, _RESET + 25 * 3600.0])
    def test_abandoned_dialog_left_on_screen_past_the_reset(
        self, sidecar_dir: Path, machine: Any, late: float
    ) -> None:
        self._abandon(sidecar_dir, machine)
        outcomes = [
            _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=late + offset))
            for offset in range(3)
        ]
        assert all(outcome.payload is None for outcome in outcomes)

    def test_key_cap_holds_past_the_reset(self, sidecar_dir: Path, machine: Any) -> None:
        stuck = _dialog(["Upgrade your plan", _TARGET], pointer=0)
        for offset in range(8):
            _tick(sidecar_dir, machine, _dialog_facts(stuck, now=_NOW + offset))
        late = [
            _tick(sidecar_dir, machine, _dialog_facts(stuck, now=_RESET + 3600.0 + offset))
            for offset in range(3)
        ]
        assert all(outcome.payload is None for outcome in late)


class TestKeysBeforeTheFirstDump:
    """Review I2: the human's keys count as taking over even before a dump shows the dialog."""

    def test_arrow_before_the_first_dump_then_quiet(self, sidecar_dir: Path, machine: Any) -> None:
        # The human presses Down while the screen is still redrawing (no dump),
        # then pauses to read; the first dump arrives with no new input.
        _tick(sidecar_dir, machine, _dialog_facts("", raw=b"\x1b[B", quiet=0.5))
        moved = _dialog(_STANDARD, pointer=1)
        outcomes = [
            _tick(sidecar_dir, machine, _dialog_facts(moved, now=_NOW + offset))
            for offset in range(1, 5)
        ]
        assert all(outcome.payload is None for outcome in outcomes)

    def test_key_in_the_same_tick_as_the_first_dump(self, sidecar_dir: Path, machine: Any) -> None:
        _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, raw=b"\x1b[B"))
        outcomes = [
            _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + offset))
            for offset in range(1, 5)
        ]
        assert all(outcome.payload is None for outcome in outcomes)

    def test_a_submitted_prompt_is_not_taking_over(self, sidecar_dir: Path, machine: Any) -> None:
        _tick(sidecar_dir, machine, _dialog_facts("", raw=b"run the tests\r", quiet=0.5))
        _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + 1))
        answered = _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + 2))
        assert answered.payload == "\r"

    def test_a_dialog_free_dump_after_the_keys_clears_them(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        _tick(sidecar_dir, machine, _dialog_facts("", raw=b"half typed", quiet=0.5))
        _tick(sidecar_dir, machine, _dialog_facts(_prompt_screen("half typed"), now=_NOW + 1))
        _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + 2))
        answered = _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + 3))
        assert answered.payload == "\r"

    def test_a_dialog_free_dump_in_the_typing_tick_does_not_clear(
        self, sidecar_dir: Path, machine: Any
    ) -> None:
        # The dump of a tick that carried keys may predate them.
        _tick(sidecar_dir, machine, _dialog_facts(_prompt_screen(""), raw=b"\x1b[B"))
        outcomes = [
            _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + offset))
            for offset in range(1, 4)
        ]
        assert all(outcome.payload is None for outcome in outcomes)

    def test_a_fresh_worker_waits_for_a_dialog_free_dump(
        self, sidecar_dir: Path, machine: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_mod, "_RATE_LIMIT_KEYS_SINCE_DUMP", {})
        first = [
            _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + offset))
            for offset in range(3)
        ]
        assert all(outcome.payload is None for outcome in first)
