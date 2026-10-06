"""Plan 00470 Task 2.3 -- the cron-expiry watchdog (supervisor half).

A session cron lives at most seven days. The daemon records every CronCreate in
``cron-records.json``; the Stop-hook enforcer refreshes a job before it dies,
but only while Stop hooks fire. If the session has gone quiet for long enough
that every recorded job is already past its expiry, nothing inside the session
will notice, so the supervisor types the same "CronList and reconcile" prompt
the daemon's ``persistent_cron_assertor`` gives at SessionStart.

The supervisor is stdlib-only and cannot import the daemon package, so the
record file name, its field names and the seven-day expiry are copied into it
and pinned here to ``utils/cron_records``. "Hook traffic" is approximated by
PTY output quiet time (``TickFacts.output_quiet_seconds``), which needs no
daemon change.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

from claude_code_hooks_daemon.handlers.session_start import persistent_cron_assertor
from claude_code_hooks_daemon.utils import cron_records
from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from tests.unit.supervise._load import SupervisorTickOutcome

_mod = load_supervisor_module()

_NOW = 5_000_000.0
_EXPIRY = cron_records.CRON_EXPIRY_SECONDS
_QUIET = 2 * 60 * 60.0
_SESSION = "cron-watchdog-sess"


def _facts(
    *,
    quiet: float = _QUIET,
    idle: bool = True,
    input_line_empty: bool = True,
    work_idle: bool = True,
) -> object:
    return _mod.TickFacts(
        now_wall=_NOW,
        idle=idle,
        input_line_empty=input_line_empty,
        human_compact_submitted=False,
        work_idle=work_idle,
        output_quiet_seconds=quiet,
    )


def _write_records(sidecar_dir: Path, ages: list[float], *, raw: str | None = None) -> None:
    """Write records created ``age`` seconds before ``_NOW`` beside the sidecar dir."""
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    path = sidecar_dir.parent / cron_records.CRON_RECORDS_FILENAME
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
        return
    entries = [
        {
            "session_id": _SESSION,
            "cron_id": f"c{i}",
            "schedule": "7 * * * *",
            "prompt_hash": "h",
            "created_at": _NOW - age,
        }
        for i, age in enumerate(ages)
    ]
    path.write_text(json.dumps({"records": entries}), encoding="utf-8")


def _decide(
    sidecar_dir: Path, *, facts: object | None = None, machine: object = None, dry_run: bool = False
) -> SupervisorTickOutcome:
    policy = _mod.CompactPolicy()
    machine = machine or _mod.CompactStateMachine(policy)
    return cast(
        "SupervisorTickOutcome",
        _mod.decide_once(
            machine,
            sidecar_dir=sidecar_dir,
            facts=facts or _facts(),
            dry_run=dry_run,
            freshness_seconds=policy.freshness_seconds,
        ),
    )


def _sidecar(tmp_path: Path) -> Path:
    return tmp_path / "context-sidecar"


class TestCopiesPinnedToTheDaemon:
    def test_the_expiry_matches(self) -> None:
        assert cron_records.CRON_EXPIRY_SECONDS == _mod._CRON_EXPIRY_SECONDS

    def test_the_record_file_name_matches(self) -> None:
        assert cron_records.CRON_RECORDS_FILENAME == _mod._CRON_RECORDS_FILENAME

    def test_the_field_names_match(self) -> None:
        source = inspect.getsource(cron_records)
        assert f'"{_mod._CRON_RECORDS_KEY}"' in source
        assert f'"{_mod._CRON_FIELD_CREATED_AT}"' in source
        assert f'"{_mod._CRON_FIELD_SESSION_ID}"' in source

    def test_the_quiet_threshold_is_two_hours(self) -> None:
        assert _mod._CRON_WATCHDOG_QUIET_SECONDS == _QUIET

    def test_the_prompt_reuses_the_assertor_wording(self) -> None:
        assert "Run CronList FIRST." in inspect.getsource(persistent_cron_assertor)
        message = _mod._render_cron_reconcile_message()
        assert "Run CronList FIRST." in message
        assert "reconcile" in message.lower()

    def test_the_prompt_carries_the_supervisor_marker_and_disclaimer(self) -> None:
        message = _mod._render_cron_reconcile_message()
        assert "🤖 [ccy-supervisor" in message
        assert "not a human instruction" in message.lower()


class TestFiring:
    def test_all_expired_and_quiet_long_enough_fires(self, tmp_path: Path) -> None:
        side = _sidecar(tmp_path)
        _write_records(side, [_EXPIRY + 10, _EXPIRY + 99])
        outcome = _decide(side)
        assert outcome.decision_value == _mod.Decision.WOULD_CRON_RECONCILE.value
        assert outcome.payload is not None and "Run CronList FIRST." in outcome.payload
        assert outcome.submit is True

    def test_no_records_does_not_fire(self, tmp_path: Path) -> None:
        side = _sidecar(tmp_path)
        side.mkdir()
        assert _decide(side).payload is None

    def test_a_malformed_record_file_does_not_fire(self, tmp_path: Path) -> None:
        side = _sidecar(tmp_path)
        _write_records(side, [], raw="{not json")
        assert _decide(side).payload is None

    def test_one_fresh_record_does_not_fire(self, tmp_path: Path) -> None:
        side = _sidecar(tmp_path)
        _write_records(side, [_EXPIRY + 10, 60.0])
        assert _decide(side).payload is None

    def test_a_record_exactly_at_expiry_counts_as_expired(self, tmp_path: Path) -> None:
        side = _sidecar(tmp_path)
        _write_records(side, [_EXPIRY])
        assert _decide(side).payload is not None

    def test_a_record_just_inside_expiry_is_alive(self, tmp_path: Path) -> None:
        side = _sidecar(tmp_path)
        _write_records(side, [_EXPIRY - 1])
        assert _decide(side).payload is None

    def test_all_expired_but_quiet_just_short_of_threshold_does_not_fire(
        self, tmp_path: Path
    ) -> None:
        side = _sidecar(tmp_path)
        _write_records(side, [_EXPIRY + 10])
        assert _decide(side, facts=_facts(quiet=_QUIET - 1)).payload is None

    def test_a_host_that_reports_no_quiet_time_never_fires(self, tmp_path: Path) -> None:
        side = _sidecar(tmp_path)
        _write_records(side, [_EXPIRY + 10])
        facts = _mod.TickFacts(
            now_wall=_NOW,
            idle=True,
            input_line_empty=True,
            human_compact_submitted=False,
            work_idle=True,
        )
        assert _decide(side, facts=facts).payload is None

    def test_a_record_of_a_foreign_session_is_ignored(self, tmp_path: Path) -> None:
        side = _sidecar(tmp_path)
        _write_records(side, [60.0])
        policy = _mod.CompactPolicy()
        machine = _mod.CompactStateMachine(policy)
        outcome = _mod.decide_once(
            machine,
            sidecar_dir=side,
            facts=_facts(),
            dry_run=False,
            freshness_seconds=policy.freshness_seconds,
            own_sessions=frozenset({"someone-else"}),
        )
        # Nothing of ours is recorded, so there is nothing to reconcile.
        assert outcome.payload is None

    def test_dry_run_types_a_marker(self, tmp_path: Path) -> None:
        side = _sidecar(tmp_path)
        _write_records(side, [_EXPIRY + 10])
        outcome = _decide(side, dry_run=True)
        assert outcome.decision_value == _mod.Decision.WOULD_CRON_RECONCILE.value
        assert outcome.payload is not None and "dry-run" in outcome.payload


class TestGates:
    def test_a_usage_pause_wins(self, tmp_path: Path) -> None:
        side = _sidecar(tmp_path)
        _write_records(side, [_EXPIRY + 10])
        pause = {
            "session_id": _SESSION,
            "paused_at": _NOW - 100,
            "resume_at": _NOW + 3600,
            "window": "five_hour",
            "used_percentage": 95.0,
            "ceiling": 90.0,
            "reason": "test",
        }
        side.mkdir(parents=True, exist_ok=True)
        (side / f"{_SESSION}{_mod._USAGE_PAUSE_SUFFIX}").write_text(
            json.dumps(pause), encoding="utf-8"
        )
        outcome = _decide(side)
        assert outcome.decision_value != _mod.Decision.WOULD_CRON_RECONCILE.value
        assert "usage pause" in outcome.reason

    def test_a_non_empty_input_box_defers(self, tmp_path: Path) -> None:
        side = _sidecar(tmp_path)
        _write_records(side, [_EXPIRY + 10])
        outcome = _decide(side, facts=_facts(input_line_empty=False))
        assert outcome.payload is None
        assert outcome.deferred_log is not None
        assert "cron" in outcome.deferred_log

    def test_a_busy_session_does_not_fire(self, tmp_path: Path) -> None:
        side = _sidecar(tmp_path)
        _write_records(side, [_EXPIRY + 10])
        assert _decide(side, facts=_facts(idle=False)).payload is None

    def test_the_cap_stops_it(self, tmp_path: Path) -> None:
        side = _sidecar(tmp_path)
        _write_records(side, [_EXPIRY + 10])
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        for _ in range(_mod._MAX_CRON_RECONCILE_INJECTIONS):
            machine.mark_cron_reconcile_injection(_NOW - 10 * _QUIET)
        outcome = _decide(side, machine=machine)
        assert outcome.payload is None
        assert outcome.noop_reason_log is not None and "cap" in outcome.noop_reason_log

    def test_it_does_not_repeat_within_the_quiet_window(self, tmp_path: Path) -> None:
        side = _sidecar(tmp_path)
        _write_records(side, [_EXPIRY + 10])
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        machine.mark_cron_reconcile_injection(_NOW - 60)
        assert _decide(side, machine=machine).payload is None

    def test_it_may_repeat_after_a_full_quiet_window(self, tmp_path: Path) -> None:
        side = _sidecar(tmp_path)
        _write_records(side, [_EXPIRY + 10])
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        machine.mark_cron_reconcile_injection(_NOW - _QUIET)
        assert _decide(side, machine=machine).payload is not None

    def test_a_pending_session_actions_directive_goes_first(self, tmp_path: Path) -> None:
        side = _sidecar(tmp_path)
        _write_records(side, [_EXPIRY + 10])
        (side / "s.session-actions").write_text(
            json.dumps({"session_id": _SESSION, "ts": _NOW - 5.0, "count": 2}),
            encoding="utf-8",
        )
        outcome = _decide(side)
        assert outcome.decision_value == _mod.Decision.WOULD_SESSION_ACTIONS.value


class TestBookkeeping:
    def test_the_host_counts_a_successful_injection(self, tmp_path: Path) -> None:
        side = _sidecar(tmp_path)
        _write_records(side, [_EXPIRY + 10])
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        outcome = _decide(side, machine=machine)
        _mod._apply_post_injection_bookkeeping(machine, outcome, injected=True, now_wall=_NOW)
        assert machine.cron_reconcile_injections == 1
        assert machine.cron_reconcile_last_ts == _NOW

    def test_state_round_trips(self) -> None:
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        machine.mark_cron_reconcile_injection(123.0)
        other = _mod.CompactStateMachine(_mod.CompactPolicy())
        other.import_state(machine.export_state())
        assert other.cron_reconcile_injections == 1
        assert other.cron_reconcile_last_ts == 123.0

    def test_the_quiet_time_crosses_the_worker_boundary(self) -> None:
        facts = _facts(quiet=1234.5)
        restored = _mod._facts_from_json(_mod._facts_to_json(facts))
        assert restored.output_quiet_seconds == 1234.5

    def test_output_quiet_seconds_from_activity(self) -> None:
        activity = _mod.OutputActivity()
        assert _mod._output_quiet_seconds(activity, now_monotonic=100.0) == 0.0
        activity.last_output_monotonic = 40.0
        assert _mod._output_quiet_seconds(activity, now_monotonic=100.0) == 60.0
