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

import json
from datetime import datetime
from zoneinfo import ZoneInfo

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
