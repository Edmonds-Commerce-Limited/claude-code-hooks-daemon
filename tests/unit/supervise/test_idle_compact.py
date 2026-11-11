"""Plan 00603 -- the supervisor's own idle compaction at a configurable percentage.

When the session is in a TRUE idle (the host vouches that the screen shows the
main prompt with no background task or sub-agent indicator, the input box is
empty, nothing is streaming) and has stayed so for the settle period, and the
context is at or above the configured percentage (and above an absolute token
floor), the supervisor injects ONE armed `/compact`. The RED and CRITICAL tiers
are untouched.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()
# The autouse fixture below replaces the module attribute; the reader's own
# tests need the real one.
_real_session_internal_idle = _mod.session_internal_idle

_NOW = 50_000.0
_SESSION = "idle-compact-sess-1"
_WINDOW = 1_000_000


@pytest.fixture(autouse=True)
def _internal_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Claude Code's own records say idle unless a test says otherwise."""
    monkeypatch.setattr(_mod, "session_internal_idle", lambda _sid: (True, ""))


def _policy(**overrides: object):
    values: dict[str, object] = {"idle_compact_mode": "on"}
    values.update(overrides)
    return _mod.CompactPolicy(**values)


def _facts(now: float = _NOW, *, true_idle: bool = True, **kw: object):
    return _mod.TickFacts(
        now_wall=now,
        idle=True,
        input_line_empty=True,
        human_compact_submitted=False,
        work_idle=True,
        true_idle=true_idle,
        **kw,
    )


def _write_sidecar(
    sidecar_dir: Path,
    *,
    pct: float = 35.0,
    window: int = _WINDOW,
    tier: str = "ok",
    red: bool = False,
    ts: float = _NOW - 1.0,
    compacting: bool = False,
) -> None:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    (sidecar_dir / f"{_SESSION}.json").write_text(
        json.dumps(
            {
                "red": red,
                "critical": False,
                "compact_urgent": False,
                "tier": tier,
                "pct": pct,
                "window_size": window,
                "session_id": _SESSION,
                "ts": ts,
                "seq": 1,
                "writer_pid": 42,
                "compacting": compacting,
            }
        ),
        encoding="utf-8",
    )


def _decide(
    sidecar_dir: Path, machine, *, now: float, dry_run: bool = False, true_idle: bool = True
):
    freshness = _mod.CompactPolicy().freshness_seconds
    return _mod.decide_once(
        machine,
        sidecar_dir=sidecar_dir,
        facts=_facts(now, true_idle=true_idle),
        dry_run=dry_run,
        freshness_seconds=freshness,
    )


def _settled(sidecar_dir: Path, machine, *, start: float = _NOW, dry_run: bool = False):
    """Tick at ``start`` (settle begins) and return the tick one settle later."""
    _write_sidecar(sidecar_dir, ts=start - 1.0)
    first = _decide(sidecar_dir, machine, now=start, dry_run=dry_run)
    assert first.payload is None, "must not fire before the settle period"
    settle = machine._policy.idle_compact_settle_seconds
    _write_sidecar(sidecar_dir, ts=start + settle - 1.0)
    return _decide(sidecar_dir, machine, now=start + settle, dry_run=dry_run)


class TestFires:
    def test_fires_one_armed_compact_after_settle(self, tmp_path: Path) -> None:
        machine = _mod.CompactStateMachine(_policy())
        outcome = _settled(tmp_path, machine)
        assert outcome.decision_value == _mod.Decision.WOULD_COMPACT.value
        assert outcome.payload is not None
        assert outcome.payload.startswith("/compact")
        assert "idle" in outcome.reason
        assert outcome.submit is True
        assert machine.state is _mod.SupervisorState.AWAIT_COMPACTING

    def test_exactly_at_threshold_fires(self, tmp_path: Path) -> None:
        machine = _mod.CompactStateMachine(_policy())
        _write_sidecar(tmp_path, pct=30.0, ts=_NOW - 1.0)
        _decide(tmp_path, machine, now=_NOW)
        _write_sidecar(tmp_path, pct=30.0, ts=_NOW + 59.0)
        assert _decide(tmp_path, machine, now=_NOW + 60.0).payload is not None

    def test_configurable_percentage(self, tmp_path: Path) -> None:
        machine = _mod.CompactStateMachine(_policy(idle_compact_pct=50.0))
        assert _settled(tmp_path, machine).payload is None


