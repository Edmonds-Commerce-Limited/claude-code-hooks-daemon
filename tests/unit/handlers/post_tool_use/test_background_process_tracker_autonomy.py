"""The background-process advisory drops its cron advice where autonomy is off (Plan 00498).

The tracker PROTECTS (it records the process and points at `harvest-background`)
and, separately, ASKS FOR A CRON (the watchdog). Only the second is work-driving,
so the handler is not gated as a whole: the record, the harvest advice and the
process-group reap advice survive everywhere, and the cron advice goes where the
project's `autonomy:` config turns autonomy off.
"""

from __future__ import annotations

import pytest
from tests.support.autonomy import pin_container_containers_only, pin_desktop_containers_only

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.handlers.post_tool_use.background_process_tracker import (
    BackgroundProcessTrackerHandler,
)


def _advice(monkeypatch: pytest.MonkeyPatch) -> str:
    handler = BackgroundProcessTrackerHandler()
    monkeypatch.setattr(handler, "_resolve_state_file", lambda: None)
    chain = HandlerChain()
    chain.add(handler)
    event = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "npm run dev", "run_in_background": True},
        "session_id": "s1",
    }
    result = chain.execute(event).result
    assert result.decision is Decision.ALLOW
    return "\n".join(result.context)


def test_a_desktop_gets_the_harvest_advice_and_no_cron(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_desktop_containers_only(monkeypatch)
    text = _advice(monkeypatch)
    assert "harvest-background" in text
    assert "kill -- -<pgid>" in text
    assert "KEEP_RUNNING_BECAUSE" in text
    assert "CronCreate" not in text
    assert "CronList" not in text
    assert "[tick:watchdog]" not in text


def test_a_container_still_gets_the_watchdog_cron_advice(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_container_containers_only(monkeypatch)
    text = _advice(monkeypatch)
    assert "CronCreate" in text
    assert "[tick:watchdog]" in text
