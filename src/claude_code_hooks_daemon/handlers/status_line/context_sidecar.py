"""Observe-only context sidecar handler (status_line).

Plan 00135 Slice 1. On every status-line render this handler writes a small
JSON "sidecar" recording the current context-window state, so an
out-of-process supervisor (the PTY ``claude-supervise`` typist) can decide
when to inject ``/compact`` — WITHOUT the daemon ever typing anything itself.

This handler is the SENSOR half of the observe-only design boundary
(Plan 00135 Decision A / the ARCH-B pivot): the daemon *observes and records*;
a separate supervisor process *actuates*. Concretely this handler:

- renders NOTHING to the status line (returns an empty ``context``),
- injects NOTHING into the session,
- only writes ``{red, tier, pct, ...}`` atomically to the daemon untracked dir.

The ``red`` flag is the trigger signal (Plan 00135 Decision J): it is computed
via the SAME ``context_tiers`` classifier the status line uses, so
"supervisor should compact" and "status line shows red" can never drift —
change a tier/model/config threshold once and both follow. The supervisor
reads ``red`` straight from the sidecar and never re-thresholds a raw
percentage.

Opt-in (``get_default_enabled() -> False``): it ships dormant and is only
useful when a supervisor is watching. It shares its threshold options with
``model_context`` (``shares_options_with``) so any per-project threshold
override applies to both, keeping the two in lock-step.
"""

import json
import logging
import os
import re
import time
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.status_line.context_tiers import (
    _CONTEXT_TIER_200K_CRITICAL_PCT,
    _CONTEXT_TIER_200K_ORANGE_PCT,
    _CONTEXT_TIER_200K_RED_PCT,
    _CONTEXT_TIER_1000K_CRITICAL_PCT,
    _CONTEXT_TIER_1000K_ORANGE_PCT,
    _CONTEXT_TIER_1000K_RED_PCT,
    TierConfig,
    TierThresholds,
    classify_context,
    is_critical,
    is_red,
)

logger = logging.getLogger(__name__)

# Subdirectory (under the daemon untracked dir) that holds the per-session
# sidecar files. Kept distinct from the supervisor's own decision.log so the
# sensor output (daemon-written) and actuator output (supervisor-written)
# never collide.
_SIDECAR_SUBDIR = "context-sidecar"

# Bumped when the on-disk schema changes in a way a reader must notice.
_SCHEMA_VERSION = 1

# Filename stem used when the Status payload carries no usable session id.
_SESSION_ID_FALLBACK = "unknown"

# Any character outside this safe set is replaced with '_' before the session
# id is used as a filename component (session ids are normally UUIDs, but we
# never trust an external value to be path-safe).
_UNSAFE_SESSION_CHARS = re.compile(r"[^A-Za-z0-9_.-]")


