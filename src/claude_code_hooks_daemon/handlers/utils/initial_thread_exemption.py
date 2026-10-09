"""Shared gate: only a session's initial thread holds the declared crons (Plan 00470 Task 6.4).

``persistent_cron_assertor``, ``cron_stop_enforcer`` and
``cron_subagent_stop_enforcer`` all ask the same question -- is this session a
thread opened LATER in a Claude Code session whose initial thread already holds
the crons? -- so the answer is asked here once. The grouping itself lives in
:mod:`claude_code_hooks_daemon.utils.session_thread_group`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.config.models import PersistentCronsConfig
from claude_code_hooks_daemon.utils.session_thread_group import (
    PROC_ROOT,
    default_registry_path,
    initial_thread_holder_elsewhere,
)


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
    ) -> str | None:
        """The initial thread's session id when this session is a later thread, else None."""
        return initial_thread_holder_elsewhere(
            hook_input,
            initial_thread_only=crons.initial_thread_only,
            registry_path=self._thread_groups_path(),
            proc_root=self._proc_root(),
        )


def render_non_holder_note(holder_session_id: str) -> list[str]:
    """What a later thread is told: it holds no declared crons, and why."""
    return [
        "DECLARED PERSISTENT CRONS: this thread holds none.",
        "",
        "This thread was opened later in a Claude Code session whose initial thread "
        f"(session {holder_session_id}) holds the project's declared persistent crons. "
        "Create no CronCreate job for them here: a second copy would fire every tick "
        "twice. Do this only if the user explicitly tells you to.",
        "",
        "The project can make every thread hold them with "
        "`persistent_crons.initial_thread_only: false`.",
    ]
