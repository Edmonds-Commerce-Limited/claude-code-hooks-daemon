"""Tests for ModelContextHandler."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.handlers.status_line import ModelContextHandler


class TestModelContextHandler:
    """Tests for ModelContextHandler."""

    @pytest.fixture
    def handler(self) -> ModelContextHandler:
        """Create handler instance."""
        return ModelContextHandler()

    def test_handler_properties(self, handler: ModelContextHandler) -> None:
        """Test handler has correct properties."""
        assert handler.name == "status-model-context"
        assert handler.priority == 10
        assert handler.terminal is False
        assert "status" in handler.tags
        assert "display" in handler.tags

    def test_matches_always_returns_true(self, handler: ModelContextHandler) -> None:
        """Handler should always match for status events."""
        assert handler.matches({}) is True
        assert handler.matches({"model": {"display_name": "Claude"}}) is True

    def test_handle_with_full_data(self, handler: ModelContextHandler) -> None:
        """Test formatting with full model and context data."""
        hook_input = {
            "model": {"id": "claude-sonnet-4-6", "display_name": "Sonnet 4.6"},
            "context_window": {"used_percentage": 42.5},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert "Sonnet 4.6" in result.context[0]
        assert "42.5%" in result.context[0]
        assert "🤖" in result.context[0]
        assert "◑" in result.context[0]

    def test_handle_with_defaults(self, handler: ModelContextHandler) -> None:
        """Test formatting with missing data uses defaults."""
        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle({})

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert "Claude" in result.context[0]
        assert "0.0%" in result.context[0]

    def test_color_coding_green(self, handler: ModelContextHandler) -> None:
        """Test green color for low usage (0-25%)."""
        hook_input = {
            "model": {"id": "", "display_name": "Claude"},
            "context_window": {"used_percentage": 20.0},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert "\033[42m" in result.context[0]
        assert "◔" in result.context[0]

    def test_color_coding_yellow(self, handler: ModelContextHandler) -> None:
        """Test yellow color for moderate usage (41-60%)."""
        hook_input = {
            "model": {"id": "", "display_name": "Claude"},
            "context_window": {"used_percentage": 50.0},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert "\033[43m" in result.context[0]

    def test_color_coding_orange(self, handler: ModelContextHandler) -> None:
        """Test orange color for high usage (61-80%)."""
        hook_input = {
            "model": {"id": "", "display_name": "Claude"},
            "context_window": {"used_percentage": 70.0},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert "\033[48;5;208m" in result.context[0]

    def test_color_coding_red(self, handler: ModelContextHandler) -> None:
        """Test red color for the red band (76-89% at 200k)."""
        hook_input = {
            "model": {"id": "", "display_name": "Claude"},
            "context_window": {"used_percentage": 80.0},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert "\033[41m" in result.context[0]

    def test_color_coding_critical(self, handler: ModelContextHandler) -> None:
        """CRITICAL (>=90% at 200k) renders a distinct loud signal (Plan 00151).

        It must NOT look like plain red: a bright-red background and the 🛑 icon
        so the "compact NOW" state is unmistakable in the status line.
        """
        hook_input = {
            "model": {"id": "", "display_name": "Claude"},
            "context_window": {"used_percentage": 95.0},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        # The circle icon is replaced by a literal "COMPACT NOW" call to action.
        assert "COMPACT NOW" in result.context[0]
        assert "🛑" in result.context[0]
        assert "\033[101m" in result.context[0]

    def test_color_reset_included(self, handler: ModelContextHandler) -> None:
        """Test that ANSI reset code is included."""
        hook_input = {
            "model": {"id": "", "display_name": "Claude"},
            "context_window": {"used_percentage": 50.0},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert "\033[0m" in result.context[0]

    def test_handle_with_null_used_percentage(self, handler: ModelContextHandler) -> None:
        """Test handling when used_percentage is None (fixes TypeError bug).

        Early in a session, Claude Code may send null for used_percentage.
        """
        hook_input = {
            "model": {"id": "claude-sonnet-4-6", "display_name": "Sonnet 4.6"},
            "context_window": {"used_percentage": None},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert "Sonnet 4.6" in result.context[0]
        assert "0.0%" in result.context[0]
        assert "\033[42m" in result.context[0]

    # --- Effort bars: explicit settings (5-tier: low/medium/high/xhigh/max) ---

    def test_explicit_low_effort_shows_one_of_five_bars(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """Explicitly set low effort shows one orange bar, four dim."""
        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 30.0},
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"effortLevel": "low"}))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "\033[38;5;208m▌\033[2;37m▌▌▌▌\033[0m" in result.context[0]

    def test_explicit_medium_effort_shows_two_of_five_bars(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """Explicitly set medium effort shows two orange bars, three dim."""
        hook_input = {
            "model": {"id": "claude-sonnet-4-6", "display_name": "Sonnet 4.6"},
            "context_window": {"used_percentage": 30.0},
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"effortLevel": "medium"}))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "\033[38;5;208m▌▌\033[2;37m▌▌▌\033[0m" in result.context[0]

    def test_explicit_high_effort_shows_three_of_five_bars(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """Explicitly set high effort shows three orange bars, two dim."""
        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 30.0},
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"effortLevel": "high"}))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "\033[38;5;208m▌▌▌\033[2;37m▌▌\033[0m" in result.context[0]

    def test_explicit_xhigh_effort_shows_four_of_five_bars(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """Explicitly set xhigh effort shows four orange bars, one dim."""
        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 30.0},
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"effortLevel": "xhigh"}))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "\033[38;5;208m▌▌▌▌\033[2;37m▌\033[0m" in result.context[0]

    def test_explicit_max_effort_shows_five_of_five_bars_no_dim(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """Explicitly set max effort shows all five bars orange, none dim.

        'max' is settable this-session-only via /effort (not persisted to
        settings.json's effortLevel, whose schema only allows low/medium/
        high/xhigh) but the live hook_input signal (tested separately below)
        is how it actually reaches the handler in practice.
        """
        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 30.0},
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"effortLevel": "max"}))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "\033[38;5;208m▌▌▌▌▌\033[0m" in result.context[0]
        assert "\033[2;37m" not in result.context[0]

    # --- Effort bars: live hook_input["effort"]["level"] takes priority ---
    # Claude Code sends the authoritative, live effort level directly on every
    # Status event (confirmed via daemon log dogfooding: 'effort': {'level': 'max'}
    # appears in the raw hook_input). This is the ONLY way to see session-only
    # /effort overrides, since those are never written to settings.json.

    def test_live_hook_input_effort_overrides_stale_settings_json(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """A live hook_input effort level wins over a stale settings.json value.

        Regression test: switching effort via `/effort max` (this session only)
        does NOT update ~/.claude/settings.json, so a handler that reads only
        settings.json renders the OLD level forever. The live hook_input field
        must be checked first.
        """
        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 30.0},
            "effort": {"level": "max"},
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"effortLevel": "low"}))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        # Live "max" wins: five bars, not the stale settings.json "low" (one bar)
        assert "\033[38;5;208m▌▌▌▌▌\033[0m" in result.context[0]

    def test_live_hook_input_effort_low_overrides_stale_settings_high(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """Live hook_input effort wins even when settings.json claims a higher tier."""
        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 30.0},
            "effort": {"level": "low"},
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"effortLevel": "high"}))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "\033[38;5;208m▌\033[2;37m▌▌▌▌\033[0m" in result.context[0]

    def test_live_hook_input_effort_shown_even_for_unrecognized_model_id(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """Live effort field is trusted even when model_id fails the version regex.

        Claude Code itself decided to send the field, so it is authoritative --
        the handler should not second-guess it via _model_supports_effort().
        """
        hook_input = {
            "model": {"id": "", "display_name": "Claude"},
            "context_window": {"used_percentage": 30.0},
            "effort": {"level": "high"},
        }
        settings_file = tmp_path / "nonexistent.json"

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "\033[38;5;208m▌▌▌\033[2;37m▌▌\033[0m" in result.context[0]

    def test_missing_hook_input_effort_falls_back_to_settings_json(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """No 'effort' key in hook_input (older Claude Code) falls back cleanly."""
        hook_input = {
            "model": {"id": "claude-sonnet-4-6", "display_name": "Sonnet 4.6"},
            "context_window": {"used_percentage": 30.0},
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"effortLevel": "medium"}))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "\033[38;5;208m▌▌\033[2;37m▌▌▌\033[0m" in result.context[0]

    def test_null_hook_input_effort_level_falls_back_to_settings_json(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """A present-but-null 'level' (defensive) falls back to settings.json."""
        hook_input = {
            "model": {"id": "claude-sonnet-4-6", "display_name": "Sonnet 4.6"},
            "context_window": {"used_percentage": 30.0},
            "effort": {"level": None},
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"effortLevel": "medium"}))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "\033[38;5;208m▌▌\033[2;37m▌▌▌\033[0m" in result.context[0]

    def test_non_dict_hook_input_effort_falls_back_to_settings_json(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """A malformed non-dict 'effort' value (defensive) doesn't crash the handler."""
        hook_input = {
            "model": {"id": "claude-sonnet-4-6", "display_name": "Sonnet 4.6"},
            "context_window": {"used_percentage": 30.0},
            "effort": "high",
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"effortLevel": "medium"}))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "\033[38;5;208m▌▌\033[2;37m▌▌▌\033[0m" in result.context[0]

    def test_unrecognized_live_effort_level_defaults_to_high_bars(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """An unrecognized future effort string renders as the 'high' default tier.

        Forward-compat: if Claude Code ships a 6th named tier before the daemon
        is updated, degrade to the daemon's existing default rather than crash
        or silently show zero bars.
        """
        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 30.0},
            "effort": {"level": "super-ultra"},
        }
        settings_file = tmp_path / "nonexistent.json"

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "\033[38;5;208m▌▌▌\033[2;37m▌▌\033[0m" in result.context[0]

    # --- Effort bars: default "high" for Claude 4+ when not in settings ---
    # (daemon default, not Claude Code default — see Bug 00088-4)

    def test_claude4_defaults_to_high_bars_when_effort_absent(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """Claude 4+ with no effortLevel in settings shows high bars (daemon default)."""
        hook_input = {
            "model": {"id": "claude-sonnet-4-6", "display_name": "Sonnet 4.6"},
            "context_window": {"used_percentage": 30.0},
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"alwaysThinkingEnabled": True}))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        # High = all three orange bars, no dim
        assert "\033[38;5;208m▌▌▌" in result.context[0]

    def test_claude4_defaults_to_high_bars_when_settings_missing(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """Claude 4+ with no settings file at all shows high bars (daemon default)."""
        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 30.0},
        }
        settings_file = tmp_path / "nonexistent.json"

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "\033[38;5;208m▌▌▌" in result.context[0]

    def test_haiku4_defaults_to_high_bars_when_effort_absent(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """Haiku 4.x with no effortLevel also defaults to high bars."""
        hook_input = {
            "model": {"id": "claude-haiku-4-5-20251001", "display_name": "Haiku 4.5"},
            "context_window": {"used_percentage": 10.0},
        }
        settings_file = tmp_path / "nonexistent.json"

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "\033[38;5;208m▌▌▌" in result.context[0]

    # --- No bars for pre-4.x models ---

    def test_claude3_no_bars_when_effort_not_in_settings(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """Claude 3.x models don't support effort - no bars shown."""
        hook_input = {
            "model": {"id": "claude-3-5-sonnet-20241022", "display_name": "Claude 3.5 Sonnet"},
            "context_window": {"used_percentage": 30.0},
        }
        settings_file = tmp_path / "nonexistent.json"

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "▌" not in result.context[0]

    def test_no_model_id_no_bars(self, handler: ModelContextHandler, tmp_path: Path) -> None:
        """Missing model ID shows no effort bars (safe default)."""
        hook_input = {
            "model": {"display_name": "Claude"},
            "context_window": {"used_percentage": 30.0},
        }
        settings_file = tmp_path / "nonexistent.json"

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "▌" not in result.context[0]

    # --- _model_supports_effort unit tests ---

    def test_model_supports_effort_sonnet46(self, handler: ModelContextHandler) -> None:
        """claude-sonnet-4-6 supports effort."""
        assert handler._model_supports_effort("claude-sonnet-4-6") is True

    def test_model_supports_effort_opus46(self, handler: ModelContextHandler) -> None:
        """claude-opus-4-6 supports effort."""
        assert handler._model_supports_effort("claude-opus-4-6") is True

    def test_model_supports_effort_haiku45(self, handler: ModelContextHandler) -> None:
        """claude-haiku-4-5-20251001 supports effort."""
        assert handler._model_supports_effort("claude-haiku-4-5-20251001") is True

    def test_model_supports_effort_claude3_false(self, handler: ModelContextHandler) -> None:
        """claude-3-5-sonnet-20241022 does not support effort."""
        assert handler._model_supports_effort("claude-3-5-sonnet-20241022") is False

    def test_model_supports_effort_empty_false(self, handler: ModelContextHandler) -> None:
        """Empty model ID does not support effort."""
        assert handler._model_supports_effort("") is False

    # --- Bug 00088-4: Default effort should be "high" (daemon optimal) ---

    def test_absent_effort_defaults_to_high_not_medium(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """Bug 00088-4: When effortLevel absent from settings, default to 'high'.

        The daemon's optimal_config_checker enforces high effort. Claude Code
        can overwrite ~/.claude/settings.json and remove effortLevel. When this
        happens, the status line should show 'high' (daemon default), not
        'medium' (Claude Code default), because daemon users expect high effort.

        Note: 'high' is the middle of five tiers (low/medium/high/xhigh/max), so
        it renders as 3 active bars + 2 dim bars, not "zero dim bars" — that
        assumption held back when high was the top tier, before xhigh/max existed.
        """
        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 30.0},
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"model": "opus"}))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        # High effort = 3 of 5 bars active (orange), 2 dim bars trailing
        assert "\033[38;5;208m▌▌▌\033[2;37m▌▌" in result.context[0]

    def test_effort_suffix_docstring_matches_default(self, handler: ModelContextHandler) -> None:
        """_get_effort_suffix docstring must state the real default ('high'), not 'medium'.

        Doc-vs-code drift: the code defaults to _EFFORT_DEFAULT == 'high', so the
        docstring must not claim 'medium' for unset effort on Claude 4+.
        """
        from claude_code_hooks_daemon.handlers.status_line import model_context

        doc = handler._get_effort_suffix.__doc__
        assert doc is not None
        assert model_context._EFFORT_DEFAULT == "high"
        assert 'defaults to "high"' in doc
        assert 'defaults to "medium"' not in doc

    def test_read_effort_level_falls_back_to_default_on_oserror(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """_read_effort_level returns daemon default on OSError for Claude 4+."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text('{"effortLevel": "medium"}')

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            with patch("pathlib.Path.read_text", side_effect=OSError("permission denied")):
                result = handler._read_effort_level({}, "claude-sonnet-4-6")

        # Claude 4+ falls back to daemon default ("high"), not None
        assert result == "high"

    def test_read_effort_level_returns_none_on_oserror_for_old_models(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """_read_effort_level returns None on OSError for pre-4.x models."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text('{"effortLevel": "medium"}')

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            with patch("pathlib.Path.read_text", side_effect=OSError("permission denied")):
                result = handler._read_effort_level({}, "claude-3-5-sonnet-20241022")

        assert result is None

    def test_read_effort_level_falls_back_to_default_on_invalid_json(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """_read_effort_level returns daemon default on invalid JSON for Claude 4+."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{invalid json{{")

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler._read_effort_level({}, "claude-sonnet-4-6")

        assert result == "high"

    # --- Context-window-size-based thresholds ---
    # Thresholds keyed by context window size (in thousands of tokens).
    # Larger windows get tighter % thresholds because even moderate percentages
    # represent enormous absolute token counts.

    def test_1000k_red_at_40_percent(self, handler: ModelContextHandler) -> None:
        """1M context: 40%+ (400k tokens) should show red."""
        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 45.0, "context_window_size": 1000000},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert "●" in result.context[0]
        assert "\033[41m" in result.context[0]

    def test_1000k_orange_at_30_percent(self, handler: ModelContextHandler) -> None:
        """1M context: 30-39% (300-400k tokens) should show orange."""
        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 35.0, "context_window_size": 1000000},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert "◕" in result.context[0]
        assert "\033[48;5;208m" in result.context[0]

    def test_1000k_yellow_at_15_percent(self, handler: ModelContextHandler) -> None:
        """1M context: 15-29% (150-300k tokens) should show yellow."""
        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 18.0, "context_window_size": 1000000},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert "◑" in result.context[0]
        assert "\033[43m" in result.context[0]

    def test_1000k_green_below_15_percent(self, handler: ModelContextHandler) -> None:
        """1M context: below 15% should show green."""
        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 10.0, "context_window_size": 1000000},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert "◔" in result.context[0]
        assert "\033[42m" in result.context[0]

    def test_1000k_boundary_30_is_orange(self, handler: ModelContextHandler) -> None:
        """1M context: exactly 30% (boundary) should be orange."""
        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 30.0, "context_window_size": 1000000},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert "◕" in result.context[0]

    def test_1000k_boundary_40_is_red(self, handler: ModelContextHandler) -> None:
        """1M context: exactly 40% (boundary) should be red."""
        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 40.0, "context_window_size": 1000000},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert "●" in result.context[0]
        assert "\033[41m" in result.context[0]

    def test_200k_uses_standard_thresholds(self, handler: ModelContextHandler) -> None:
        """200k context: 35% should be yellow (standard 26-50% band)."""
        hook_input = {
            "model": {"id": "claude-sonnet-4-6", "display_name": "Sonnet 4.6"},
            "context_window": {"used_percentage": 35.0, "context_window_size": 200000},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert "◑" in result.context[0]
        assert "\033[43m" in result.context[0]

    def test_200k_thresholds_configurable(self, handler: ModelContextHandler) -> None:
        """200k thresholds can be overridden via config options."""
        handler._200k_orange_pct = 40
        handler._200k_red_pct = 60

        hook_input = {
            "model": {"id": "claude-sonnet-4-6", "display_name": "Sonnet 4.6"},
            "context_window": {"used_percentage": 45.0, "context_window_size": 200000},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert "◕" in result.context[0]
        assert "\033[48;5;208m" in result.context[0]

    def test_1000k_thresholds_configurable(self, handler: ModelContextHandler) -> None:
        """1000k thresholds can be overridden via config options."""
        handler._1000k_orange_pct = 20
        handler._1000k_red_pct = 35

        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 22.0, "context_window_size": 1000000},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert "◕" in result.context[0]
        assert "\033[48;5;208m" in result.context[0]

    def test_opus_200k_uses_200k_thresholds(self, handler: ModelContextHandler) -> None:
        """Opus with 200k context should use 200k thresholds, not 1000k."""
        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 35.0, "context_window_size": 200000},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        # 35% with 200k = yellow (standard 26-50% band), NOT orange (1000k band)
        assert "◑" in result.context[0]
        assert "\033[43m" in result.context[0]

    def test_missing_context_window_size_uses_200k(self, handler: ModelContextHandler) -> None:
        """Missing context_window_size falls back to 200k (standard) thresholds."""
        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 35.0},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        # No size info -> standard thresholds -> 35% = yellow
        assert "◑" in result.context[0]

    def test_future_2000k_falls_back_to_1000k(self, handler: ModelContextHandler) -> None:
        """A hypothetical 2M context uses the largest configured tier (1000k)."""
        hook_input = {
            "model": {"id": "claude-opus-5-0", "display_name": "Opus 5.0"},
            "context_window": {"used_percentage": 35.0, "context_window_size": 2000000},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        # 2M > 1M so uses 1000k tier -> 35% = orange (30-39% band)
        assert "◕" in result.context[0]
