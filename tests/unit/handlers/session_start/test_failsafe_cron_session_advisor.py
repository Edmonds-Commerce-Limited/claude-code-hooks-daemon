"""Tests for the failsafe cron's SessionStart counterpart (Plan 00394, option 2).

The failsafe recovery cron is the net that resumes a session stalled by a rate
limit, a usage limit or an API error. Its only advisory was a PostToolUse
handler firing on a plan-lifecycle moment, so a session got the net from its
first plan write -- a Q&A session, a review or an ``issue-sdlc`` tick that
stalled before writing a plan had none, and nothing said so.
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
from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.post_tool_use.recovery_cron_advisor import (
    CANONICAL_CRON_PROMPT,
    RecoveryCronAdvisorHandler,
)
from claude_code_hooks_daemon.handlers.session_start.failsafe_cron_session_advisor import (
    FailsafeCronSessionAdvisorHandler,
)
from claude_code_hooks_daemon.handlers.session_start.persistent_cron_assertor import (
    PersistentCronAssertorHandler,
)
from claude_code_hooks_daemon.utils.cron_enforcement import SessionCron, cron_is_asserted

_REPO_ROOT = Path(__file__).resolve().parents[4]

_DECLARED_FAILSAFE = PersistentCronConfig(
    id="failsafe-recovery",
    schedule="47 * * * *",
    prompt=CANONICAL_CRON_PROMPT,
)


class _RootedFailsafeCronSessionAdvisorHandler(FailsafeCronSessionAdvisorHandler):
    """Test double declaring `_workspace_root`, which the handler reads through
    `getattr` -- the same shape `test_persistent_cron_assertor` uses."""

    def __init__(self, root: Path) -> None:
        super().__init__()
        self._workspace_root = root


def _handler(monkeypatch: pytest.MonkeyPatch, config: Config) -> FailsafeCronSessionAdvisorHandler:
    handler = FailsafeCronSessionAdvisorHandler()
    monkeypatch.setattr(handler, "_load_config", lambda: config)
    return handler


def _new_session(tmp_path: Path) -> dict[str, Any]:
    """A SessionStart whose transcript is still empty: a genuinely new session."""
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("", encoding="utf-8")
    return {"hook_event_name": "SessionStart", "transcript_path": str(transcript)}


def _resumed_session(tmp_path: Path) -> dict[str, Any]:
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("x" * 4096, encoding="utf-8")
    return {"hook_event_name": "SessionStart", "transcript_path": str(transcript)}


def _recovery_advisor_disabled() -> Config:
    return Config.model_validate(
        {"handlers": {"post_tool_use": {"recovery_cron_advisor": {"enabled": False}}}}
    )


def _failsafe_declared(*, section_enabled: bool = True) -> Config:
    return Config(
        persistent_crons=PersistentCronsConfig(enabled=section_enabled, jobs=[_DECLARED_FAILSAFE])
    )


class TestASessionWithNoPlanWorkIsStillCovered:
    """Task 2.1: the gap was a session that never touches a plan file."""

    def test_a_new_session_is_advised(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        handler = _handler(monkeypatch, Config())
        assert handler.matches(_new_session(tmp_path)) is True

    def test_the_advice_carries_the_canonical_prompt_verbatim(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        result = _handler(monkeypatch, Config()).handle(_new_session(tmp_path))
        assert result.decision == Decision.ALLOW
        assert CANONICAL_CRON_PROMPT in "\n".join(result.context)

    def test_the_advice_reconciles_before_creating(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Task 2.3: every surface that speaks must say CronList first, so a
        second surface in one session can never produce a second cron."""
        text = "\n".join(_handler(monkeypatch, Config()).handle(_new_session(tmp_path)).context)
        assert text.index("CronList") < text.index("CronCreate")
        assert "ONLY IF none" in text
        assert "EXACTLY ONE" in text

    def test_the_advice_never_claims_the_cron_is_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The daemon cannot read session memory. Claiming absence is a claim
        it cannot support, and the agent would act on it with a duplicate."""
        text = "\n".join(_handler(monkeypatch, Config()).handle(_new_session(tmp_path)).context)
        assert "is missing" not in text.lower()


class TestItStaysSilentWhereItHasNothingToAdd:
    def test_a_resumed_session_keeps_its_crons(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        handler = _handler(monkeypatch, Config())
        assert handler.matches(_resumed_session(tmp_path)) is False

    def test_it_follows_the_recovery_cron_advisor_switch(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """One switch, not two: a project that turned the failsafe cron's
        advisory off must not start hearing about it at every session start."""
        handler = _handler(monkeypatch, _recovery_advisor_disabled())
        assert handler.matches(_new_session(tmp_path)) is False

    def test_a_declared_failsafe_job_leaves_it_to_the_assertor(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """persistent_cron_assertor already states a declared job at session
        start; two SessionStart surfaces naming one cron is noise."""
        handler = _handler(monkeypatch, _failsafe_declared())
        assert handler.matches(_new_session(tmp_path)) is False

    def test_a_declaration_under_a_disabled_section_does_not_count(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        handler = _handler(monkeypatch, _failsafe_declared(section_enabled=False))
        assert handler.matches(_new_session(tmp_path)) is True


class TestConfigFailuresFailTowardTheAdvice:
    def test_an_unloadable_config_still_advises(self, tmp_path: Path) -> None:
        """The advice is idempotent (CronList first), so speaking costs a few
        lines, while silence costs a session with no recovery net."""
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "hooks-daemon.yaml").write_text("{not: [yaml", encoding="utf-8")
        handler = _RootedFailsafeCronSessionAdvisorHandler(tmp_path)
        assert handler.matches(_new_session(tmp_path)) is True


class TestThisRepositoryHasExactlyOneFailsafeSurfaceAtSessionStart:
    """Task 2.3 against the real config. Option 1 declares the failsafe cron in
    this repository's persistent_crons, and option 2 adds a SessionStart
    advisory for every project. Both must describe ONE cron with ONE text."""

    @pytest.fixture
    def repo_config(self) -> Config:
        return Config.load_or_default(_REPO_ROOT / ".claude" / "hooks-daemon.yaml")

    def _declared_failsafe(self, config: Config) -> PersistentCronConfig:
        jobs = [
            job for job in config.persistent_crons.active_jobs() if "[tick:failsafe]" in job.prompt
        ]
        assert len(jobs) == 1, "this repository declares the failsafe cron exactly once"
        return jobs[0]

    def test_the_declared_prompt_is_the_canonical_prompt(self, repo_config: Config) -> None:
        """Two copies of one prompt drift. The declaration must be the
        canonical text, so the assertor, the Stop enforcer and the PostToolUse
        advisory all hand the agent the same bytes."""
        declared = self._declared_failsafe(repo_config).prompt
        assert declared.strip() == CANONICAL_CRON_PROMPT

    def test_the_session_advisor_is_silent_here(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, repo_config: Config
    ) -> None:
        handler = _handler(monkeypatch, repo_config)
        assert handler.matches(_new_session(tmp_path)) is False

    def test_the_assertor_renders_it_without_a_second_identity(
        self, monkeypatch: pytest.MonkeyPatch, repo_config: Config
    ) -> None:
        assertor = PersistentCronAssertorHandler()
        monkeypatch.setattr(assertor, "_load_config", lambda: repo_config)
        text = "\n".join(assertor.handle({}).context)
        assert "[tick:failsafe]" in text
        assert "[tick:job:" + self._declared_failsafe(repo_config).id not in text

    def test_a_cron_made_from_any_surface_satisfies_the_stop_enforcer(
        self, repo_config: Config
    ) -> None:
        """Whichever surface the agent copied from, the result is the one
        cron the enforcer is looking for -- never a reason to make another."""
        job = self._declared_failsafe(repo_config)
        created = [SessionCron("c1", job.schedule, CANONICAL_CRON_PROMPT)]
        assert cron_is_asserted(job, created)


class TestWiring:
    def test_identity(self) -> None:
        handler = FailsafeCronSessionAdvisorHandler()
        assert handler.name == HandlerID.FAILSAFE_CRON_SESSION_ADVISOR.display_name
        assert handler.priority == Priority.FAILSAFE_CRON_SESSION_ADVISOR
        assert handler.terminal is False

    def test_it_is_an_advisory(self) -> None:
        assert HandlerTag.ADVISORY in FailsafeCronSessionAdvisorHandler().tags

    def test_its_default_matches_the_recovery_cron_advisor(self) -> None:
        assert (
            FailsafeCronSessionAdvisorHandler().get_default_enabled()
            is RecoveryCronAdvisorHandler().get_default_enabled()
        )

    def test_it_documents_itself(self) -> None:
        guidance = FailsafeCronSessionAdvisorHandler().get_claude_md()
        assert guidance is not None
        assert "failsafe_cron_session_advisor" in guidance

    def test_it_has_an_acceptance_test(self) -> None:
        assert FailsafeCronSessionAdvisorHandler().get_acceptance_tests()
