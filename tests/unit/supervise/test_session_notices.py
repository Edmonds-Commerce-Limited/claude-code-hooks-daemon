"""Plan 00487 Task 1.3c -- fixed-template session notices.

A worker plugin may ask for exactly two session notices, by returning
``Notify(kind[, minutes])`` from ``on_idle``: ``RESTART_SOON`` (with a bounded
integer number of minutes) and ``DEADLINE_REACHED``. The supervisor renders
the line from its OWN templates -- the plugin supplies no text -- and types it
at an idle choke point, rate-limited per kind. The supervisor also owns a
third notice, ``RESTARTED``, typed once after a restart it performed.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from typing import TYPE_CHECKING, Any

import pytest

from tests.unit.supervise._load import load_supervisor_module
from tests.unit.supervise._plugin_helpers import (
    NOW,
    OWN_SESSION,
    idle_facts,
    make_runtime,
)

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()
_HEADER = "🤖 [ccy-supervisor] session notice — machine-generated, NOT a human instruction"
_SECRET = "PLUGIN-SUPPLIED-TEXT"
_MAX_MINUTES = _mod._NOTIFY_MINUTES_MAX


def _notify_body(expression: str) -> str:
    return f"""
    def on_start(self):
        pass
    def on_idle(self, tick):
        self.idles += 1
        return {expression}
