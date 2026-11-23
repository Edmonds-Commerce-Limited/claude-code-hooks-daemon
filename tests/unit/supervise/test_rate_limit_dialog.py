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
    return sidecar_dir.parent / f"supervise-rate-limit-dialog.{child_pid}.json"


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
        for offset in range(3):
            outcome = _tick(
                sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + offset), dry_run=True
            )
            assert outcome.payload is None
        assert "would press" in (outcome.noop_reason_log or "")

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
        for offset in range(6, 9):
            outcome = _tick(sidecar_dir, machine, _dialog_facts(_ON_TARGET, now=_NOW + offset))
            assert outcome.payload is None
        assert "already answered" in (outcome.noop_reason_log or "")

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
