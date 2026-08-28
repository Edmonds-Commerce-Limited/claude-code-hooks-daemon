"""Tests for StandingAuthorisationsHandler (Plan 00223).

The handler replays authorisations a project's owner has actually recorded in
config. Two properties matter more than any of the mechanics, and both have
dedicated test classes below:

- **Nothing is authorised by default** (Plan 00223 Decision 3). The handler
  ships on so the options are discoverable; every entry ships off so the
  daemon never fabricates the consent its own text claims.
- **The text is a recorded request, never a countermand** (Decision 2). It
  must never tell the agent to disregard, ignore or override its
  instructions — that framing is both a worse prompt and a mechanism that
  should not exist.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.user_prompt_submit.standing_authorisations import (
    _SIGNAL_SUBDIR,
    _SIGNAL_SUFFIX,
    _SOURCE_REINFORCEMENT,
    AUTHORISATION_COMMIT_PUSH_CADENCE,
    AUTHORISATION_SUBAGENT_DELEGATION,
    AUTHORISATION_WORKFLOWS,
    SUPERVISOR_CHANNEL_HEADER,
    StandingAuthorisationsHandler,
    write_standing_auth_signal,
)

_MODULE = "claude_code_hooks_daemon.handlers.user_prompt_submit.standing_authorisations"

_PROMPT = "Please refactor the config loader and add tests for the new branch."


def _hook_input(prompt: str = _PROMPT) -> dict[str, Any]:
    return {"hook_event_name": "UserPromptSubmit", "prompt": prompt}


def _enable(handler: StandingAuthorisationsHandler, *ids: str) -> None:
    """Apply config options the way the registry does — via setattr."""
    handler._authorisations = [{"id": entry_id, "enabled": True} for entry_id in ids]


class TestInitialisation:
    def test_handler_identity_and_priority(self) -> None:
        handler = StandingAuthorisationsHandler()
        assert handler.handler_id == HandlerID.STANDING_AUTHORISATIONS
        assert handler.priority == Priority.STANDING_AUTHORISATIONS

    def test_handler_is_never_terminal(self) -> None:
        """An advisory that can end dispatch would be a bug."""
        assert StandingAuthorisationsHandler().terminal is False


class TestNothingIsAuthorisedByDefault:
    """Decision 3 — the mechanism ships on, every authorisation ships off."""

    def test_fresh_handler_emits_no_context(self) -> None:
        result = StandingAuthorisationsHandler().handle(_hook_input())
        assert result.context == []

    def test_fresh_handler_never_denies(self) -> None:
        result = StandingAuthorisationsHandler().handle(_hook_input())
        assert result.decision == Decision.ALLOW

    def test_every_builtin_entry_ships_disabled(self) -> None:
        """The default set exists to be discoverable, not to be active."""
        handler = StandingAuthorisationsHandler()
        assert handler._resolve_entries() == []

    def test_explicitly_disabled_entry_stays_silent(self) -> None:
        handler = StandingAuthorisationsHandler()
        handler._authorisations = [
            {"id": AUTHORISATION_SUBAGENT_DELEGATION, "enabled": False},
        ]
        assert handler.handle(_hook_input()).context == []


class TestEnablingAnAuthorisation:
    def test_enabled_entry_is_injected(self) -> None:
        handler = StandingAuthorisationsHandler()
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        assert handler.handle(_hook_input()).context

    def test_injected_text_names_where_it_is_configured(self) -> None:
        """It must be auditable and revocable, or it is not a recorded request."""
        handler = StandingAuthorisationsHandler()
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        text = " ".join(handler.handle(_hook_input()).context)
        assert "hooks-daemon.yaml" in text
        assert "standing_authorisations" in text

    def test_the_two_restrictions_are_independently_authorisable(self) -> None:
        """Authorising delegation says nothing about authorising workflows."""
        handler = StandingAuthorisationsHandler()
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        text = " ".join(handler.handle(_hook_input()).context).lower()
        assert "workflow" not in text

    def test_both_can_be_enabled_together(self) -> None:
        handler = StandingAuthorisationsHandler()
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION, AUTHORISATION_WORKFLOWS)
        assert len(handler.handle(_hook_input()).context) == 2

    def test_commit_push_cadence_text_names_the_practice(self) -> None:
        """The commit/push entry must name both halves and the backup rationale."""
        handler = StandingAuthorisationsHandler()
        _enable(handler, AUTHORISATION_COMMIT_PUSH_CADENCE)
        text = " ".join(handler.handle(_hook_input()).context).lower()
        assert "commit" in text
        assert "push" in text
        assert "backup" in text

    def test_all_three_can_be_enabled_together(self) -> None:
        handler = StandingAuthorisationsHandler()
        _enable(
            handler,
            AUTHORISATION_SUBAGENT_DELEGATION,
            AUTHORISATION_WORKFLOWS,
            AUTHORISATION_COMMIT_PUSH_CADENCE,
        )
        assert len(handler.handle(_hook_input()).context) == 3

    def test_unknown_entry_id_is_ignored_not_crashed(self) -> None:
        handler = StandingAuthorisationsHandler()
        _enable(handler, "no-such-authorisation")
        assert handler.handle(_hook_input()).context == []


class TestTextIsARecordedRequestNeverACountermand:
    """Decision 2 — the single most important property of this handler."""

    @pytest.mark.parametrize(
        "entry_id",
        [
            AUTHORISATION_SUBAGENT_DELEGATION,
            AUTHORISATION_WORKFLOWS,
            AUTHORISATION_COMMIT_PUSH_CADENCE,
        ],
    )
    def test_no_entry_tells_the_agent_to_disregard_instructions(self, entry_id: str) -> None:
        handler = StandingAuthorisationsHandler()
        _enable(handler, entry_id)
        text = " ".join(handler.handle(_hook_input()).context).lower()
        for forbidden in ("ignore", "disregard", "override", "overrule", "bypass"):
            assert forbidden not in text, f"{entry_id} text uses countermand word {forbidden!r}"

    @pytest.mark.parametrize(
        "entry_id",
        [
            AUTHORISATION_SUBAGENT_DELEGATION,
            AUTHORISATION_WORKFLOWS,
            AUTHORISATION_COMMIT_PUSH_CADENCE,
        ],
    )
    def test_every_entry_attributes_the_request_to_the_project(self, entry_id: str) -> None:
        handler = StandingAuthorisationsHandler()
        _enable(handler, entry_id)
        text = " ".join(handler.handle(_hook_input()).context).lower()
        assert "project" in text


class TestMatches:
    def test_matches_a_normal_prompt(self) -> None:
        assert StandingAuthorisationsHandler().matches(_hook_input()) is True

    def test_does_not_match_when_prompt_is_missing(self) -> None:
        assert StandingAuthorisationsHandler().matches({}) is False

    def test_does_not_match_a_non_string_prompt(self) -> None:
        assert StandingAuthorisationsHandler().matches({"prompt": 42}) is False


class _FakeClock:
    """A settable monotonic-ish clock for exercising the time-based cadence."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestCadence:
    """Plan 00283 — first full, then reinforce on 5 prompts OR 15 min.

    This SUPERSEDES Plan 00223's "decay never skips a prompt". The old property
    injected the short form on every single prompt; that was reliable but noisy,
    and it rode along on every automated failsafe-recovery tick. The reliability
    argument (a per-request system-prompt restriction needs an answer that
    survives compaction) is preserved by a DIFFERENT mechanism: the reinforcement
    still arrives many times per session, bounded to at most `prompt_interval`
    prompts or `interval_minutes` apart — a small, bounded silence, not the
    unbounded once-ever silence that made SessionStart injection fail.
    """

    def test_first_prompt_delivers_the_full_text(self) -> None:
        handler = StandingAuthorisationsHandler()
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        first = " ".join(handler.handle(_hook_input()).context)
        assert "without pausing to ask permission" in first

    def test_prompts_between_reinforcements_are_silent(self) -> None:
        """The whole point: no per-prompt spam between reinforcements."""
        handler = StandingAuthorisationsHandler()
        clock = _FakeClock()
        handler._clock = clock
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        handler.handle(_hook_input())  # first — full
        # The next (prompt_interval - 1) prompts, within the time window, are silent.
        for _ in range(handler._prompt_interval - 1):
            assert handler.handle(_hook_input()).context == []

    def test_reinforces_after_prompt_interval(self) -> None:
        handler = StandingAuthorisationsHandler()
        clock = _FakeClock()
        handler._clock = clock
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        handler.handle(_hook_input())  # first — full
        result = None
        for _ in range(handler._prompt_interval):
            result = handler.handle(_hook_input())
        assert result is not None
        assert result.context, "reinforcement must fire once prompt_interval is reached"

    def test_reinforces_after_time_interval_even_with_few_prompts(self) -> None:
        handler = StandingAuthorisationsHandler()
        clock = _FakeClock()
        handler._clock = clock
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        handler.handle(_hook_input())  # first — full
        # One more prompt, but well past the time window: the timer fires it.
        clock.advance(handler._interval_minutes * 60 + 1)
        assert handler.handle(_hook_input()).context

    def test_reinforcement_is_the_short_form(self) -> None:
        handler = StandingAuthorisationsHandler()
        clock = _FakeClock()
        handler._clock = clock
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        first = " ".join(handler.handle(_hook_input()).context)
        clock.advance(handler._interval_minutes * 60 + 1)
        later = " ".join(handler.handle(_hook_input()).context)
        assert later, "sanity: a reinforcement was delivered"
        assert len(later) < len(first)

    def test_short_form_still_names_where_it_is_recorded(self) -> None:
        handler = StandingAuthorisationsHandler()
        clock = _FakeClock()
        handler._clock = clock
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        handler.handle(_hook_input())
        clock.advance(handler._interval_minutes * 60 + 1)
        later = " ".join(handler.handle(_hook_input()).context)
        assert "hooks-daemon.yaml" in later

    def test_short_form_is_still_never_a_countermand(self) -> None:
        handler = StandingAuthorisationsHandler()
        clock = _FakeClock()
        handler._clock = clock
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION, AUTHORISATION_WORKFLOWS)
        handler.handle(_hook_input())
        clock.advance(handler._interval_minutes * 60 + 1)
        later = " ".join(handler.handle(_hook_input()).context).lower()
        for forbidden in ("ignore", "disregard", "override", "overrule", "bypass"):
            assert forbidden not in later

    def test_cadence_is_tracked_per_session(self) -> None:
        """A new session gets the full text again — it has not been told yet."""
        handler = StandingAuthorisationsHandler()
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        session_a = {**_hook_input(), "session_id": "aaaaaaaa"}
        for _ in range(10):
            handler.handle(session_a)
        session_b = {**_hook_input(), "session_id": "bbbbbbbb"}
        fresh = " ".join(handler.handle(session_b).context)
        assert "without pausing to ask permission" in fresh

    def test_session_tracking_map_is_bounded(self) -> None:
        """A long-lived daemon must not leak one entry per session forever."""
        handler = StandingAuthorisationsHandler()
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        for index in range(600):
            handler.handle({**_hook_input(), "session_id": f"session-{index}"})
        assert len(handler._session_states) <= 512

    def test_reinforcement_never_skipped_longer_than_the_bound(self) -> None:
        """The reliability floor: silence is bounded, never once-ever.

        Over a long run of prompts with the clock advancing a little each time,
        the reinforcement must keep arriving — at least once every
        prompt_interval prompts.
        """
        handler = StandingAuthorisationsHandler()
        clock = _FakeClock()
        handler._clock = clock
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        handler.handle(_hook_input())  # first — full
        deliveries = 0
        prompts = 40
        for _ in range(prompts):
            clock.advance(1.0)  # tiny, so the timer never fires; only the counter
            if handler.handle(_hook_input()).context:
                deliveries += 1
        # With only the prompt-counter in play, expect ~prompts / prompt_interval.
        assert deliveries >= prompts // handler._prompt_interval - 1


