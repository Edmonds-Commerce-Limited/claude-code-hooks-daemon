"""Tests for UsageIndicatorHandler (Plan 00479 Task 2.2).

The segment renders the 5-hour and weekly subscription windows, read from the
daemon's usage snapshot, as compact background-coloured chips after a line
graph icon (owner ruling: a line graph, not a bar chart). A window below the warning level is its label alone (``📈 5h|7d``); a
window at or above it adds its percentage and reset countdown
(``📈 5h 67% 3h 0m|7d``) (owner ruling: green needs no number).
"""

import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from tests.support.status_usage import NOW, load_status_payload

from claude_code_hooks_daemon.config.models import Config, HostConfig, UsageCeilingConfig
from claude_code_hooks_daemon.constants import HookInputField
from claude_code_hooks_daemon.core.data_layer import get_data_layer, reset_data_layer
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.status_line.usage_indicator import (
    UsageIndicatorHandler,
    format_countdown,
)
from claude_code_hooks_daemon.utils.usage_pause import (
    WINDOW_FIVE_HOUR,
    UsagePause,
    write_usage_pause,
)

_ANSI = re.compile(r"\033\[[0-9;]*m")

# Background bands, the same sequences model_context uses for its chips.
_GREEN = "\033[42m\033[30m"
_YELLOW = "\033[43m\033[30m"
_ORANGE = "\033[48;5;208m\033[30m"
_CRITICAL = "\033[41m\033[97m"


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
    def test_both_windows_green_are_labels_only(self) -> None:
        _feed("main_thread_integer.json")  # 5h 13, 7d 3: both green
        rendered = _render()
        assert rendered is not None
        assert _plain(rendered) == "| 📈 5h|7d"

    def test_a_warning_window_shows_its_percentage_and_countdown(self) -> None:
        _feed("main_thread_fractional.json")  # 5h 67.4 yellow, 7d 81.9 orange
        rendered = _render()
        assert rendered is not None
        assert _plain(rendered) == "| 📈 5h 67% 3h 0m|7d 81% 6d 22h"

    def test_only_the_window_over_the_warning_level_gets_detail(self) -> None:
        payload = load_status_payload("main_thread_integer.json")
        payload["rate_limits"]["seven_day"]["used_percentage"] = 75
        get_data_layer().usage.update_from_status_event(payload, now=NOW)
        rendered = _render()
        assert rendered is not None
        assert _plain(rendered) == "| 📈 5h|7d 75% 6d 22h"

    def test_seven_day_only_has_no_five_hour_part(self) -> None:
        _feed("seven_day_only.json")  # 7d 42: green
        rendered = _render()
        assert rendered is not None
        assert _plain(rendered) == "| 📈 7d"

    def test_expired_five_hour_is_dropped_and_seven_day_stays(self) -> None:
        _feed("five_hour_expired.json")
        rendered = _render()
        assert rendered is not None
        assert _plain(rendered) == "| 📈 7d"

    def test_agent_thread_payload_renders_like_the_main_thread(self) -> None:
        _feed("agent_thread.json")
        rendered = _render()
        assert rendered is not None
        assert _plain(rendered) == "| 📈 5h|7d"

    def test_percentage_is_rounded_down(self) -> None:
        payload = load_status_payload("main_thread_integer.json")
        payload["rate_limits"]["five_hour"]["used_percentage"] = 79.9
        get_data_layer().usage.update_from_status_event(payload, now=NOW)
        rendered = _render()
        assert rendered is not None
        assert "5h 79% " in _plain(rendered)


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
    def test_five_hour_background_by_threshold(self, used: float, colour: str) -> None:
        payload = load_status_payload("main_thread_integer.json")
        payload["rate_limits"]["five_hour"]["used_percentage"] = used
        get_data_layer().usage.update_from_status_event(payload, now=NOW)
        rendered = _render()
        assert rendered is not None
        assert f"{colour}5h" in rendered

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
        assert f"{_GREEN}7d\033[0m" in rendered

    def test_every_chip_is_reset(self) -> None:
        _feed("main_thread_integer.json")
        rendered = _render()
        assert rendered is not None
        assert rendered.count("\033[0m") == 2

    def test_the_separator_carries_no_background(self) -> None:
        _feed("main_thread_integer.json")
        rendered = _render()
        assert rendered is not None
        assert "\033[0m|" in rendered


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