class TestHolds:
    def test_not_inside_settle_period(self, tmp_path: Path) -> None:
        machine = _mod.CompactStateMachine(_policy())
        _write_sidecar(tmp_path)
        assert _decide(tmp_path, machine, now=_NOW).payload is None
        _write_sidecar(tmp_path, ts=_NOW + 28.0)
        assert _decide(tmp_path, machine, now=_NOW + 30.0).payload is None

    def test_background_task_or_subagent_means_not_true_idle(self, tmp_path: Path) -> None:
        """The host reports true_idle False for either; the settle clock restarts."""
        machine = _mod.CompactStateMachine(_policy())
        _write_sidecar(tmp_path)
        _decide(tmp_path, machine, now=_NOW)
        _write_sidecar(tmp_path, ts=_NOW + 40.0)
        assert _decide(tmp_path, machine, now=_NOW + 41.0, true_idle=False).payload is None
        _write_sidecar(tmp_path, ts=_NOW + 69.0)
        # idle again at +42, but only 29s since: the interruption reset the clock.
        _decide(tmp_path, machine, now=_NOW + 42.0)
        _write_sidecar(tmp_path, ts=_NOW + 70.0)
        assert _decide(tmp_path, machine, now=_NOW + 71.0).payload is None
        _write_sidecar(tmp_path, ts=_NOW + 101.0)
        assert _decide(tmp_path, machine, now=_NOW + 102.0).payload is not None

    def test_legacy_host_without_the_fact_never_fires(self, tmp_path: Path) -> None:
        machine = _mod.CompactStateMachine(_policy())
        _write_sidecar(tmp_path)
        _decide(tmp_path, machine, now=_NOW, true_idle=False)
        _write_sidecar(tmp_path, ts=_NOW + 100.0)
        assert _decide(tmp_path, machine, now=_NOW + 101.0, true_idle=False).payload is None

    def test_below_percentage(self, tmp_path: Path) -> None:
        machine = _mod.CompactStateMachine(_policy())
        _write_sidecar(tmp_path, pct=29.0)
        _decide(tmp_path, machine, now=_NOW)
        _write_sidecar(tmp_path, pct=29.0, ts=_NOW + 59.0)
        assert _decide(tmp_path, machine, now=_NOW + 60.0).payload is None

    def test_token_floor_protects_a_small_window(self, tmp_path: Path) -> None:
        machine = _mod.CompactStateMachine(_policy())
        _write_sidecar(tmp_path, pct=40.0, window=100_000)
        _decide(tmp_path, machine, now=_NOW)
        _write_sidecar(tmp_path, pct=40.0, window=100_000, ts=_NOW + 59.0)
        assert _decide(tmp_path, machine, now=_NOW + 60.0).payload is None

    def test_unknown_window_fails_closed(self, tmp_path: Path) -> None:
        machine = _mod.CompactStateMachine(_policy())
        _write_sidecar(tmp_path, window=0)
        _decide(tmp_path, machine, now=_NOW)
        _write_sidecar(tmp_path, window=0, ts=_NOW + 59.0)
        assert _decide(tmp_path, machine, now=_NOW + 60.0).payload is None

    def test_stale_sidecar(self, tmp_path: Path) -> None:
        machine = _mod.CompactStateMachine(_policy())
        _write_sidecar(tmp_path, ts=_NOW - 1.0)
        _decide(tmp_path, machine, now=_NOW)
        assert _decide(tmp_path, machine, now=_NOW + 600.0).payload is None

    def test_compaction_in_progress(self, tmp_path: Path) -> None:
        machine = _mod.CompactStateMachine(_policy())
        _write_sidecar(tmp_path, compacting=True)
        _decide(tmp_path, machine, now=_NOW)
        _write_sidecar(tmp_path, compacting=True, ts=_NOW + 59.0)
        outcome = _decide(tmp_path, machine, now=_NOW + 60.0)
        assert not (outcome.payload or "").startswith("/compact")

    def test_cooldown_after_a_compaction(self, tmp_path: Path) -> None:
        machine = _mod.CompactStateMachine(_policy())
        assert _settled(tmp_path, machine).payload is not None
        machine._enter_monitor()  # the compaction ran and resumed
        machine.clear_own_line()
        later = _NOW + 60.0 + 600.0
        _write_sidecar(tmp_path, ts=later - 1.0)
        _decide(tmp_path, machine, now=later - 100.0)
        assert _decide(tmp_path, machine, now=later).payload is None
        after = _NOW + 60.0 + 1800.0 + 61.0
        _write_sidecar(tmp_path, ts=after - 62.0)
        _decide(tmp_path, machine, now=after - 61.0)
        _write_sidecar(tmp_path, ts=after - 1.0)
        assert _decide(tmp_path, machine, now=after).payload is not None

    def test_cooldown_counts_any_compaction_not_just_its_own(self, tmp_path: Path) -> None:
        machine = _mod.CompactStateMachine(_policy())
        machine.import_state({"last_action_ts": _NOW - 10.0})
        assert _settled(tmp_path, machine).payload is None

    def test_red_tier_behaviour_unchanged(self, tmp_path: Path) -> None:
        machine = _mod.CompactStateMachine(_policy())
        _write_sidecar(tmp_path, pct=45.0, tier="red", red=True)
        outcome = _decide(tmp_path, machine, now=_NOW, true_idle=False)
        assert outcome.decision_value == _mod.Decision.WOULD_COMPACT.value
        assert "idle compaction" not in outcome.reason