class TestAutomatedPromptsAreIgnored:
    """Task 1.2 + Task 2.4 — automated ticks neither count nor deliver.

    A failsafe-recovery cron tick, a goal-injection line, or this handler's OWN
    supervisor-typed reinforcement all arrive as UserPromptSubmit events. None
    is a human prompt, so none should advance the prompt counter or trigger a
    reinforcement — otherwise the reinforcement rides every hourly cron tick
    (the exact spam this plan removes) and a supervisor-typed line re-triggers
    itself (an injection loop).
    """

    def test_failsafe_recovery_tick_is_silent(self) -> None:
        handler = StandingAuthorisationsHandler()
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        handler.handle(_hook_input())  # first — full
        tick = _hook_input("**FAILSAFE RECOVERY CHECK (automated hourly safety net ...)**")
        assert handler.handle(tick).context == []

    def test_supervisor_marker_prompt_is_silent_loop_guard(self) -> None:
        handler = StandingAuthorisationsHandler()
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        handler.handle(_hook_input())  # first — full
        own = _hook_input("🤖 [ccy-supervisor] standing-authorisation reminder — ...")
        assert handler.handle(own).context == []

    def test_timestamped_supervisor_nudge_is_silent(self) -> None:
        """The REAL supervisor prefix carries a timestamp INSIDE the brackets.

        Live supervisor traffic is ``🤖 [ccy-supervisor 2026-08-28 10:51:04]
        continue`` — the invariant provenance marker is ``🤖 [ccy-supervisor``
        (no closing bracket, mirroring the supervisor's own ``_BOT_PREFIX``),
        not a literal ``🤖 [ccy-supervisor]``. A timestamped nudge must be
        recognised as automated, or every compact/continue nudge would count as
        a human prompt and drag reinforcements forward.
        """
        handler = StandingAuthorisationsHandler()
        clock = _FakeClock()
        handler._clock = clock
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        handler.handle(_hook_input())  # first — full
        # A flood of TIMESTAMPED nudges must never, by themselves, earn a
        # reinforcement — they are automated. With the buggy literal-`]` marker
        # these count as human prompts and the fifth fires a reinforcement.
        for _ in range(20):
            nudge = _hook_input("🤖 [ccy-supervisor 2026-08-28 10:51:04] continue")
            assert handler.handle(nudge).context == []

    def test_automated_ticks_do_not_advance_the_prompt_counter(self) -> None:
        """Interleaved automated ticks must not bring a reinforcement forward."""
        handler = StandingAuthorisationsHandler()
        clock = _FakeClock()
        handler._clock = clock
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        handler.handle(_hook_input())  # first — full
        # A flood of automated ticks must not, by themselves, earn a reinforcement.
        for _ in range(20):
            assert handler.handle(_hook_input("**FAILSAFE RECOVERY CHECK ...**")).context == []