class ContextSidecarHandler(Handler):
    """Write an observe-only context-state sidecar for the PTY supervisor."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.CONTEXT_SIDECAR,
            priority=Priority.CONTEXT_SIDECAR,
            terminal=False,
            tags=[HandlerTag.STATUS, HandlerTag.NON_TERMINAL],
            shares_options_with=HandlerID.MODEL_CONTEXT.config_key,
        )
        # Per-tier context thresholds — overridable via config options, and
        # inherited from model_context via shares_options_with so the sidecar's
        # "red" is defined by exactly the same numbers the status line uses.
        self._200k_orange_pct: int = _CONTEXT_TIER_200K_ORANGE_PCT
        self._200k_red_pct: int = _CONTEXT_TIER_200K_RED_PCT
        self._200k_critical_pct: int = _CONTEXT_TIER_200K_CRITICAL_PCT
        self._1000k_orange_pct: int = _CONTEXT_TIER_1000K_ORANGE_PCT
        self._1000k_red_pct: int = _CONTEXT_TIER_1000K_RED_PCT
        self._1000k_critical_pct: int = _CONTEXT_TIER_1000K_CRITICAL_PCT
        # Monotonic per-writer sequence number. Resets to 0 when the daemon
        # restarts (new writer_pid); readers pair it with writer_pid + ts to
        # detect a fresh writer rather than treating a reset as staleness.
        self._seq: int = 0

    def get_default_enabled(self) -> bool:
        """Opt-in: dormant unless a supervisor is watching the sidecar."""
        return False

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Run on every status event (writing is cheap and idempotent)."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Write the context-state sidecar; render/inject nothing.

        Args:
            hook_input: Status event input with model and context_window data

        Returns:
            HookResult with an empty context (this handler is display-silent)
        """
        ctx_data = hook_input.get("context_window", {})
        used_pct = float(ctx_data.get("used_percentage") or 0)
        window_size = int(ctx_data.get("context_window_size") or 0)

        model_data = hook_input.get("model", {})
        model_id = str(model_data.get("id", ""))

        session_id = str(hook_input.get(HookInputField.SESSION_ID, "") or "")

        cfg = self._build_tier_config()
        tier = classify_context(used_pct, window_size, cfg)

        self._seq += 1
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "red": is_red(used_pct, window_size, cfg),
            "critical": is_critical(used_pct, window_size, cfg),
            "tier": tier.value,
            "pct": used_pct,
            "window_size": window_size,
            "cost_usd": self._read_cost(hook_input),
            "session_id": session_id,
            "model_id": model_id,
            "ts": self._now(),
            "seq": self._seq,
            "writer_pid": os.getpid(),
        }

        self._write_sidecar(session_id, payload)
        return HookResult(context=[])

    def _read_cost(self, hook_input: dict[str, Any]) -> float | None:
        """Extract session cost in USD if the payload carries it, else None.

        The Status payload's ``cost.total_cost_usd`` is best-effort (not every
        Claude Code version sends it), so this is nullable by design — the
        supervisor treats a missing cost as "unknown", never as zero.
        """
        cost_data = hook_input.get("cost")
        if isinstance(cost_data, dict):
            total = cost_data.get("total_cost_usd")
            if total is not None:
                return float(total)
        return None

    def _write_sidecar(self, session_id: str, payload: dict[str, Any]) -> None:
        """Atomically write ``payload`` to the per-session sidecar file.

        Atomicity (tmp write + ``os.replace``) guarantees a concurrent reader
        never sees a half-written JSON document. Failures are logged, never
        silently swallowed, and never propagated into the status-line render.
        """
        try:
            target_dir = ProjectContext.daemon_untracked_dir() / _SIDECAR_SUBDIR
            target_dir.mkdir(parents=True, exist_ok=True)

            safe_stem = self._safe_session_stem(session_id)
            final_path = target_dir / f"{safe_stem}.json"
            tmp_path = target_dir / f".{safe_stem}.{os.getpid()}.tmp"

            tmp_path.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp_path, final_path)
        except RuntimeError as e:
            # ProjectContext not initialised (default-config / standalone
            # entry-point branch). Skip rather than fail the dispatch.
            logger.warning("Skipping context sidecar (no project context): %s", e)
        except OSError as e:
            logger.warning("Failed to write context sidecar: %s", e)

    def _safe_session_stem(self, session_id: str) -> str:
        """Return a filesystem-safe filename stem for the session id."""
        if not session_id:
            return _SESSION_ID_FALLBACK
        return _UNSAFE_SESSION_CHARS.sub("_", session_id)

    def _now(self) -> float:
        """Return the current epoch time (seam for deterministic tests)."""
        return time.time()

    def _build_tier_config(self) -> TierConfig:
        """Build a TierConfig from this handler's (possibly overridden) options.

        Mirrors ``ModelContextHandler._build_tier_config`` so both surfaces
        classify against identical thresholds (Plan 00135 Decision J).
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
        # Observe-only: writes nothing to the session and blocks nothing, so
        # there is no handler behaviour an agent needs to avoid fighting.
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="context sidecar handler test",
                command='echo "test"',
                description="Tests that the observe-only context sidecar handler runs",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Observe-only status handler - writes a sidecar, injects nothing",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
