"""The shared body of the two branch pool ladder handlers (Plan 00619).

The PreToolUse advisor and the UserPromptSubmit prompt handler differ only in the
event they are wired to and the result type they return. Everything else (the
project root, the cache and throttle wiring, and the rule that nothing here may
raise) lives once, here, so a change to it cannot reach one handler and miss the
other.

Context only: nothing in this mixin denies, and a failure of any kind is silence.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants import HookInputField
from claude_code_hooks_daemon.core.branch_ladder import (
    PRESSURE_CACHE,
    SESSION_THROTTLE,
    LadderThrottle,
    PressureCache,
    ladder_notice,
)
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

logger = logging.getLogger(__name__)


class BranchLadderSurface:
    """State and the ``matches`` body of a handler that says how full the branch pools are."""

    def __init__(self, **handler_kwargs: Any) -> None:
        # Cooperative: the handler base that follows this mixin in the MRO takes the
        # handler's identity (id, priority, tags); this class adds only its own state.
        super().__init__(**handler_kwargs)
        self._branches: BranchesConfig = BranchesConfig()
        self._project_root_override: Path | None = None
        self._throttle: LadderThrottle = SESSION_THROTTLE
        self._cache: PressureCache = PRESSURE_CACHE
        self._due: list[str] = []

    def _project_root(self) -> Path:
        if self._project_root_override is not None:
            return self._project_root_override
        try:
            return ProjectContext.project_root()
        except RuntimeError:
            logger.debug("ProjectContext not initialised; reading branch pools from cwd")
            return Path.cwd()

    def ladder_matches(self, hook_input: dict[str, Any]) -> bool:
        """True when a pool is at or above its warn level and the notice is due now.

        Never raises: this handler is context only, and under ``daemon.strict_mode``
        the chain turns a handler's exception into a deny of the whole call.
        """
        self._due = []
        try:
            session = hook_input.get(HookInputField.SESSION_ID)
            self._due = ladder_notice(
                self._project_root(),
                self._branches,
                session_id=session if isinstance(session, str) else None,
                throttle=self._throttle,
                cache=self._cache,
            )
        except Exception as exc:  # advisory only: never a deny, whatever the read does
            log_and_continue(
                logger,
                exc,
                reason="the branch pool ladder is context only; a failure is silence, not a deny",
                level=logging.WARNING,
            )
            self._due = []
        return bool(self._due)