class TestClaudeMdGuidance:
    def test_guidance_documents_the_setting(self) -> None:
        guidance = StandingAuthorisationsHandler().get_claude_md()
        assert guidance is not None
        assert "standing_authorisations" in guidance

    def test_guidance_does_not_itself_carry_the_authorisation(self) -> None:
        """CLAUDE.md documents the setting; the handler delivers it (Decision 1).

        Phase 1 measured CLAUDE.md as the LOWEST-position lever of four, so a
        second copy of the authorisation text here would be the copy that goes
        stale while reading as authoritative.
        """
        guidance = StandingAuthorisationsHandler().get_claude_md()
        assert guidance is not None
        assert "STANDING AUTHORISATION" not in guidance


class TestWriteStandingAuthSignal:
    """Plan 00283 Phase 2 — the signal writer mirrors goal_injection's contract."""

    @pytest.fixture(autouse=True)
    def _mock_project_context(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            f"{_MODULE}.ProjectContext.daemon_untracked_dir",
            classmethod(lambda cls: tmp_path),
        )
        self._untracked = tmp_path

    def _read(self, session_id: str) -> dict[str, Any]:
        path = self._untracked / _SIGNAL_SUBDIR / f"{session_id}{_SIGNAL_SUFFIX}"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_writes_schema_fields(self) -> None:
        lines = ["auth line one", "auth line two"]
        path = write_standing_auth_signal("sess-1", lines, _SOURCE_REINFORCEMENT)
        assert path is not None and path.exists()
        data = self._read("sess-1")
        assert data["session_id"] == "sess-1"
        assert data["rendered_lines"] == lines
        assert data["source"] == _SOURCE_REINFORCEMENT
        assert isinstance(data["ts"], float)

    def test_suffix_is_not_json(self) -> None:
        """A `.json` suffix would be swept up by the supervisor's sidecar reader."""
        path = write_standing_auth_signal("sess-2", ["x"], _SOURCE_REINFORCEMENT)
        assert path is not None
        assert path.suffix != ".json"
        assert path.name.endswith(_SIGNAL_SUFFIX)

    def test_unsafe_session_chars_sanitised(self) -> None:
        path = write_standing_auth_signal("a/b c", ["x"], _SOURCE_REINFORCEMENT)
        assert path is not None
        assert path.name == f"a_b_c{_SIGNAL_SUFFIX}"

    def test_fails_open_when_no_project_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(cls: object) -> Path:
            raise RuntimeError("no ctx")

        monkeypatch.setattr(f"{_MODULE}.ProjectContext.daemon_untracked_dir", classmethod(_raise))
        assert write_standing_auth_signal("s", ["x"], _SOURCE_REINFORCEMENT) is None

    def test_fails_open_on_oserror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(Path, "mkdir", _raise)
        assert write_standing_auth_signal("s", ["x"], _SOURCE_REINFORCEMENT) is None