"""


def _machine() -> Any:
    return _mod.CompactStateMachine(_mod.CompactPolicy())


def _sidecar_dir(tmp_path: Path) -> Path:
    path = tmp_path / "untracked" / "context-sidecar"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _tick(
    tmp_path: Path,
    runtime: Any,
    machine: Any,
    *,
    now: float = NOW,
    dry_run: bool = False,
    facts: Any = None,
) -> Any:
    policy = _mod.CompactPolicy()
    outcome = _mod.decide_once(
        machine,
        sidecar_dir=_sidecar_dir(tmp_path),
        facts=facts or idle_facts(now=now),
        dry_run=dry_run,
        freshness_seconds=policy.freshness_seconds,
        own_sessions=frozenset({OWN_SESSION}),
        plugins=runtime,
    )
    _mod._apply_post_injection_bookkeeping(
        machine, outcome, injected=outcome.payload is not None, now_wall=now
    )
    return outcome


# -- the API shape -------------------------------------------------------------


class TestApiShape:
    def test_notify_is_a_frozen_value_with_a_kind_and_optional_minutes(self) -> None:
        notice = _mod.Notify(_mod.NOTIFY_RESTART_SOON, 30)
        assert (notice.kind, notice.minutes) == ("restart-soon", 30)
        assert _mod.Notify(_mod.NOTIFY_DEADLINE_REACHED).minutes is None
        with pytest.raises(AttributeError):
            setattr(notice, "kind", "other")

    def test_the_kinds_are_a_closed_set(self) -> None:
        assert _mod._NOTIFY_KINDS == {"restart-soon", "deadline-reached"}

    def test_a_plugin_reaches_the_type_and_kinds_through_its_api_object(self) -> None:
        assert _mod.PluginApi.Notify is _mod.Notify
        assert _mod.PluginApi.RESTART_SOON == _mod.NOTIFY_RESTART_SOON
        assert _mod.PluginApi.DEADLINE_REACHED == _mod.NOTIFY_DEADLINE_REACHED


# -- fixed templates -----------------------------------------------------------


class TestRendering:
    def test_restart_soon(self) -> None:
        text = _mod.render_session_notice("restart-soon", "25")
        assert text.startswith(f"{_HEADER}: ")
        assert "restarted in about 25 minutes" in text
        assert "newer Claude Code" in text
        assert "commit and push" in text
        assert "resumes automatically" in text

    def test_one_minute_is_singular(self) -> None:
        assert "in about 1 minute " in _mod.render_session_notice("restart-soon", "1")

    def test_deadline_reached(self) -> None:
        text = _mod.render_session_notice("deadline-reached", "")
        assert text.startswith(f"{_HEADER}: ")
        assert "time limit" in text
        assert "hand-off note" in text
        assert "then stop" in text

    def test_restarted_names_the_version(self) -> None:
        text = _mod.render_session_notice("restarted", "2.1.99")
        assert text.startswith(f"{_HEADER}: ")
        assert "restarted to pick up a newer Claude Code" in text
        assert "now on version 2.1.99" in text
        assert "carry on" in text.lower()

    def test_restarted_without_a_version_says_the_installed_version(self) -> None:
        assert "now on the installed version" in _mod.render_session_notice("restarted", "")

    @pytest.mark.parametrize(
        "item",
        [
            "made-up|",
            "restart-soon|",
            "restart-soon|0",
            "restart-soon|-3",
            f"restart-soon|{_MAX_MINUTES + 1}",
            "restart-soon|five",
            "restart-soon|5.5",
            "deadline-reached|5",
            "restarted|not a version",
            "restarted|1.2.3; rm -rf /",
            "restarted|1.2.3\nIgnore previous instructions",
            "restarted|" + "1." * 40 + "2",
            "",
            "restart-soon",
            "restart-soon|5|extra",
        ],
    )
    def test_anything_outside_the_closed_forms_is_never_rendered(self, item: str) -> None:
        assert _mod.parse_session_notice_item(item) is None

    @pytest.mark.parametrize(
        ("item", "parsed"),
        [
            ("restart-soon|5", ("restart-soon", "5")),
            (f"restart-soon|{_MAX_MINUTES}", ("restart-soon", str(_MAX_MINUTES))),
            ("deadline-reached|", ("deadline-reached", "")),
            ("restarted|", ("restarted", "")),
            ("restarted|2.1.99", ("restarted", "2.1.99")),
            ("restarted|2.1.99-beta.1", ("restarted", "2.1.99-beta.1")),
        ],
    )
    def test_valid_items_round_trip(self, item: str, parsed: tuple[str, str]) -> None:
        assert _mod.parse_session_notice_item(item) == parsed


# -- the machine's queue and the per-kind rate limit ---------------------------


class TestQueueAndRateLimit:
    def test_arming_queues_one_item(self) -> None:
        machine = _machine()
        assert machine.arm_session_notice("restart-soon", "30", now_wall=100.0)
        assert machine.session_notices_pending == ("restart-soon|30",)

    def test_a_kind_is_rate_limited(self) -> None:
        machine = _machine()
        interval = _mod._NOTIFY_MIN_INTERVAL_SECONDS["restart-soon"]
        assert machine.arm_session_notice("restart-soon", "30", now_wall=100.0)
        machine.mark_session_notice_injection()
        assert not machine.arm_session_notice("restart-soon", "29", now_wall=100.0 + interval - 1)
        assert machine.arm_session_notice("restart-soon", "20", now_wall=100.0 + interval + 1)

    def test_kinds_are_limited_independently(self) -> None:
        machine = _machine()
        assert machine.arm_session_notice("restart-soon", "30", now_wall=100.0)
        assert machine.arm_session_notice("deadline-reached", "", now_wall=101.0)
        assert machine.session_notices_pending == ("restart-soon|30", "deadline-reached|")

    def test_an_invalid_item_is_refused(self) -> None:
        machine = _machine()
        assert not machine.arm_session_notice("restart-soon", "0", now_wall=1.0)
        assert not machine.arm_session_notice("made-up", "", now_wall=1.0)
        assert machine.session_notices_pending == ()

    def test_restarted_is_armed_only_once_per_process(self) -> None:
        machine = _machine()
        assert machine.arm_session_notice("restarted", "2.1.99", now_wall=1.0)
        machine.mark_session_notice_injection()
        assert not machine.arm_session_notice("restarted", "2.1.99", now_wall=10**9)

    def test_marking_an_injection_pops_the_oldest(self) -> None:
        machine = _machine()
        machine.arm_session_notice("restart-soon", "30", now_wall=1.0)
        machine.arm_session_notice("deadline-reached", "", now_wall=1.0)
        machine.mark_session_notice_injection()
        assert machine.session_notices_pending == ("deadline-reached|",)

    def test_state_round_trips_including_the_rate_limit(self) -> None:
        machine = _machine()
        machine.arm_session_notice("restart-soon", "30", now_wall=100.0)
        other = _machine()
        other.import_state(machine.export_state())
        assert other.session_notices_pending == ("restart-soon|30",)
        other.mark_session_notice_injection()
        assert not other.arm_session_notice("restart-soon", "29", now_wall=101.0)

    def test_import_drops_what_is_not_valid_and_a_peer_without_the_keys_changes_nothing(
        self,
    ) -> None:
        machine = _machine()
        machine.arm_session_notice("deadline-reached", "", now_wall=1.0)
        machine.import_state({"state": "monitor"})
        assert machine.session_notices_pending == ("deadline-reached|",)
        machine.import_state(
            {
                "session_notices_pending": ["restart-soon|0", "junk", 7, "restart-soon|9"],
                "session_notice_last": {"restart-soon": "x", "made-up": 1.0, "restarted": 5.0},
            }
        )
        assert machine.session_notices_pending == ("restart-soon|9",)
        assert not machine.arm_session_notice("restarted", "", now_wall=10**9)


# -- what on_idle may return ----------------------------------------------------


class TestPluginResults:
    def test_a_valid_notify_is_collected_and_asks_for_no_exit(self, tmp_path: Path) -> None:
        runtime = make_runtime(
            tmp_path, {"p": _notify_body("self.api.Notify(self.api.RESTART_SOON, 30)")}
        )
        assert runtime.run_idle(NOW) is None
        assert runtime.failures == ()
        assert [(n.plugin, n.kind, n.minutes) for n in runtime.notifications] == [
            ("p", "restart-soon", 30)
        ]

    def test_a_deadline_notify_takes_no_minutes(self, tmp_path: Path) -> None:
        runtime = make_runtime(
            tmp_path, {"p": _notify_body("self.api.Notify(self.api.DEADLINE_REACHED)")}
        )
        runtime.run_idle(NOW)
        assert [(n.kind, n.minutes) for n in runtime.notifications] == [("deadline-reached", None)]

    def test_notifications_are_per_run(self, tmp_path: Path) -> None:
        runtime = make_runtime(
            tmp_path, {"p": _notify_body("self.api.Notify(self.api.DEADLINE_REACHED)")}
        )
        runtime.run_idle(NOW)
        runtime.run_idle(NOW)
        assert len(runtime.notifications) == 1

    @pytest.mark.parametrize(
        "expression",
        [
            "self.api.Notify('made-up')",
            "self.api.Notify('restart-soon')",
            "self.api.Notify('restart-soon', 0)",
            f"self.api.Notify('restart-soon', {_MAX_MINUTES + 1})",
            "self.api.Notify('restart-soon', True)",
            "self.api.Notify('restart-soon', 5.0)",
            "self.api.Notify('restart-soon', '5')",
            "self.api.Notify('deadline-reached', 5)",
            "self.api.Notify(5, None)",
            "self.api.Notify(None, None)",
        ],
    )
    def test_anything_outside_the_closed_forms_is_a_bad_result(
        self, tmp_path: Path, expression: str
    ) -> None:
        runtime = make_runtime(tmp_path, {"p": _notify_body(expression)})
        runtime.run_idle(NOW)
        assert [(f.kind, f.hook) for f in runtime.failures] == [("bad-result", "on_idle")]
        assert runtime.notifications == ()

    def test_a_notify_property_that_hangs_is_an_overrun(self, tmp_path: Path) -> None:
        body = """
    def on_start(self):
        pass
    def on_idle(self, tick):
        import time
        class Slow(self.api.Notify):
            def __init__(self):
                pass
            @property
            def kind(self):
                time.sleep(30)
                return "restart-soon"
        return Slow()
