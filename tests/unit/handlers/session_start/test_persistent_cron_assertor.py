"""Unit tests for the persistent-cron assertor (Plan 00384).

The daemon cannot READ a session's crons — they live in Claude Code's memory,
not on disk — so it cannot verify anything. It asserts by INSTRUCTION: it
states what the project declared and tells the agent to reconcile via
``CronList``. That is the same contract the failsafe recovery cron advisory
already works under, and the tests below pin it honestly rather than implying
the daemon knows what is running.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import (
    Config,
    PersistentCronConfig,
    PersistentCronsConfig,
)
from claude_code_hooks_daemon.constants import HandlerTag
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.session_start.persistent_cron_assertor import (
    PersistentCronAssertorHandler,
)
from claude_code_hooks_daemon.utils.cron_pause import (
    CRON_PAUSES_FILENAME,
    CronPause,
    record_pause,
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


class TestAJobPausedForThisSessionIsNotReAsked:
    """Ledger 00422 N4: a SessionStart inside the SAME session (resume, clear,
    compact) must not tell the agent to re-create a job it was told to pause.
    A new session has a new id, so the pause cannot follow it there."""

    _SESSION = "paused-session"

    def _handler_with_pause(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *jobs: PersistentCronConfig
    ) -> PersistentCronAssertorHandler:
        handler = _handler(monkeypatch, _config(*jobs))
        path = tmp_path / CRON_PAUSES_FILENAME
        monkeypatch.setattr(handler, "_pauses_path", lambda: path)
        record_pause(
            path,
            CronPause(
                job_id=_JOB.id,
                session_id=self._SESSION,
                reason="owner stopped it",
                recorded_at=time.time(),
            ),
            now=time.time(),
        )
        return handler

    def test_the_paused_job_is_not_in_the_create_list(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        second = PersistentCronConfig(id="second-job", schedule="41 * * * *", prompt="q")
        handler = self._handler_with_pause(monkeypatch, tmp_path, _JOB, second)

        context = handler.handle({"session_id": self._SESSION}).context

        declared = context[context.index("DECLARED JOB:") :]
        assert not any(_JOB.schedule in line for line in declared)
        assert any("second-job" in line for line in declared)

    def test_the_pause_itself_is_stated_with_reason_and_expiry(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        handler = self._handler_with_pause(monkeypatch, tmp_path, _JOB)

        context = "\n".join(handler.handle({"session_id": self._SESSION}).context)

        assert _JOB.id in context
        assert "owner stopped it" in context
        assert "expires" in context
        assert "Do NOT re-create" in context

    def test_a_new_session_is_asked_to_create_it_again(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        handler = self._handler_with_pause(monkeypatch, tmp_path, _JOB)

        context = "\n".join(handler.handle({"session_id": "a-brand-new-session"}).context)

        assert _JOB.schedule in context
        assert "owner stopped it" not in context


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


class TestTheHandlerIsTagged:
    """Plan 00412: this handler shipped in v3.64.0 carrying NO tags at all.

    That is not cosmetic. Tags are how a handler is bucketed for the
    config-optimisation review and for any tag-scoped query, so an untagged
    handler is invisible to exactly the surfaces meant to surface it — and it
    fails silently, which is why nobody noticed for a release.

    The v3.64.0 config-changes manifest describes it as "PLANNING tagged", so
    the DOCUMENTATION was right and the code was wrong. Worth stating, because
    the tempting repair was to correct the manifest to match the code, which
    would have written the defect down as intended behaviour.
    """

    def test_it_carries_tags(self) -> None:
        assert PersistentCronAssertorHandler().tags, "handler declares no tags at all"

    @pytest.mark.parametrize(
        "expected",
        [HandlerTag.ADVISORY, HandlerTag.PLANNING, HandlerTag.NON_TERMINAL, HandlerTag.WORKFLOW],
    )
    def test_it_carries_the_tags_its_siblings_do(self, expected: HandlerTag) -> None:
        """Matched to `recovery_cron_advisor`, the closest analogue.

        That handler is also a cron advisory that reports rather than verifies,
        and it carries WORKFLOW, PLANNING, ADVISORY and NON_TERMINAL.
        """
        assert expected in PersistentCronAssertorHandler().tags


class TestTheDeclaredPromptCarriesItsTickSentinel:
    """Plan 00388 option 2': the prompt the agent pastes is the daemon's text,
    so the daemon adds the line that lets a later tick be told from the owner.
    Without it an `issue-sdlc` tick wiped the `[awaiting-human]` marker."""

    def test_the_job_prompt_is_led_by_its_sentinel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        context = _handler(monkeypatch, _config(_JOB)).handle({}).context
        prompt_start = context.index("    prompt:") + 1
        assert context[prompt_start].strip() == "[tick:job:gh-issue-sdlc]"
        assert context[prompt_start + 1].strip() == _JOB.prompt

    def test_a_pause_leaves_the_other_jobs_sentinel_in_place(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Ledger 00422 N4's pause filter and Plan 00388's sentinel both shape
        this advisory, and they landed on separate branches: the job still
        asked for keeps its sentinel, and the paused one gains no create
        instruction."""
        second = PersistentCronConfig(id="second-job", schedule="41 * * * *", prompt="q")
        handler = _handler(monkeypatch, _config(_JOB, second))
        path = tmp_path / CRON_PAUSES_FILENAME
        monkeypatch.setattr(handler, "_pauses_path", lambda: path)
        now = time.time()
        record_pause(
            path,
            CronPause(job_id=_JOB.id, session_id="s", reason="owner stopped it", recorded_at=now),
            now=now,
        )

        context = handler.handle({"session_id": "s"}).context

        assert "[tick:job:second-job]" in [line.strip() for line in context]
        assert "[tick:job:gh-issue-sdlc]" not in "\n".join(context)
        assert "owner stopped it" in "\n".join(context)
