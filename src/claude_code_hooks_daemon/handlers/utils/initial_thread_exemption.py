"""Shared gate: only a session's initial thread holds the declared crons (Plan 00470 Task 6.4).

``persistent_cron_assertor``, ``cron_stop_enforcer``,
``cron_subagent_stop_enforcer`` and ``usage_pause_gate`` all ask the same
question -- is this session a thread opened LATER in a Claude Code session whose
initial thread holds the crons? -- so the answer is asked here once. The
grouping itself lives in :mod:`claude_code_hooks_daemon.utils.session_thread_group`.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.config.models import PersistentCronConfig, PersistentCronsConfig
from claude_code_hooks_daemon.utils.session_thread_group import (
    PROC_ROOT,
    OtherHolder,
    default_registry_path,
    initial_thread_holder_elsewhere,
)

#: A verdict is reused only within one chain's matches() then handle().
_VERDICT_TTL_SECONDS: Final[float] = 2.0


class InitialThreadExemption:
    """Mixin for the handlers that demand or declare ``persistent_crons``."""

    def _thread_groups_path(self) -> Path | None:
        """Where the group-to-holder map persists (overridden in tests)."""
        return default_registry_path()

    def _proc_root(self) -> Path:
        """The ``/proc`` mount the ancestry walk reads (overridden in tests)."""
        return PROC_ROOT

    def _exempt_holder(
        self, hook_input: dict[str, Any], crons: PersistentCronsConfig
    ) -> OtherHolder | None:
        """The other holder when this session is a later thread, else None.

        One chain asks twice (``matches`` then ``handle``); the verdict for the
        same payload object is kept briefly so the walk and the registry are
        read once. The payload itself is held, so its identity cannot be reused.
        """
        cached: tuple[dict[str, Any], float, OtherHolder | None] | None = getattr(
            self, "_thread_verdict", None
        )
        now = time.monotonic()
        if cached is not None and cached[0] is hook_input and now < cached[1]:
            return cached[2]
        verdict = initial_thread_holder_elsewhere(
            hook_input,
            initial_thread_only=crons.initial_thread_only,
            registry_path=self._thread_groups_path(),
            proc_root=self._proc_root(),
        )
        self._thread_verdict = (hook_input, now + _VERDICT_TTL_SECONDS, verdict)
        return verdict

    def _jobs_held_by_session(
        self,
        hook_input: dict[str, Any],
        crons: PersistentCronsConfig,
        jobs: list[PersistentCronConfig],
    ) -> list[PersistentCronConfig]:
        """``jobs`` for a session that holds the crons, none for a later thread."""
        if jobs and self._exempt_holder(hook_input, crons) is not None:
            return []
        return jobs


def render_non_holder_note(holder_session_id: str | None) -> list[str]:
    """What a later thread is told: it holds no declared crons, and why."""
    holder = f" (session {holder_session_id})" if holder_session_id else ""
    return [
        "DECLARED PERSISTENT CRONS: this thread holds none.",
        "",
        "This thread was opened later in a Claude Code session whose initial thread"
        f"{holder} holds the project's declared persistent crons. "
        "Create no CronCreate job for them here: a second copy would fire every tick "
        "twice. Do this only if the user explicitly tells you to.",
        "",
        "The project can make every thread hold them with "
        "`persistent_crons.initial_thread_only: false`.",
    ]