"""
        runtime = make_runtime(tmp_path, {"p": body}, hook_budget=0.2)
        runtime.run_idle(NOW)
        assert [(f.kind, f.hook) for f in runtime.failures] == [("overrun", "on_idle")]

    def test_a_notifying_plugin_does_not_stop_the_next_one(self, tmp_path: Path) -> None:
        runtime = make_runtime(
            tmp_path,
            {
                "a": _notify_body("self.api.Notify(self.api.DEADLINE_REACHED)"),
                "b": _notify_body("self.api.Notify(self.api.RESTART_SOON, 3)"),
            },
        )
        runtime.run_idle(NOW)
        assert [n.plugin for n in runtime.notifications] == ["a", "b"]


# -- typed once, at an idle point ------------------------------------------------


class TestTyping:
    def test_a_notify_is_typed_at_the_next_idle_tick_from_the_supervisors_template(
        self, tmp_path: Path
    ) -> None:
        runtime = make_runtime(
            tmp_path, {"p": _notify_body("self.api.Notify(self.api.RESTART_SOON, 25)")}
        )
        machine = _machine()
        first = _tick(tmp_path, runtime, machine)
        assert first.payload is None  # the asking tick types nothing
        second = _tick(tmp_path, runtime, machine)
        assert second.decision_value == _mod.Decision.WOULD_SESSION_NOTICE.value
        assert second.payload == _mod.render_session_notice("restart-soon", "25")

    def test_a_plugin_asking_every_tick_is_typed_once_per_interval(self, tmp_path: Path) -> None:
        runtime = make_runtime(
            tmp_path, {"p": _notify_body("self.api.Notify(self.api.RESTART_SOON, 25)")}
        )
        machine = _machine()
        payloads = [_tick(tmp_path, runtime, machine, now=NOW + n).payload for n in range(8)]
        assert len([p for p in payloads if p is not None]) == 1
        interval = _mod._NOTIFY_MIN_INTERVAL_SECONDS["restart-soon"]
        later = [
            _tick(tmp_path, runtime, machine, now=NOW + interval + 5 + n).payload for n in range(4)
        ]
        assert len([p for p in later if p is not None]) == 1

    def test_the_plugin_supplies_no_text(self, tmp_path: Path) -> None:
        body = f"""
    def on_start(self):
        pass
    def on_idle(self, tick):
        notice = self.api.Notify(self.api.DEADLINE_REACHED)
        object.__setattr__(notice, "text", "{_SECRET}")
        object.__setattr__(notice, "reason", "{_SECRET}")
        return notice
