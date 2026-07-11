"""Model and context percentage handler for status line.

Formats color-coded model name with effort level signal bars and context percentage:

Format: 🤖 Model ▌▌▌░░ | ◔ XX%

Model colors (by model type):
- Blue: Haiku models
- Green: Sonnet models
- Orange: Opus models
- White: Unknown/other models

Effort level signal bars — 5 tiers, one bar per tier out of a 5-segment bar
(matches Claude Code's own canonical low/medium/high/xhigh/max ordering):
- Low:    ▌░░░░  (1 bar orange,  4 dim grey)
- Medium: ▌▌░░░  (2 bars orange, 3 dim grey)
- High:   ▌▌▌░░  (3 bars orange, 2 dim grey)
- Xhigh:  ▌▌▌▌░  (4 bars orange, 1 dim grey)
- Max:    ▌▌▌▌▌  (all 5 bars orange, none dim)

Bars are always orange when active, dim grey when inactive.

Effort level source (in priority order):
1. hook_input["effort"]["level"] — the LIVE, authoritative value Claude Code
   sends on every status-line request. This is the ONLY way to see a
   session-only override (e.g. `/effort max` for "this session only"), since
   those are never written to ~/.claude/settings.json.
2. effortLevel key in ~/.claude/settings.json (set explicitly via /model or a
   persisted /effort default) — fallback for older Claude Code versions whose
   hook_input doesn't include the live field.
3. Default "high" for Claude 4+ models (daemon default — optimal_config_checker
   enforces high) when neither of the above is available.
4. No bars for pre-4.x models (effort feature not available).

An unrecognized effort level string (a future tier the daemon doesn't know
about yet) degrades to the "high" tier's bar count rather than crashing or
showing nothing.

Note: `ultracode` (xhigh effort plus standing dynamic-workflow orchestration)
is a separate boolean toggle, not a 6th rung on this ladder — and it is not
currently present in the status-line hook_input, so it cannot be surfaced here.

Context usage (quarter circle icons with color-coded percentages):

Thresholds are keyed by context window size (in thousands of tokens). Larger
windows get tighter percentage thresholds because even moderate percentages
represent enormous absolute token counts.

200k thresholds (standard — Sonnet, Haiku, Opus-200k):
- ◔ Green (0-25%):  up to 50k tokens
- ◑ Yellow (26-50%): 50-100k tokens
- ◕ Orange (51-75%): 100-150k tokens
- ● Red (76-100%):   150k+ tokens

1000k thresholds (Opus-1M — tighter because 400k+ tokens is already huge):
- ◔ Green (0-14%):  up to 150k tokens
- ◑ Yellow (15-29%): 150-300k tokens
- ◕ Orange (30-39%): 300-400k tokens, diminishing returns territory
- ● Red (40-100%):   400k+ tokens is an enormous context to push back and forth
  per API call. Quality degrades, latency spikes, and costs balloon. Even if
  the window technically fits more, you should compact or start fresh.

Thresholds are configurable per tier via handler options:
  200k_orange_pct: 51   (default)
  200k_red_pct: 76      (default)
  1000k_orange_pct: 30  (default)
  1000k_red_pct: 40     (default)

Adding a new tier (e.g. 2000k) is just adding two new options. Models whose
context_window_size exceeds all configured tiers use the largest tier.
"""

import logging
import re
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.handlers.status_line.context_tiers import (
    _CONTEXT_TIER_200K_CRITICAL_PCT,
    _CONTEXT_TIER_200K_ORANGE_PCT,
    _CONTEXT_TIER_200K_RED_PCT,
    _CONTEXT_TIER_1000K_CRITICAL_PCT,
    _CONTEXT_TIER_1000K_ORANGE_PCT,
    _CONTEXT_TIER_1000K_RED_PCT,
    ContextTier,
    TierConfig,
    TierThresholds,
    classify_context,
)
from claude_code_hooks_daemon.handlers.status_line.settings_reader import (
    read_claude_settings,
)

