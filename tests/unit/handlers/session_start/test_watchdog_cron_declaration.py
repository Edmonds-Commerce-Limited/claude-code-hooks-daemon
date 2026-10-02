"""The background-process watchdog is a standing job (Plan 00470 Task 2.4).

The owner's decision: the watchdog is a sensible safety net for a long-running
session, so every session gets it. This repository therefore declares it under
``persistent_crons`` beside the failsafe, and the declaration must carry the
canonical watchdog prompt byte for byte, so the assertor, the Stop enforcer and
the ``background_process_tracker`` advisory all hand the agent one text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import Config, PersistentCronConfig
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.post_tool_use.background_process_tracker import (
    watchdog_cron_prompt,
)
from claude_code_hooks_daemon.handlers.session_start.persistent_cron_assertor import (
    PersistentCronAssertorHandler,
)
from claude_code_hooks_daemon.utils.cron_enforcement import (
    SessionCron,
    cron_is_asserted,
    find_missing_crons,
)
from claude_code_hooks_daemon.utils.cron_tick import DaemonTick, TickKind, classify_tick

_REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def repo_config() -> Config:
    return Config.load_or_default(_REPO_ROOT / ".claude" / "hooks-daemon.yaml")


@pytest.fixture(autouse=True)
def _self_install(monkeypatch: pytest.MonkeyPatch) -> None:
    """This repository is a self-install, so its declared prompt names `bin/hooks-daemon`."""
    monkeypatch.setattr(ProjectContext, "self_install_mode", classmethod(lambda cls: True))


def _declared_watchdog(config: Config) -> PersistentCronConfig:
    jobs = [
        job
        for job in config.persistent_crons.active_jobs()
        if classify_tick(job.prompt) == DaemonTick(TickKind.WATCHDOG)
    ]
    assert len(jobs) == 1, "this repository declares the watchdog cron exactly once"
    return jobs[0]


class TestTheWatchdogIsDeclared:
    def test_the_declared_prompt_is_the_canonical_prompt(self, repo_config: Config) -> None:
        assert _declared_watchdog(repo_config).prompt.strip() == watchdog_cron_prompt()

    def test_the_schedule_is_off_the_hour_mark(self, repo_config: Config) -> None:
        minute = _declared_watchdog(repo_config).schedule.split()[0]
        assert minute != "0"

    def test_the_schedule_differs_from_every_other_declared_job(self, repo_config: Config) -> None:
        jobs = repo_config.persistent_crons.active_jobs()
        schedules = [job.schedule for job in jobs]
        assert len(schedules) == len(set(schedules))

    def test_it_is_not_host_restricted(self, repo_config: Config) -> None:
        assert not _declared_watchdog(repo_config).hosts


class TestTheDeclarationIsHeldForTheWholeSession:
    def test_the_assertor_re_states_it_at_session_start(
        self, monkeypatch: pytest.MonkeyPatch, repo_config: Config
    ) -> None:
        assertor = PersistentCronAssertorHandler()
        monkeypatch.setattr(assertor, "_load_config", lambda: repo_config)
        text = "\n".join(assertor.handle({}).context)
        assert "[tick:watchdog]" in text
        assert "harvest-background" in text

    def test_the_stop_enforcer_requires_it_when_absent(self, repo_config: Config) -> None:
        job = _declared_watchdog(repo_config)
        assert job in find_missing_crons(repo_config.persistent_crons.active_jobs(), [])

    def test_a_cron_pasted_from_the_advisory_satisfies_the_enforcer(
        self, repo_config: Config
    ) -> None:
        job = _declared_watchdog(repo_config)
        created = [SessionCron("c1", job.schedule, watchdog_cron_prompt())]
        assert cron_is_asserted(job, created)


class TestAnIdleTickIsANoOp:
    def test_the_prompt_does_not_tell_the_agent_to_delete_the_cron(self) -> None:
        prompt = watchdog_cron_prompt()
        assert "Delete this cron" not in prompt
        assert "once no backgrounded work remains" not in prompt

    def test_the_prompt_says_an_idle_tick_is_a_no_op(self) -> None:
        prompt = watchdog_cron_prompt()
        assert "no-op" in prompt
        assert "Do NOT delete this cron" in prompt