class TestSupervisorChannelRouting:
    """Plan 00283 Phase 2 — a due reinforcement routes to the supervisor when armed.

    Channel OFF (the shipped default) is identical to Phase 1: reinforcements are
    folded hook-context. Channel ON routes to a signal file only when a ccy
    supervisor is armed+live, and FAILS OPEN to hook-context otherwise, so a
    reinforcement is never silently lost.
    """

    def _make(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        channel: bool,
        armed: bool,
        write_result: Path | None = Path("/x.standing-auth-intent"),
    ) -> tuple[StandingAuthorisationsHandler, list[tuple[str, list[str], str]]]:
        handler = StandingAuthorisationsHandler()
        handler._clock = _FakeClock()
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        handler._supervisor_channel_enabled = channel
        monkeypatch.setattr(
            f"{_MODULE}.ProjectContext.project_root", classmethod(lambda cls: Path("/proj"))
        )
        monkeypatch.setattr(f"{_MODULE}.ccy_supervisor.armed_supervisor_live", lambda root: armed)
        calls: list[tuple[str, list[str], str]] = []

        def _spy(session_id: str, lines: list[str], source: str) -> Path | None:
            calls.append((session_id, lines, source))
            return write_result

        monkeypatch.setattr(f"{_MODULE}.write_standing_auth_signal", _spy)
        return handler, calls

    @staticmethod
    def _drive_to_due(handler: StandingAuthorisationsHandler) -> Any:
        handler.handle(_hook_input())  # first — full (establish)
        result = None
        for _ in range(handler._prompt_interval):
            result = handler.handle(_hook_input())
        return result

    def test_first_delivery_is_hook_context_even_when_armed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        handler, calls = self._make(monkeypatch, channel=True, armed=True)
        first = handler.handle(_hook_input())
        assert first.context, "first delivery must be immediate hook-context"
        assert calls == [], "the establishing delivery must never route to the supervisor"

    def test_due_reinforcement_routes_to_signal_when_armed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        handler, calls = self._make(monkeypatch, channel=True, armed=True)
        result = self._drive_to_due(handler)
        assert result.context == [], "routed reinforcement injects no hook-context"
        assert len(calls) == 1
        _session, lines, source = calls[0]
        assert lines[0] == SUPERVISOR_CHANNEL_HEADER, "the fixed machine-origin header opens it"
        assert "sub-agent delegation" in lines[1], "the body names the enabled authorisation"
        assert source == _SOURCE_REINFORCEMENT

    def test_falls_back_to_context_when_not_armed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handler, calls = self._make(monkeypatch, channel=True, armed=False)
        result = self._drive_to_due(handler)
        assert result.context, "unarmed → fold hook-context"
        assert calls == [], "no signal written when no supervisor is armed"

    def test_falls_back_to_context_when_signal_write_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        handler, calls = self._make(monkeypatch, channel=True, armed=True, write_result=None)
        result = self._drive_to_due(handler)
        assert result.context, "a failed signal write must fail open to hook-context"
        assert len(calls) == 1, "the write was attempted before falling back"

    def test_channel_off_never_routes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handler, calls = self._make(monkeypatch, channel=False, armed=True)
        result = self._drive_to_due(handler)
        assert result.context, "channel off → Phase 1 hook-context behaviour"
        assert calls == [], "channel off must never even check the supervisor"

    def test_no_project_context_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handler, calls = self._make(monkeypatch, channel=True, armed=True)

        def _raise(cls: object) -> Path:
            raise RuntimeError("uninitialised")

        monkeypatch.setattr(f"{_MODULE}.ProjectContext.project_root", classmethod(_raise))
        result = self._drive_to_due(handler)
        assert result.context, "no project context → fold hook-context"
        assert calls == [], "no signal attempted without a project root"