logger = logging.getLogger(__name__)

# Active effort bar color (orange) - matches Claude Code UI
_EFFORT_ACTIVE = "\033[38;5;208m"

# Signal bar character - three identical left-half blocks matching Claude Code UI (▌▌▌)
_EFFORT_BAR = "▌"

# ANSI dim grey for unlit effort bars
_EFFORT_DIM = "\033[2;37m"

# Canonical effort tiers, lowest to highest — matches Claude Code's own
# ordering (confirmed via the product's /effort menu: low, medium, high,
# xhigh, max). Bar count = index + 1 out of len(_EFFORT_LEVELS_ORDERED) total
# segments. `ultracode` is a separate boolean toggle, not a 6th tier here.
_EFFORT_LEVELS_ORDERED = ("low", "medium", "high", "xhigh", "max")

# Daemon default effort level when no effort data is available at all (absent
# from both hook_input and settings). Claude Code itself defaults to "medium",
# but daemon users expect "high" because optimal_config_checker enforces high
# effort. Also used as the bar-count fallback for an unrecognized effort
# string (e.g. a future tier the daemon doesn't know about yet).
_EFFORT_DEFAULT = "high"

# Minimum Claude major version that supports effort configuration
_EFFORT_MIN_MAJOR_VERSION = 4

# Context threshold tier definitions (sizes, default orange/red percentages)
# live in the shared claude_code_hooks_daemon.handlers.status_line.context_tiers
# module — the single source of truth reused by both the status line and
# future compact-trigger logic. This handler only holds the (possibly
# config-overridden) percentage values and delegates classification to that
# module via _build_tier_config().

# Regex to extract major version from Claude 4+ model IDs
# Matches: claude-sonnet-4-6, claude-opus-4-6, claude-haiku-4-5-20251001
# Does NOT match Claude 3.x format: claude-3-5-sonnet-20241022
_MODEL_VERSION_PATTERN = re.compile(r"claude-(?:opus|sonnet|haiku)-(\d+)-")