class TestModes:
    def test_off_never_fires(self, tmp_path: Path) -> None:
        machine = _mod.CompactStateMachine(_policy(idle_compact_mode="off"))
        assert _settled(tmp_path, machine).payload is None

    def test_mode_dry_run_logs_and_types_nothing(self, tmp_path: Path) -> None:
        machine = _mod.CompactStateMachine(_policy(idle_compact_mode="dry-run"))
        outcome = _settled(tmp_path, machine)
        assert outcome.payload is None
        assert outcome.noop_reason_log is not None
        assert "would idle-compact" in outcome.noop_reason_log
        assert "35%" in outcome.noop_reason_log
        assert machine.state is _mod.SupervisorState.MONITOR

    def test_global_dry_run_types_nothing(self, tmp_path: Path) -> None:
        machine = _mod.CompactStateMachine(_policy(idle_compact_mode="on"))
        outcome = _settled(tmp_path, machine, dry_run=True)
        assert outcome.payload is None
        assert outcome.noop_reason_log is not None
        assert "would idle-compact" in outcome.noop_reason_log
        assert machine.state is _mod.SupervisorState.MONITOR

    def test_dry_run_decision_is_cooled_down_so_it_logs_once(self, tmp_path: Path) -> None:
        machine = _mod.CompactStateMachine(_policy(idle_compact_mode="dry-run"))
        assert _settled(tmp_path, machine).noop_reason_log is not None
        later = _NOW + 120.0
        _write_sidecar(tmp_path, ts=later - 1.0)
        outcome = _decide(tmp_path, machine, now=later)
        assert "would idle-compact" not in (outcome.noop_reason_log or "")

    def test_state_round_trips_to_the_worker(self) -> None:
        machine = _mod.CompactStateMachine(_policy())
        machine.note_true_idle(True, now=_NOW)
        other = _mod.CompactStateMachine(_policy())
        other.import_state(machine.export_state())
        assert other.export_state()["true_idle_since"] == _NOW


class TestPolicyEnv:
    def test_defaults_are_dry_run_first(self) -> None:
        policy = _mod.CompactPolicy()
        assert policy.idle_compact_mode == "dry-run"
        assert policy.idle_compact_pct == 30.0
        assert policy.idle_compact_settle_seconds == 60.0
        assert policy.idle_compact_cooldown_seconds == 1800.0
        assert policy.idle_compact_min_tokens == 100_000

    def test_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CCY_IDLE_COMPACT", "on")
        monkeypatch.setenv("CCY_IDLE_COMPACT_PCT", "25")
        monkeypatch.setenv("CCY_IDLE_COMPACT_SETTLE_SECONDS", "10")
        monkeypatch.setenv("CCY_IDLE_COMPACT_COOLDOWN_SECONDS", "60")
        monkeypatch.setenv("CCY_IDLE_COMPACT_MIN_TOKENS", "5000")
        policy = _mod.CompactPolicy()
        assert (
            policy.idle_compact_mode,
            policy.idle_compact_pct,
            policy.idle_compact_settle_seconds,
            policy.idle_compact_cooldown_seconds,
            policy.idle_compact_min_tokens,
        ) == ("on", 25.0, 10.0, 60.0, 5000)

    def test_unknown_mode_is_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CCY_IDLE_COMPACT", "banana")
        assert _mod.CompactPolicy().idle_compact_mode == "off"

    @pytest.mark.parametrize("raw", ["", "abc", "0", "100", "-5"])
    def test_bad_percentage_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch, raw: str
    ) -> None:
        monkeypatch.setenv("CCY_IDLE_COMPACT_PCT", raw)
        assert _mod.CompactPolicy().idle_compact_pct == 30.0

    @pytest.mark.parametrize("raw", ["", "abc", "-1"])
    def test_bad_seconds_fall_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch, raw: str
    ) -> None:
        monkeypatch.setenv("CCY_IDLE_COMPACT_SETTLE_SECONDS", raw)
        monkeypatch.setenv("CCY_IDLE_COMPACT_COOLDOWN_SECONDS", raw)
        monkeypatch.setenv("CCY_IDLE_COMPACT_MIN_TOKENS", raw)
        policy = _mod.CompactPolicy()
        assert policy.idle_compact_settle_seconds == 60.0
        assert policy.idle_compact_cooldown_seconds == 1800.0
        assert policy.idle_compact_min_tokens == 100_000