"""
        runtime = make_runtime(tmp_path, {"p": body})
        machine = _machine()
        outcomes = [_tick(tmp_path, runtime, machine) for _ in range(3)]
        for outcome in outcomes:
            assert _SECRET not in _mod._outcome_to_json(outcome)
        typed = [o.payload for o in outcomes if o.payload is not None]
        assert typed == [_mod.render_session_notice("deadline-reached", "")]

    def test_dry_run_types_a_marked_demonstration(self, tmp_path: Path) -> None:
        runtime = make_runtime(
            tmp_path, {"p": _notify_body("self.api.Notify(self.api.DEADLINE_REACHED)")}
        )
        machine = _machine()
        _tick(tmp_path, runtime, machine, dry_run=True)
        outcome = _tick(tmp_path, runtime, machine, dry_run=True)
        assert outcome.payload is not None
        assert "dry-run" in outcome.payload
        assert _mod.render_session_notice("deadline-reached", "") in outcome.payload

    @pytest.mark.parametrize(
        "facts",
        [idle_facts(input_line_empty=False), idle_facts(idle=False)],
    )
    def test_never_typed_into_a_non_empty_box_or_a_busy_session(
        self, tmp_path: Path, facts: Any
    ) -> None:
        machine = _machine()
        machine.arm_session_notice("deadline-reached", "", now_wall=NOW)
        assert _tick(tmp_path, None, machine, facts=facts).payload is None
        assert machine.session_notices_pending  # still owed

    def test_a_plugin_failure_notice_goes_first(self, tmp_path: Path) -> None:
        machine = _machine()
        machine.arm_session_notice("deadline-reached", "", now_wall=NOW)
        machine.arm_plugin_notice("p", "exception", "on_idle")
        outcome = _tick(tmp_path, None, machine)
        assert outcome.decision_value == _mod.Decision.WOULD_PLUGIN_NOTICE.value
        machine.clear_own_line()  # the first line was confirmed submitted
        follow_up = _tick(tmp_path, None, machine)
        assert follow_up.decision_value == _mod.Decision.WOULD_SESSION_NOTICE.value

    def test_not_typed_over_a_pending_own_line(self, tmp_path: Path) -> None:
        machine = _machine()
        machine.arm_session_notice("deadline-reached", "", now_wall=NOW)
        machine.mark_own_line_typed("/goal x", NOW)
        assert _tick(tmp_path, None, machine).payload is None
        assert machine.session_notices_pending

    def test_the_plugin_is_not_asked_while_a_notice_is_being_typed(self, tmp_path: Path) -> None:
        runtime = make_runtime(
            tmp_path, {"p": _notify_body("self.api.Notify(self.api.RESTART_SOON, 25)")}
        )
        machine = _machine()
        machine.arm_session_notice("deadline-reached", "", now_wall=NOW)
        assert _tick(tmp_path, runtime, machine).payload is not None
        assert runtime.half("p").idles == 0


# -- the RESTARTED notice: marker at exit, consumed once by the next supervisor ---


_SESSION = "restart-sess-1"


def _coordinator(tmp_path: Path) -> Any:
    return _mod.RestartCoordinator(
        state_path=tmp_path / "state" / "restart-request.json",
        wall_clock=lambda: NOW,
        sleep=lambda seconds: None,
    )


def _finish_a_restart(tmp_path: Path, *, wall_clock: Any = None) -> None:
    coordinator = _mod.RestartCoordinator(
        state_path=tmp_path / "state" / "restart-request.json",
        wall_clock=wall_clock or (lambda: NOW),
        sleep=lambda seconds: None,
    )
    assert coordinator.request(
        "max-age",
        "old",
        session_ids=frozenset({_SESSION}),
        machine=_machine(),
        write_master=lambda data: None,
        log=None,
        dry_run=False,
    )
    assert coordinator.finish(0, None) == _mod.EXIT_STATUS_RESTART_REQUESTED


class TestRestartedMarker:
    def test_the_marker_lives_next_to_the_request_file_in_the_state_dir(self) -> None:
        assert _mod._restarted_marker_path() == _mod._ccy_state_dir() / "restarted.json"
        assert _mod._restarted_marker_path() != _mod._restart_request_path()

    def test_finishing_a_restart_writes_a_separate_small_marker(self, tmp_path: Path) -> None:
        _finish_a_restart(tmp_path)
        marker = tmp_path / "state" / "restarted.json"
        assert json.loads(marker.read_text()) == {"session_id": _SESSION, "requested_at": NOW}
        assert stat.S_IMODE(marker.stat().st_mode) == 0o600
        # The launcher removes the request file; the marker is a different file.
        (tmp_path / "state" / "restart-request.json").unlink()
        assert marker.exists()

    def test_a_marker_that_cannot_be_written_does_not_cost_the_restart(
        self, tmp_path: Path
    ) -> None:
        coordinator = _mod.RestartCoordinator(
            state_path=tmp_path / "state" / "restart-request.json",
            marker_path=tmp_path / "request-is-a-file" / "restarted.json",
            wall_clock=lambda: NOW,
            sleep=lambda seconds: None,
        )
        (tmp_path / "request-is-a-file").write_text("a file where the directory should be")
        coordinator.request(
            "max-age",
            "old",
            session_ids=frozenset({_SESSION}),
            machine=_machine(),
            write_master=lambda data: None,
            log=None,
            dry_run=False,
        )
        assert coordinator.finish(0, None) == _mod.EXIT_STATUS_RESTART_REQUESTED
        assert (tmp_path / "state" / "restart-request.json").exists()

    def test_no_restart_means_no_marker(self, tmp_path: Path) -> None:
        assert _coordinator(tmp_path).finish(4, None) == 4
        assert not (tmp_path / "state" / "restarted.json").exists()


class TestResumedSessionId:
    @pytest.mark.parametrize(
        ("argv", "expected"),
        [
            (["claude", "--resume", "abc-123"], "abc-123"),
            (["claude", "--resume=abc-123"], "abc-123"),
            (["claude", "-r", "abc-123", "--other"], "abc-123"),
            (["claude", "--model", "x", "--resume", "abc-123"], "abc-123"),
            (["claude"], None),
            (["claude", "--resume"], None),
            (["claude", "--resume", "--other"], None),
            (["claude", "--resume", "bad id; rm"], None),
            (["claude", "--resume", ""], None),
        ],
    )
    def test_the_resumed_id_is_read_from_the_child_argv(
        self, argv: list[str], expected: str | None
    ) -> None:
        assert _mod._resumed_session_id(argv) == expected


class TestConsumeMarker:
    def _marker(self, tmp_path: Path, **fields: Any) -> Path:
        path = tmp_path / "state" / "restarted.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"session_id": _SESSION, "requested_at": NOW, **fields}))
        return path

    def test_a_matching_marker_is_consumed_exactly_once(self, tmp_path: Path) -> None:
        path = self._marker(tmp_path)
        assert _mod.consume_restarted_marker(path, _SESSION, now=NOW + 60)
        assert not path.exists()
        assert not _mod.consume_restarted_marker(path, _SESSION, now=NOW + 60)

    def test_a_marker_for_another_session_is_left_alone(self, tmp_path: Path) -> None:
        path = self._marker(tmp_path)
        assert not _mod.consume_restarted_marker(path, "some-other-session", now=NOW + 60)
        assert path.exists()

    def test_a_session_that_is_not_a_resume_consumes_nothing(self, tmp_path: Path) -> None:
        path = self._marker(tmp_path)
        assert not _mod.consume_restarted_marker(path, None, now=NOW + 60)
        assert path.exists()

    def test_a_stale_marker_is_removed_and_ignored(self, tmp_path: Path) -> None:
        path = self._marker(tmp_path)
        too_late = NOW + _mod._RESTARTED_MARKER_MAX_AGE_SECONDS + 1
        assert not _mod.consume_restarted_marker(path, _SESSION, now=too_late)
        assert not path.exists()

    @pytest.mark.parametrize("text", ["not json", "[]", '"x"', "{}", '{"session_id": 5}'])
    def test_a_garbled_marker_is_removed_and_ignored(self, tmp_path: Path, text: str) -> None:
        path = tmp_path / "state" / "restarted.json"
        path.parent.mkdir(parents=True)
        path.write_text(text)
        assert not _mod.consume_restarted_marker(path, _SESSION, now=NOW)
        assert not path.exists()

    def test_no_marker_is_no_notice(self, tmp_path: Path) -> None:
        assert not _mod.consume_restarted_marker(tmp_path / "none.json", _SESSION, now=NOW)


def _fake_claude(tmp_path: Path, output: str, *, code: int = 0, sleep: float = 0.0) -> str:
    script = tmp_path / "fake-claude"
    script.write_text(
        f"#!{sys.executable}\nimport sys, time\ntime.sleep({sleep})\n"
        f"sys.stdout.write({output!r})\nsys.exit({code})\n"
    )
    script.chmod(0o700)
    return str(script)


class TestClaudeVersion:
    @pytest.mark.parametrize(
        ("output", "expected"),
        [
            ("2.1.99 (Claude Code)\n", "2.1.99"),
            ("2.1.99\n", "2.1.99"),
            ("2.1.99-beta.1 (Claude Code)", "2.1.99-beta.1"),
            ("Python 3.11.9\n", None),
            ("", None),
            ("1.2.3; rm -rf /\n", None),
            ("version 2.1.99\n", None),
            ("9" * 100 + ".1.1\n", None),
        ],
    )
    def test_the_version_is_the_first_token_and_must_look_like_a_version(
        self, tmp_path: Path, output: str, expected: str | None
    ) -> None:
        assert _mod._claude_version(_fake_claude(tmp_path, output)) == expected

    def test_a_failing_command_has_no_version(self, tmp_path: Path) -> None:
        assert _mod._claude_version(_fake_claude(tmp_path, "2.1.99\n", code=1)) is None

    def test_a_missing_command_has_no_version(self, tmp_path: Path) -> None:
        assert _mod._claude_version(str(tmp_path / "does-not-exist")) is None

    def test_a_slow_command_is_cut_off_at_the_bound(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_mod, "_CLAUDE_VERSION_TIMEOUT_SECONDS", 0.3)
        started = _mod.time.monotonic()
        assert _mod._claude_version(_fake_claude(tmp_path, "2.1.99\n", sleep=30)) is None
        assert _mod.time.monotonic() - started < 10


class TestArmRestartedNotice:
    def _write_marker(self, tmp_path: Path) -> Path:
        marker = tmp_path / "state" / "restarted.json"
        marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({"session_id": _SESSION, "requested_at": NOW}))
        return marker

    def test_a_resume_of_the_restarted_session_arms_the_notice_with_the_version(
        self, tmp_path: Path
    ) -> None:
        marker = self._write_marker(tmp_path)
        machine = _machine()
        claude = _fake_claude(tmp_path, "2.1.99 (Claude Code)\n")
        assert _mod.arm_restarted_notice(
            machine, [claude, "--resume", _SESSION], marker_path=marker, now=NOW + 5
        )
        assert machine.session_notices_pending == ("restarted|2.1.99",)
        assert not marker.exists()

    def test_an_unreadable_version_falls_back_to_the_installed_version(
        self, tmp_path: Path
    ) -> None:
        marker = self._write_marker(tmp_path)
        machine = _machine()
        claude = _fake_claude(tmp_path, "not a version\n")
        assert _mod.arm_restarted_notice(
            machine, [claude, "--resume", _SESSION], marker_path=marker, now=NOW + 5
        )
        assert machine.session_notices_pending == ("restarted|",)

    def test_a_fresh_launch_arms_nothing_and_runs_nothing(self, tmp_path: Path) -> None:
        marker = self._write_marker(tmp_path)
        machine = _machine()
        ran = tmp_path / "ran"
        script = tmp_path / "claude-that-records"
        script.write_text(f"#!{sys.executable}\nopen({str(ran)!r}, 'w').close()\n")
        script.chmod(0o700)
        assert not _mod.arm_restarted_notice(machine, [str(script)], marker_path=marker, now=NOW)
        assert machine.session_notices_pending == ()
        assert not ran.exists()
        assert marker.exists()

    def test_it_never_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def explode(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("bug")

        monkeypatch.setattr(_mod, "consume_restarted_marker", explode)
        assert not _mod.arm_restarted_notice(
            _machine(), ["claude", "--resume", _SESSION], marker_path=tmp_path / "m.json", now=NOW
        )


_CHILD = r"""
import os, sys, time, select
log = open(sys.argv[1], "ab", buffering=0)
deadline = time.time() + float(sys.argv[2])
while time.time() < deadline:
    ready, _, _ = select.select([0], [], [], 0.05)
    if ready:
        log.write(os.read(0, 4096))
