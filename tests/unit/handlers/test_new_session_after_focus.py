"""A new session after a focused one runs normally (Plan 00501, focus criterion).

Focus is keyed by session id and has session lifetime, so its entry is still in
the registry when the human starts a NEW session. The new session must get the
normal behaviour regardless: every real work-driving handler is consulted by the
real chain, and a declared cron tick is delivered. The focused session's own
id, in the same registry, is still held off both, which proves the entry is live
and the new session's normal behaviour is not a missing mode.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import pytest
from tests.support.autonomy import focus_entry, pin_container_containers_only, pin_session_modes
from tests.unit.handlers.test_autonomy_drivers import _CLASSES, EXPECTED_DRIVERS

from claude_code_hooks_daemon.config.models import (
    Config,
    PersistentCronConfig,
    PersistentCronsConfig,
)
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.handlers.user_prompt_submit.failsafe_cron_blockage_suppressor import (
    FailsafeCronBlockageSuppressorHandler,
)
from claude_code_hooks_daemon.utils.cron_enforcement import declared_tick_prompt

_FOCUSED: Final[str] = "session-that-was-focused"
_NEW: Final[str] = "session-started-after-it"
_JOB: Final[PersistentCronConfig] = PersistentCronConfig(
    id="issue-sdlc", schedule="23 * * * *", prompt="Run the issue loop."
)


@pytest.fixture(autouse=True)
def _focused_earlier_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Autonomy is allowed here, and an earlier session's focus is still live."""
    pin_container_containers_only(monkeypatch)
    pin_session_modes(monkeypatch, tmp_path, focus_entry(_FOCUSED))


def _times_consulted(name: str, session_id: str, monkeypatch: pytest.MonkeyPatch) -> int:
    """How many times the real chain asked the real driver ``name`` whether it matches."""
    handler = _CLASSES[name]()
    asked: list[dict[str, Any]] = []

    def record(hook_input: dict[str, Any]) -> bool:
        asked.append(hook_input)
        return False

    monkeypatch.setattr(handler, "matches", record)
    chain = HandlerChain()
    chain.add(handler)
    chain.execute({"hook_event_name": "Any", "session_id": session_id})
    return len(asked)


@pytest.mark.parametrize("name", sorted(EXPECTED_DRIVERS))
def test_every_driver_runs_for_the_new_session(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _times_consulted(name, _NEW, monkeypatch) == 1


@pytest.mark.parametrize("name", sorted(EXPECTED_DRIVERS))
def test_the_focused_session_still_skips_it(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _times_consulted(name, _FOCUSED, monkeypatch) == 0


def _suppressor() -> FailsafeCronBlockageSuppressorHandler:
    handler = FailsafeCronBlockageSuppressorHandler()
    handler._config_loader = lambda: Config(
        persistent_crons=PersistentCronsConfig(enabled=True, jobs=[_JOB])
    )
    return handler


def _tick(session_id: str) -> dict[str, Any]:
    return {"prompt": declared_tick_prompt(_JOB), "session_id": session_id}


def test_a_declared_tick_is_delivered_to_the_new_session() -> None:
    result = _suppressor().handle(_tick(_NEW))
    assert result.decision is Decision.ALLOW
    assert result.context == []


def test_the_focused_session_still_drops_the_tick() -> None:
    assert _suppressor().handle(_tick(_FOCUSED)).decision is Decision.DENY