class TestFactsWire:
    def test_true_idle_round_trips(self) -> None:
        facts = _facts(true_idle=True)
        assert _mod._facts_from_json(_mod._facts_to_json(facts)).true_idle is True

    def test_absent_key_means_not_idle(self) -> None:
        raw = json.loads(_mod._facts_to_json(_facts()))
        del raw["true_idle"]
        assert _mod._facts_from_json(json.dumps(raw)).true_idle is False


class TestScreenFooter:
    @pytest.mark.parametrize(
        "footer",
        [
            "  ? for shortcuts",
            "  ⏵⏵ bypass permissions on (shift+tab to cycle)",
            "",
        ],
    )
    def test_quiet_footer(self, footer: str) -> None:
        dump = "some chat text mentioning an agent\n\n> \n" + footer
        assert _mod.screen_shows_busy_footer(dump) is False

    @pytest.mark.parametrize(
        "footer",
        [
            "  1 background task running",
            "  2 local agents",
            "  1 shell · esc to interrupt",
            "  ✻ Thinking… (esc to interrupt)",
            "  3 monitors",
        ],
    )
    def test_busy_footer(self, footer: str) -> None:
        assert _mod.screen_shows_busy_footer(f"> \n{footer}") is True

    def test_only_the_footer_rows_count(self) -> None:
        chat = "the background task finished\n" + "\n".join(f"line {i}" for i in range(20))
        assert _mod.screen_shows_busy_footer(chat) is False


class _FakeScreen(_mod.ScreenFocusCheck):
    """A ScreenFocusCheck whose hooks-screen output is scripted."""

    def __init__(self, outputs: dict[str, str | None]) -> None:
        super().__init__(
            _mod.ScreenBuffer(),
            binary=None,
            size_fn=lambda: (80, 24),
            clock=lambda: 0.0,
        )
        self._outputs = outputs
        self.spawns = 0

    def _spawn(self, snapshot: bytes, extra: str) -> str | None:
        self.spawns += 1
        return self._outputs.get(extra)


class TestQuietPrompt:
    def test_main_and_quiet_footer(self) -> None:
        screen = _FakeScreen({"": "main\n", "--dump": "> \n  ? for shortcuts\n"})
        assert screen.quiet_prompt() is True

    @pytest.mark.parametrize("word", ["transcript", "panel-selected", "unknown"])
    def test_other_screens_fail_closed(self, word: str) -> None:
        screen = _FakeScreen({"": f"{word}\n", "--dump": "> \n"})
        assert screen.quiet_prompt() is False

    def test_busy_footer_is_not_quiet(self) -> None:
        screen = _FakeScreen({"": "main\n", "--dump": "> \n  1 local agent\n"})
        assert screen.quiet_prompt() is False

    def test_no_dump_fails_closed(self) -> None:
        assert _FakeScreen({"": "main\n", "--dump": None}).quiet_prompt() is False

    def test_empty_dump_fails_closed(self) -> None:
        assert _FakeScreen({"": "main\n", "--dump": "  \n"}).quiet_prompt() is False


def _no_read(_sid: str) -> tuple[bool, str]:
    raise AssertionError("Claude Code's records must not be read here")