class ModelContextHandler(Handler):
    """Format model name with effort level and color-coded context percentage."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.MODEL_CONTEXT,
            priority=Priority.MODEL_CONTEXT,
            terminal=False,
            tags=[HandlerTag.STATUS, HandlerTag.DISPLAY, HandlerTag.NON_TERMINAL],
        )
        # Per-tier context thresholds — overridable via config options.
        # Config keys match the pattern: {size}k_orange_pct, {size}k_red_pct
        # e.g. "1000k_orange_pct: 25" in hooks-daemon.yaml options.
        self._200k_orange_pct: int = _CONTEXT_TIER_200K_ORANGE_PCT
        self._200k_red_pct: int = _CONTEXT_TIER_200K_RED_PCT
        self._200k_critical_pct: int = _CONTEXT_TIER_200K_CRITICAL_PCT
        self._1000k_orange_pct: int = _CONTEXT_TIER_1000K_ORANGE_PCT
        self._1000k_red_pct: int = _CONTEXT_TIER_1000K_RED_PCT
        self._1000k_critical_pct: int = _CONTEXT_TIER_1000K_CRITICAL_PCT

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status events."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Generate model, effort level, and context percentage status text.

        Args:
            hook_input: Status event input with model and context_window data

        Returns:
            HookResult with formatted status text in context list
        """
        # Extract data with safe defaults
        model_data = hook_input.get("model", {})
        model_display = model_data.get("display_name", "Claude")
        model_id = model_data.get("id", "")
        ctx_data = hook_input.get("context_window", {})
        used_pct = ctx_data.get("used_percentage") or 0

        # Color code model name by model type
        model_lower = model_display.lower()
        if "haiku" in model_lower:
            model_color = "\033[34m"  # Blue for Haiku
        elif "sonnet" in model_lower:
            model_color = "\033[32m"  # Green for Sonnet
        elif "opus" in model_lower:
            model_color = "\033[38;5;208m"  # Orange for Opus
        else:
            model_color = "\033[37m"  # White for unknown

        reset = "\033[0m"

        # Build model display with optional effort signal bars
        effort_suffix = self._get_effort_suffix(hook_input, model_id, reset)
        model_part = f"🤖 {model_color}{model_display}{reset}{effort_suffix}"

        # Get quarter circle icon and colors based on usage threshold
        window_size = ctx_data.get("context_window_size") or 0
        ctx_icon, icon_color, pct_color = self._get_context_icon_and_color(
            used_pct, window_size=window_size
        )

        # Format: "🤖 Model ▌▌▌ | ◔ XX%" with colored icon and percentage
        status = f"{model_part} | {icon_color}{ctx_icon}{reset} {pct_color}{used_pct:.1f}%{reset}"

        return HookResult(context=[status])

    def _get_effort_suffix(self, hook_input: dict[str, Any], model_id: str, reset: str) -> str:
        """Get effort level signal bars for Claude 4+ models.

        Shows a 5-segment bar (▌▌▌▌▌) where active bars are orange, inactive dim grey.
        Prefers the live hook_input["effort"]["level"] field; falls back to
        effortLevel from settings. When both are absent, defaults to "high" for
        Claude 4+ models (daemon optimal default).

        Args:
            hook_input: Status event input, checked for a live "effort" field
            model_id: Model ID string (e.g. "claude-sonnet-4-6")
            reset: ANSI reset code

        Returns:
            Formatted effort bars like " ▌▌▌▌▌" or empty string for unsupported models
        """
        effort_level = self._read_effort_level(hook_input, model_id)
        if effort_level is None:
            return ""

        return f" {self._render_effort_bars(effort_level, reset)}"

    def _render_effort_bars(self, effort_level: str, reset: str) -> str:
        """Render a 5-segment bar for the given effort level.

        One bar lit per tier position in _EFFORT_LEVELS_ORDERED (low=1 ... max=5).
        An unrecognized level degrades to _EFFORT_DEFAULT's bar count rather than
        crashing or showing nothing, so a future tier the daemon doesn't know
        about yet still renders something sensible.

        Args:
            effort_level: One of _EFFORT_LEVELS_ORDERED, or an unrecognized string
            reset: ANSI reset code

        Returns:
            Formatted bar string, e.g. "▌▌▌\033[2;37m▌▌\033[0m" for "high"
        """
        if effort_level in _EFFORT_LEVELS_ORDERED:
            active_count = _EFFORT_LEVELS_ORDERED.index(effort_level) + 1
        else:
            active_count = _EFFORT_LEVELS_ORDERED.index(_EFFORT_DEFAULT) + 1

        total = len(_EFFORT_LEVELS_ORDERED)
        dim_count = total - active_count

        active = f"{_EFFORT_ACTIVE}{_EFFORT_BAR * active_count}"
        dim = f"{_EFFORT_DIM}{_EFFORT_BAR * dim_count}" if dim_count else ""

        return f"{active}{dim}{reset}"

    def _read_effort_level(self, hook_input: dict[str, Any], model_id: str) -> str | None:
        """Determine effort level for the given model.

        Priority:
        1. hook_input["effort"]["level"] — the LIVE value Claude Code sends on
           every status-line request. This is the only way to see a session-only
           /effort override, since those are never written to settings.json.
        2. effortLevel from ~/.claude/settings.json (explicitly set via /model,
           or a persisted /effort default) — fallback for older Claude Code
           versions whose hook_input doesn't include the live field.
        3. _EFFORT_DEFAULT ("high") for Claude 4+ models (daemon optimal default)
        4. None for pre-4.x models (effort not supported)

        Args:
            hook_input: Status event input, checked for a live "effort" field
            model_id: Model ID string (e.g. "claude-sonnet-4-6")

        Returns:
            Effort level string (low/medium/high/xhigh/max/other) or None if not applicable
        """
        live_effort = hook_input.get("effort")
        if isinstance(live_effort, dict):
            live_level = live_effort.get("level")
            if live_level:
                return str(live_level)

        settings = read_claude_settings(self._get_settings_path())

        level = settings.get("effortLevel")
        if level is not None:
            return str(level)

        # Not in settings - use default "high" for Claude 4+ (daemon optimal)
        if self._model_supports_effort(model_id):
            return _EFFORT_DEFAULT

        return None

    def _model_supports_effort(self, model_id: str) -> bool:
        """Check if model supports effort configuration (Claude 4+).

        Claude 4+ model IDs follow: claude-{family}-{major}-{minor}
        e.g. claude-sonnet-4-6, claude-opus-4-6, claude-haiku-4-5-20251001

        Args:
            model_id: Model ID string to check

        Returns:
            True if model is Claude 4 or later
        """
        match = _MODEL_VERSION_PATTERN.search(model_id)
        if match:
            major = int(match.group(1))
            return major >= _EFFORT_MIN_MAJOR_VERSION
        return False

    def _get_settings_path(self) -> Path:
        """Get path to Claude settings file.

        Returns:
            Path to ~/.claude/settings.json
        """
        return Path.home() / ".claude" / "settings.json"

    def _get_context_icon_and_color(
        self, used_pct: float, *, window_size: int = 0
    ) -> tuple[str, str, str]:
        """Get quarter circle icon, icon color, and percentage background color.

        Selects threshold tier based on context_window_size. Larger windows get
        tighter percentage thresholds because even moderate percentages represent
        enormous absolute token counts at scale (e.g. 30% of 1M = 300k tokens).

        Args:
            used_pct: Context usage percentage (0-100)
            window_size: Context window size in tokens (e.g. 200000, 1000000)

        Returns:
            Tuple of (icon, icon_fg_color, percentage_bg_color)
        """
        cfg = self._build_tier_config()
        tier = classify_context(used_pct, window_size, cfg)

        if tier is ContextTier.GREEN:
            return "◔", "\033[32m", "\033[42m\033[30m"
        elif tier is ContextTier.YELLOW:
            return "◑", "\033[33m", "\033[43m\033[30m"
        elif tier is ContextTier.ORANGE:
            return "◕", "\033[38;5;208m", "\033[48;5;208m\033[30m"
        elif tier is ContextTier.RED:
            return "●", "\033[31m", "\033[41m\033[97m"
        else:
            # CRITICAL (Plan 00151): the loudest signal — 🛑 with a BRIGHT-red
            # (\033[101m) background so it is unmistakable from the plain-red
            # band. This is the "compact NOW" state.
            return "🛑", "\033[1;91m", "\033[101m\033[30m"

    def _build_tier_config(self) -> TierConfig:
        """Build a TierConfig from this handler's (possibly overridden) options.

        Config keys match the pattern: {size}k_orange_pct, {size}k_red_pct
        (e.g. "1000k_orange_pct: 25" in hooks-daemon.yaml options) and are
        applied to instance attrs in __init__. This method translates those
        attrs into the shared context_tiers module's TierConfig so the actual
        classification logic has a single source of truth.

        Returns:
            TierConfig reflecting any config overrides on this instance
        """
        return TierConfig(
            t200k=TierThresholds(
                orange_pct=self._200k_orange_pct,
                red_pct=self._200k_red_pct,
                critical_pct=self._200k_critical_pct,
            ),
            t1000k=TierThresholds(
                orange_pct=self._1000k_orange_pct,
                red_pct=self._1000k_red_pct,
                critical_pct=self._1000k_critical_pct,
            ),
        )

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="model context handler test",
                command='echo "test"',
                description="Tests model context handler functionality",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
