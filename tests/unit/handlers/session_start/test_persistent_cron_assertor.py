"""Unit tests for the persistent-cron assertor (Plan 00384).

The daemon cannot READ a session's crons — they live in Claude Code's memory,
not on disk — so it cannot verify anything. It asserts by INSTRUCTION: it
states what the project declared and tells the agent to reconcile via
``CronList``. That is the same contract the failsafe recovery cron advisory
already works under, and the tests below pin it honestly rather than implying
the daemon knows what is running.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import (
    Config,
    PersistentCronConfig,
    PersistentCronsConfig,
)
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.session_start.persistent_cron_assertor import (
    PersistentCronAssertorHandler,
)


class _RootedPersistentCronAssertorHandler(PersistentCronAssertorHandler):
    """Test double declaring `_workspace_root` so it is a known instance attribute.

    The handler reads it dynamically via `getattr(self, "_workspace_root", None)`,
    so assigning it inside `__init__` mirrors that rather than reaching into the
    instance from outside — the same shape `test_tool_disable_advisor` uses.
    """

    def __init__(self, root: Path) -> None:
        super().__init__()
        self._workspace_root = root


def _handler(monkeypatch: pytest.MonkeyPatch, config: Config) -> PersistentCronAssertorHandler:
    handler = PersistentCronAssertorHandler()
    monkeypatch.setattr(handler, "_load_config", lambda: config)
    return handler


def _config(*jobs: PersistentCronConfig, enabled: bool = True) -> Config:
    return Config(persistent_crons=PersistentCronsConfig(enabled=enabled, jobs=list(jobs)))


_JOB = PersistentCronConfig(
    id="gh-issue-sdlc",
    schedule="23 * * * *",
    prompt="Invoke the issue-sdlc skill and follow it exactly.",
    description="One GitHub issue through the full SDLC",
)


class TestItStaysSilentUnlessAsked:
    def test_a_project_with_no_config_is_not_advised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handler = _handler(monkeypatch, Config())
        assert handler.matches({}) is False

    def test_declared_jobs_with_the_section_off_are_not_advised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One switch, not two: the config section is the master control, so a
        project that declared a job but never switched the section on is not
        quietly opted in."""
        handler = _handler(monkeypatch, _config(_JOB, enabled=False))
        assert handler.matches({}) is False

    def test_an_all_disabled_job_list_is_not_advised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        disabled = PersistentCronConfig(id="off", schedule="7 * * * *", prompt="p", enabled=False)
        handler = _handler(monkeypatch, _config(disabled))
        assert handler.matches({}) is False

    def test_an_unreadable_config_degrades_to_silence(self, tmp_path: Path) -> None:
        """A config the daemon already reports as invalid must not raise out of
        the SessionStart chain and take every other advisory down with it."""
        handler = _RootedPersistentCronAssertorHandler(tmp_path)
        assert handler.matches({}) is False


class TestWhatItTellsTheAgent:
    @pytest.fixture
    def context(self, monkeypatch: pytest.MonkeyPatch) -> str:
        handler = _handler(monkeypatch, _config(_JOB))
        result = handler.handle({})
        assert result.decision is Decision.ALLOW
        return "\n".join(result.context)

    def test_it_carries_the_schedule_and_the_prompt_verbatim(self, context: str) -> None:
        """The agent cannot create a job it was not given in full."""
        assert "23 * * * *" in context
        assert "Invoke the issue-sdlc skill and follow it exactly." in context

    def test_it_names_the_job_id_so_cronlist_can_be_matched(self, context: str) -> None:
        assert "gh-issue-sdlc" in context

    def test_it_instructs_a_cronlist_check_before_creating(self, context: str) -> None:
        """Without this the advisory would stack a duplicate job every session,
        which is the failure the failsafe cron advisory already learned."""
        assert "CronList" in context
        assert "CronCreate" in context

    def test_it_says_why_the_job_has_to_be_recreated(self, context: str) -> None:
        """A reader who does not know crons are session-only will assume this
        advisory is noise and stop acting on it."""
        lowered = context.lower()
        assert "session" in lowered
        assert "durable" in lowered

    def test_it_does_not_claim_to_know_what_is_running(self, context: str) -> None:
        """The daemon cannot see session memory. Wording that implies it
        checked would be a false claim, and the agent would trust it."""
        lowered = context.lower()
        for false_claim in ("is missing", "is not running", "no cron found"):
            assert false_claim not in lowered


class TestEveryDeclaredJobIsReported:
    def test_two_jobs_both_appear(self, monkeypatch: pytest.MonkeyPatch) -> None:
        second = PersistentCronConfig(id="second-job", schedule="41 * * * *", prompt="q")
        handler = _handler(monkeypatch, _config(_JOB, second))

        context = "\n".join(handler.handle({}).context)

        assert "gh-issue-sdlc" in context
        assert "second-job" in context
        assert "41 * * * *" in context

    def test_a_disabled_job_is_omitted_from_a_mixed_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        off = PersistentCronConfig(
            id="dormant-job", schedule="41 * * * *", prompt="q", enabled=False
        )
        handler = _handler(monkeypatch, _config(_JOB, off))

        context = "\n".join(handler.handle({}).context)

        assert "gh-issue-sdlc" in context
        assert "dormant-job" not in context


class TestHandlerWiring:
    def test_it_is_enabled_by_default(self) -> None:
        """Inertness comes from the config section, not from a second switch —
        a project that declares jobs AND enables the section would otherwise
        get nothing and have no way to tell why."""
        assert PersistentCronAssertorHandler().get_default_enabled() is True

    def test_handle_with_nothing_declared_returns_an_empty_allow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A direct call bypassing ``matches`` must still degrade safely."""
        handler = _handler(monkeypatch, Config())
        result: Any = handler.handle({})
        assert result.decision is Decision.ALLOW
        assert result.context == []