class TestInternalIdleGate:
    def test_decision_consults_the_internal_records(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[str] = []

        def busy(session_id: str) -> tuple[bool, str]:
            seen.append(session_id)
            return False, "busy"

        monkeypatch.setattr(_mod, "session_internal_idle", busy)
        machine = _mod.CompactStateMachine(_policy())
        assert _settled(tmp_path, machine).payload is None
        assert set(seen) == {_SESSION}

    def test_not_read_when_the_feature_is_off(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_mod, "session_internal_idle", _no_read)
        machine = _mod.CompactStateMachine(_policy(idle_compact_mode="off"))
        assert _settled(tmp_path, machine).payload is None

    def test_not_read_while_the_cheap_gates_fail(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_mod, "session_internal_idle", _no_read)
        machine = _mod.CompactStateMachine(_policy())
        _write_sidecar(tmp_path)
        assert _decide(tmp_path, machine, now=_NOW, true_idle=False).payload is None


_CLAUDE_SID = "0a12-session"


class _Layout:
    """A fake config dir and tmp root laid out as Claude Code 2.1.322 does."""

    def __init__(self, root: Path) -> None:
        self.config = root / "config"
        self.tmp = root / "tmp"
        self.uid = 1234
        (self.config / "sessions").mkdir(parents=True)
        self.tmp.mkdir()

    def session(self, *, status: str = "idle", pid: int = 111, sid: str = _CLAUDE_SID) -> None:
        (self.config / "sessions" / f"{pid}.json").write_text(
            json.dumps({"pid": pid, "sessionId": sid, "status": status}), encoding="utf-8"
        )

    def subagent(self, name: str, body: str) -> None:
        folder = self.config / "projects" / "-proj" / _CLAUDE_SID / "subagents"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{name}.meta.json").write_text(body, encoding="utf-8")

    def task(self, name: str, text: str) -> None:
        folder = self.tmp / f"claude-{self.uid}" / "-proj" / _CLAUDE_SID / "tasks"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{name}.output").write_text(text, encoding="utf-8")

    def check(self, *, alive: bool = True, sid: str = _CLAUDE_SID) -> tuple[bool, str]:
        return _real_session_internal_idle(
            sid,
            config_dir=self.config,
            tmp_root=self.tmp,
            uid=self.uid,
            pid_alive=lambda _pid: alive,
        )


@pytest.fixture
def layout(tmp_path: Path) -> _Layout:
    return _Layout(tmp_path)


class TestSessionInternalIdle:
    def test_idle_with_nothing_running(self, layout: _Layout) -> None:
        layout.session()
        assert layout.check() == (True, "")

    def test_finished_agents_and_exited_tasks_are_idle(self, layout: _Layout) -> None:
        layout.session()
        layout.subagent("agent-a1", json.dumps({"finished": True}))
        layout.task("b1", "start\nend\n\n[exited with code 0]")
        layout.task("b2", "failed\n[exited with code 137]\n")
        assert layout.check() == (True, "")

    @pytest.mark.parametrize("status", ["busy", "waiting", "shell", ""])
    def test_status_other_than_idle(self, layout: _Layout, status: str) -> None:
        layout.session(status=status)
        idle, why = layout.check()
        assert idle is False
        assert "not idle" in why

    def test_missing_status_record_fails_closed(self, layout: _Layout) -> None:
        assert layout.check() == (False, "no live session record")

    def test_record_of_another_session_does_not_count(self, layout: _Layout) -> None:
        layout.session(sid="someone-else")
        assert layout.check()[0] is False

    def test_dead_pid_record_does_not_count(self, layout: _Layout) -> None:
        layout.session()
        assert layout.check(alive=False) == (False, "no live session record")

    def test_unparseable_status_record_fails_closed(self, layout: _Layout) -> None:
        (layout.config / "sessions" / "9.json").write_text("{not json", encoding="utf-8")
        assert layout.check()[0] is False

    def test_empty_session_id(self, layout: _Layout) -> None:
        layout.session()
        assert layout.check(sid="") == (False, "no session id")

    @pytest.mark.parametrize("body", ['{"agentType": "x"}', '{"finished": false}', "{broken", "[]"])
    def test_unfinished_or_unreadable_subagent(self, layout: _Layout, body: str) -> None:
        layout.session()
        layout.subagent("agent-a1", body)
        idle, why = layout.check()
        assert idle is False
        assert "agent-a1" in why

    def test_task_without_exit_line(self, layout: _Layout) -> None:
        layout.session()
        layout.task("b7", "still going\n")
        idle, why = layout.check()
        assert idle is False
        assert "b7" in why

    def test_task_exit_line_only_counts_at_the_end(self, layout: _Layout) -> None:
        layout.session()
        layout.task("b7", "[exited with code 0]\nrestarted and running\n" + "x" * 400)
        assert layout.check()[0] is False

    def test_a_long_exited_task_is_read_from_its_tail(self, layout: _Layout) -> None:
        layout.session()
        layout.task("b8", "y" * 5000 + "\n[exited with code 0]")
        assert layout.check() == (True, "")

    def test_non_background_outputs_are_ignored(self, layout: _Layout) -> None:
        layout.session()
        layout.task("a1", "agent transcript link, no trailer")
        assert layout.check() == (True, "")

    def test_defaults_resolve_without_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/nonexistent-claude-config")
        assert _real_session_internal_idle("sid")[0] is False

    def test_pid_probe(self) -> None:
        assert _mod._pid_alive(os.getpid()) is True
        assert _mod._pid_alive(0) is False
        assert _mod._pid_alive(2**22 + 12345678) is False
