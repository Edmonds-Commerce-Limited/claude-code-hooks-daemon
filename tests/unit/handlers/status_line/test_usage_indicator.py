"""Tests for UsageIndicatorHandler (Plan 00479 Task 2.2).

The segment renders the 5-hour and weekly subscription windows, read from the
daemon's usage snapshot, e.g. ``5h 13% (3h 0m) · 7d 3%``.
"""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.support.status_usage import NOW, load_status_payload

from claude_code_hooks_daemon.core.data_layer import get_data_layer, reset_data_layer
from claude_code_hooks_daemon.handlers.status_line.usage_indicator import (
    UsageIndicatorHandler,
    format_countdown,
)

_ANSI = re.compile(r"\033\[[0-9;]*m")

_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_ORANGE = "\033[38;5;208m"
_CRITICAL = "\033[1;91m"


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Fresh data layer, no host-wide file, and a clock fixed at NOW."""
    reset_data_layer()
    monkeypatch.setattr(
        "claude_code_hooks_daemon.core.data_layer.resolve_usage_state_file", lambda: None
    )
    monkeypatch.setattr(
        "claude_code_hooks_daemon.handlers.status_line.usage_indicator.time.time", lambda: NOW
    )
    monkeypatch.setattr("claude_code_hooks_daemon.core.data_layer.time.time", lambda: NOW)
    yield
    reset_data_layer()


def _feed(name: str) -> None:
    get_data_layer().usage.update_from_status_event(load_status_payload(name), now=NOW)


def _render(handler: UsageIndicatorHandler | None = None) -> str | None:
    result = (handler or UsageIndicatorHandler()).handle({})
    assert len(result.context) <= 1
    return result.context[0] if result.context else None


class TestVisibility:
    def test_hidden_when_no_data(self) -> None:
        assert _render() is None

    def test_hidden_before_first_response(self) -> None:
        _feed("before_first_response.json")
        assert _render() is None

    def test_hidden_when_every_window_expired(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _feed("main_thread_integer.json")
        monkeypatch.setattr("claude_code_hooks_daemon.core.data_layer.time.time", lambda: NOW + 1e9)
        assert _render() is None

    def test_matches_always(self) -> None:
        assert UsageIndicatorHandler().matches({}) is True


class TestRendering:
    def test_both_windows_with_five_hour_countdown(self) -> None:
        _feed("main_thread_integer.json")
        rendered = _render()
        assert rendered is not None
        assert _plain(rendered) == "| 5h 13% (3h 0m) · 7d 3%"

    def test_fractional_percentage_shows_the_whole_number_below(self) -> None:
        _feed("main_thread_fractional.json")
        rendered = _render()
        assert rendered is not None
        assert _plain(rendered).startswith("| 5h 67% (3h 0m) · 7d 81%")

    def test_seven_day_only_has_no_five_hour_part(self) -> None:
        _feed("seven_day_only.json")
        rendered = _render()
        assert rendered is not None
        assert _plain(rendered) == "| 7d 42%"

    def test_expired_five_hour_is_dropped_and_seven_day_stays(self) -> None:
        _feed("five_hour_expired.json")
        rendered = _render()
        assert rendered is not None
        assert _plain(rendered) == "| 7d 3%"

    def test_agent_thread_payload_renders_like_the_main_thread(self) -> None:
        _feed("agent_thread.json")
        rendered = _render()
        assert rendered is not None
        assert _plain(rendered) == "| 5h 13% (3h 0m) · 7d 3%"

    def test_seven_day_countdown_shown_when_it_is_high(self) -> None:
        _feed("main_thread_fractional.json")
        rendered = _render()
        assert rendered is not None
        assert _plain(rendered) == "| 5h 67% (3h 0m) · 7d 81% (6d 22h)"

    def test_seven_day_countdown_threshold_is_an_option(self) -> None:
        _feed("main_thread_integer.json")
        handler = UsageIndicatorHandler()
        handler._seven_day_countdown_pct = 3
        rendered = _render(handler)
        assert rendered is not None
        assert _plain(rendered).endswith("7d 3% (6d 22h)")


class TestColour:
    @pytest.mark.parametrize(
        ("used", "colour"),
        [
            (0, _GREEN),
            (59.9, _GREEN),
            (60, _YELLOW),
            (79.9, _YELLOW),
            (80, _ORANGE),
            (89.9, _ORANGE),
            (90, _CRITICAL),
            (100, _CRITICAL),
        ],
    )
    def test_five_hour_colour_by_threshold(self, used: float, colour: str) -> None:
        payload = load_status_payload("main_thread_integer.json")
        payload["rate_limits"]["five_hour"]["used_percentage"] = used
        get_data_layer().usage.update_from_status_event(payload, now=NOW)
        rendered = _render()
        assert rendered is not None
        assert f"{colour}5h " in rendered

    def test_each_window_is_coloured_by_its_own_percentage(self) -> None:
        _feed("main_thread_fractional.json")  # 5h 67.4 -> yellow, 7d 81.9 -> orange
        rendered = _render()
        assert rendered is not None
        assert f"{_YELLOW}5h 67%" in rendered
        assert f"{_ORANGE}7d 81%" in rendered

    def test_thresholds_are_options(self) -> None:
        _feed("main_thread_integer.json")
        handler = UsageIndicatorHandler()
        handler._warn_pct = 5
        handler._high_pct = 10
        handler._critical_pct = 12
        rendered = _render(handler)
        assert rendered is not None
        assert f"{_CRITICAL}5h 13%" in rendered
        assert f"{_GREEN}7d 3%" in rendered

    def test_every_coloured_part_is_reset(self) -> None:
        _feed("main_thread_integer.json")
        rendered = _render()
        assert rendered is not None
        assert rendered.count("\033[0m") == 2


class TestFormatCountdown:
    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (0, "<1m"),
            (59, "<1m"),
            (60, "1m"),
            (3_000, "50m"),
            (3_600, "1h 0m"),
            (12_000, "3h 20m"),
            (86_399, "23h 59m"),
            (86_400, "1d 0h"),
            (601_200, "6d 23h"),
        ],
    )
    def test_formats(self, seconds: int, expected: str) -> None:
        assert format_countdown(seconds) == expected


class TestFailSilent:
    def test_snapshot_read_failure_renders_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(**_: object) -> None:
            raise OSError("disk gone")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.status_line.usage_indicator.latest_usage", boom
        )
        assert _render() is None


class TestHandlerContract:
    def test_is_non_terminal_status_line_handler(self) -> None:
        handler = UsageIndicatorHandler()
        assert handler.terminal is False
        assert handler.priority == 16

    def test_defaults_enabled(self) -> None:
        assert UsageIndicatorHandler().get_default_enabled() is True

    def test_explanation_names_its_glyphs_and_thresholds(self) -> None:
        explanation = UsageIndicatorHandler().explain_segment()
        assert explanation.name == "Subscription Usage"
        assert "5h" in explanation.glyphs and "7d" in explanation.glyphs
        assert "60" in explanation.how_to_read and "90" in explanation.how_to_read

    def test_explanation_current_value_reflects_the_snapshot(self) -> None:
        assert "no usage" in UsageIndicatorHandler().explain_segment().current_value.lower()
        _feed("main_thread_integer.json")
        assert "5h 13%" in UsageIndicatorHandler().explain_segment().current_value

    def test_acceptance_tests_declared(self) -> None:
        assert UsageIndicatorHandler().get_acceptance_tests()