class TestPausedSession:
    """Plan 00479 Task 4.7: a usage-paused session shows ``⏸ usage <resume HH:MM>``."""

    _SESSION = "sess-1"

    def _pause(self, tmp_path: Path, *, session: str = "sess-1") -> float:
        resume_at = NOW + 3 * 3600
        write_usage_pause(
            tmp_path,
            UsagePause(
                session_id=session,
                paused_at=NOW - 60,
                resume_at=resume_at,
                window=WINDOW_FIVE_HOUR,
                used_percentage=91.0,
                ceiling=80.0,
                reason="five_hour window at 91% (ceiling 80%)",
            ),
        )
        return resume_at

    def _render_paused(self, tmp_path: Path, session: str = "sess-1") -> str | None:
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            result = UsageIndicatorHandler().handle({"session_id": session})
        return result.context[0] if result.context else None

    def test_shows_the_pause_and_resume_time(self, tmp_path: Path) -> None:
        resume_at = self._pause(tmp_path)
        text = self._render_paused(tmp_path)
        assert text is not None
        assert f"⏸ usage {datetime.fromtimestamp(resume_at):%H:%M}" in _plain(text)

    def test_keeps_the_usage_chips_when_there_is_a_snapshot(self, tmp_path: Path) -> None:
        self._pause(tmp_path)
        _feed("main_thread_fractional.json")
        text = self._render_paused(tmp_path)
        assert text is not None
        plain = _plain(text)
        assert "⏸ usage" in plain
        assert "5h 67%" in plain

    def test_shows_the_pause_even_with_no_usage_data(self, tmp_path: Path) -> None:
        self._pause(tmp_path)
        text = self._render_paused(tmp_path)
        assert text is not None
        assert "📈" not in text

    def test_an_unreadable_record_shows_no_pause_and_does_not_raise(self, tmp_path: Path) -> None:
        self._pause(tmp_path)
        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            assert self._render_paused(tmp_path) is None

    def test_another_session_shows_no_pause(self, tmp_path: Path) -> None:
        self._pause(tmp_path, session="someone-else")
        assert self._render_paused(tmp_path) is None

    def test_a_payload_without_a_session_shows_no_pause(self, tmp_path: Path) -> None:
        self._pause(tmp_path)
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            result = UsageIndicatorHandler().handle({})
        assert result.context == []

    def test_explanation_mentions_the_pause_glyph(self) -> None:
        explanation = UsageIndicatorHandler().explain_segment()
        assert "⏸" in explanation.glyphs
        assert "paused" in explanation.how_to_read.lower()


class TestCeilingSegment:
    """Plan 00479 Task 2.3: a host ceiling shows as ``⛔ <limit>%`` after the chips."""

    _HOST = "sdlc-box"

    @staticmethod
    def _handler(hosts: dict[str, HostConfig]) -> UsageIndicatorHandler:
        handler = UsageIndicatorHandler()
        handler._config_loader = lambda: Config(hosts=hosts)
        return handler

    def _render_for(self, hosts: dict[str, HostConfig], hostname: str | None = None) -> str | None:
        hook_input = {HookInputField.SESSION_HOSTNAME: hostname or self._HOST}
        result = self._handler(hosts).handle(hook_input)
        return result.context[0] if result.context else None

    def test_shows_the_ceiling_when_one_applies(self) -> None:
        _feed("main_thread_integer.json")
        hosts = {self._HOST: HostConfig(usage_ceiling=UsageCeilingConfig(max_used_percent=80))}
        text = self._render_for(hosts)
        assert text is not None
        assert _plain(text) == "| 📈 5h|7d ⛔ 80%"

    def test_hidden_when_no_host_entry_matches(self) -> None:
        _feed("main_thread_integer.json")
        hosts = {"other": HostConfig(usage_ceiling=UsageCeilingConfig(max_used_percent=80))}
        text = self._render_for(hosts)
        assert text is not None
        assert "⛔" not in text

    def test_hidden_when_the_matching_entry_sets_no_ceiling(self) -> None:
        _feed("main_thread_integer.json")
        text = self._render_for({self._HOST: HostConfig()})
        assert text is not None
        assert "⛔" not in text

    def test_glob_pattern_entries_apply(self) -> None:
        _feed("main_thread_integer.json")
        hosts = {
            "sdlc": HostConfig(
                pattern="sdlc-*", usage_ceiling=UsageCeilingConfig(max_used_percent=70)
            )
        }
        text = self._render_for(hosts)
        assert text is not None
        assert _plain(text).endswith("⛔ 70%")

    def test_differing_window_limits_are_labelled(self) -> None:
        _feed("main_thread_integer.json")
        ceiling = UsageCeilingConfig(max_used_percent=80, seven_day=95)
        text = self._render_for({self._HOST: HostConfig(usage_ceiling=ceiling)})
        assert text is not None
        assert _plain(text).endswith("⛔ 5h 80% 7d 95%")

    def test_a_single_window_ceiling_is_labelled(self) -> None:
        _feed("main_thread_integer.json")
        ceiling = UsageCeilingConfig(seven_day=90)
        text = self._render_for({self._HOST: HostConfig(usage_ceiling=ceiling)})
        assert text is not None
        assert _plain(text).endswith("⛔ 7d 90%")

    def test_fractional_limit_keeps_its_fraction(self) -> None:
        _feed("main_thread_integer.json")
        hosts = {self._HOST: HostConfig(usage_ceiling=UsageCeilingConfig(max_used_percent=82.5))}
        text = self._render_for(hosts)
        assert text is not None
        assert _plain(text).endswith("⛔ 82.5%")

    def test_not_shown_without_usage_data(self) -> None:
        hosts = {self._HOST: HostConfig(usage_ceiling=UsageCeilingConfig(max_used_percent=80))}
        assert self._render_for(hosts) is None

    def test_a_payload_without_hostname_uses_the_process_hostname(self) -> None:
        _feed("main_thread_integer.json")
        handler = UsageIndicatorHandler()
        handler._config_loader = lambda: Config()
        text = handler.handle({}).context[0]
        assert "⛔" not in text


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
        assert "📈" in explanation.glyphs
        assert "5h" in explanation.glyphs and "7d" in explanation.glyphs
        assert "60" in explanation.how_to_read and "90" in explanation.how_to_read

    def test_explanation_current_value_reflects_the_snapshot(self) -> None:
        assert "no usage" in UsageIndicatorHandler().explain_segment().current_value.lower()
        _feed("main_thread_fractional.json")
        assert "5h 67%" in UsageIndicatorHandler().explain_segment().current_value

    def test_acceptance_tests_declared(self) -> None:
        assert UsageIndicatorHandler().get_acceptance_tests()