sys.exit(6)
"""


class TestSuperviseTypesTheRestartedNotice:
    def _run(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv_tail: list[str]) -> str:
        monkeypatch.setattr(_mod, "cached_own_session_ids", lambda *a, **k: frozenset({_SESSION}))
        monkeypatch.setattr(_mod, "_claude_version", lambda executable: "2.1.99")
        monkeypatch.setenv("CCY_SUPERVISOR_STATE_DIR", str(tmp_path / "state"))
        received = tmp_path / "received.bin"
        stdin_fd = os.open(os.devnull, os.O_RDONLY)
        try:
            code = _mod.supervise(
                [sys.executable, "-c", _CHILD, str(received), "2.0", *argv_tail],
                dry_run=False,
                log=_mod.DecisionLog(tmp_path / "decision.log"),
                stdin_fd=stdin_fd,
                poll_seconds=0.05,
                idle_floor_seconds=0.1,
                sidecar_dir=tmp_path / "untracked" / "context-sidecar",
                restart_coordinator=_coordinator(tmp_path),
            )
        finally:
            os.close(stdin_fd)
        assert code == 6
        return received.read_bytes().decode() if received.exists() else ""

    def test_the_resumed_session_is_told_once_what_version_it_is_on(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _finish_a_restart(tmp_path, wall_clock=_mod.time.time)
        typed = self._run(tmp_path, monkeypatch, ["--resume", _SESSION])
        assert typed.count("session notice") == 1
        assert "now on version 2.1.99" in typed
        assert not (tmp_path / "state" / "restarted.json").exists()

    def test_a_second_launch_is_not_told_again(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _finish_a_restart(tmp_path, wall_clock=_mod.time.time)
        self._run(tmp_path, monkeypatch, ["--resume", _SESSION])
        (tmp_path / "received.bin").unlink()
        assert "session notice" not in self._run(tmp_path, monkeypatch, ["--resume", _SESSION])

    def test_a_different_session_is_not_told(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _finish_a_restart(tmp_path, wall_clock=_mod.time.time)
        assert "session notice" not in self._run(tmp_path, monkeypatch, ["--resume", "other"])
        assert (tmp_path / "state" / "restarted.json").exists()

    def test_a_fresh_launch_is_not_told(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _finish_a_restart(tmp_path, wall_clock=_mod.time.time)
        assert "session notice" not in self._run(tmp_path, monkeypatch, [])
