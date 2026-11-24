"""Whether a UserPromptSubmit prompt is a machine turn rather than a human one.

A failsafe-recovery cron tick, a declared persistent-cron tick, a goal-injection
line or a ccy-supervisor typed line all arrive as UserPromptSubmit events. None
is a human prompt, so a handler that paces itself on human prompts (standing
authorisations, the owner directives register) must neither count nor answer
them. Claude Code exposes no automated-vs-human flag on the event, so the test
is a small set of STABLE, self-authored markers.
"""

from __future__ import annotations

from typing import Final

from claude_code_hooks_daemon.utils import ccy_supervisor
from claude_code_hooks_daemon.utils.cron_tick import classify_tick

FAILSAFE_RECOVERY_MARKER: Final[str] = "FAILSAFE RECOVERY CHECK"
# The supervisor's provenance prefix has no closing bracket (see
# ``ccy_supervisor.CCY_SUPERVISOR_MARKER``): a bracketed literal would miss
# every timestamped nudge.
AUTOMATED_PROMPT_MARKERS: Final[tuple[str, ...]] = (
    FAILSAFE_RECOVERY_MARKER,
    ccy_supervisor.CCY_SUPERVISOR_MARKER,
)


def is_automated_prompt(prompt: str) -> bool:
    """True when ``prompt`` carries a known machine-origin marker.

    Any daemon cron tick counts, not only the failsafe one: the watchdog and
    every declared ``persistent_crons`` job carry a tick sentinel too
    (Plan 00388).
    """
    if classify_tick(prompt) is not None:
        return True
    return any(marker in prompt for marker in AUTOMATED_PROMPT_MARKERS)
