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
from typing import TYPE_CHECKING

import pytest

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()

_NOW = 50_000.0
_SESSION = "idle-compact-sess-1"
_WINDOW = 1_000_000


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
