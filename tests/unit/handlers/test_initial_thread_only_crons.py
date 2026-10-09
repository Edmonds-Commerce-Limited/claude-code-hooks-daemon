"""Only a session's initial thread holds the declared crons (Plan 00470 Task 6.4).

Real handlers, a fake ``/proc`` tree in a tmp dir, and a real on-disk registry.
A later thread of one Claude Code session is a fresh session to the hooks, so
without this ``cron_stop_enforcer`` would demand the declared crons at its stop
and ``persistent_cron_assertor`` would tell it to create them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tests.fake_proc import (
    DAEMON_ARGV,
    INITIAL_WORKER_ARGV,
    SPARE_WORKER_ARGV,
    add_proc,
    add_thread,
    remove_proc,
)

from claude_code_hooks_daemon.config.models import (
    Config,
    PersistentCronConfig,
    PersistentCronsConfig,
)
from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.session_start.persistent_cron_assertor import (
    PersistentCronAssertorHandler,
)
from claude_code_hooks_daemon.handlers.stop.cron_stop_enforcer import CronStopEnforcerHandler
from claude_code_hooks_daemon.handlers.subagent_stop.cron_subagent_stop_enforcer import (
    CronSubagentStopEnforcerHandler,
)

_JOB = PersistentCronConfig(id="sdlc", schedule="23 * * * *", prompt="Run the skill.")

# Pids of the fake tree: two threads under the same `claude daemon run` (589).
_DAEMON = 589
_INITIAL_WORKER, _INITIAL_HOOK = 591, 700
_SPARE_WORKER, _SPARE_HOOK = 592, 701
_SECOND_SPARE_WORKER, _SECOND_SPARE_HOOK = 593, 702
# A separate session: no `claude daemon run` above it.
_SOLO_HOOK = 801


def _config(*, initial_thread_only: bool = True) -> Config:
    return Config(
        persistent_crons=PersistentCronsConfig(
            enabled=True, jobs=[_JOB], initial_thread_only=initial_thread_only
        )
    )


@pytest.fixture
def proc_root(tmp_path: Path) -> Path:
    root = tmp_path / "proc"
    root.mkdir()
    add_proc(root, 1, 0, ["init"])
    add_proc(root, _DAEMON, 1, DAEMON_ARGV, start=777)
    add_thread(root, _DAEMON, _INITIAL_WORKER, _INITIAL_HOOK, INITIAL_WORKER_ARGV)
    add_thread(root, _DAEMON, _SPARE_WORKER, _SPARE_HOOK, SPARE_WORKER_ARGV)
    add_proc(root, 800, 1, ["claude"])
    add_proc(root, _SOLO_HOOK, 800, ["relay"])
    return root


def _wire(handler: Any, monkeypatch: pytest.MonkeyPatch, config: Config, tmp_path: Path) -> None:
    monkeypatch.setattr(handler, "_load_config", lambda: config)
    monkeypatch.setattr(handler, "_proc_root", lambda: tmp_path / "proc")
    monkeypatch.setattr(handler, "_thread_groups_path", lambda: tmp_path / "state" / "groups.json")


def _stop(session: str, pid: int | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        HookInputField.SESSION_ID: session,
        "stop_hook_active": False,
        "session_crons": [],
    }
    if pid is not None:
        payload[HookInputField.PEER_PID] = pid
    return payload


def _start(session: str, pid: int | None) -> dict[str, Any]:
    payload: dict[str, Any] = {HookInputField.SESSION_ID: session, "source": "startup"}
    if pid is not None:
        payload[HookInputField.PEER_PID] = pid
    return payload


@pytest.fixture
def stop_handler(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, proc_root: Path
) -> CronStopEnforcerHandler:
    handler = CronStopEnforcerHandler()
    _wire(handler, monkeypatch, _config(), tmp_path)
    return handler


@pytest.fixture
def start_handler(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, proc_root: Path
) -> PersistentCronAssertorHandler:
    handler = PersistentCronAssertorHandler()
    _wire(handler, monkeypatch, _config(), tmp_path)
    return handler


class TestStopEnforcer:
    def test_the_initial_thread_is_still_required_to_hold_the_crons(
        self, stop_handler: CronStopEnforcerHandler
    ) -> None:
        payload = _stop("thread-1", _INITIAL_HOOK)

        assert stop_handler.matches(payload) is True
        assert stop_handler.handle(payload).decision is Decision.DENY

    def test_a_second_thread_is_not_required_to_hold_them(
        self, stop_handler: CronStopEnforcerHandler
    ) -> None:
        stop_handler.matches(_stop("thread-1", _INITIAL_HOOK))
        second = _stop("thread-2", _SPARE_HOOK)

        assert stop_handler.matches(second) is False
        assert stop_handler.handle(second).decision is Decision.ALLOW

    def test_a_new_thread_arriving_first_does_not_take_the_crons_from_the_initial_thread(
        self, stop_handler: CronStopEnforcerHandler
    ) -> None:
        """The new thread's SessionStart/Stop usually precedes any event of the
        initial thread, which produced no group before the second thread existed."""
        assert stop_handler.matches(_stop("thread-2-new", _SPARE_HOOK)) is False

        initial = _stop("thread-1-initial", _INITIAL_HOOK)

        assert stop_handler.matches(initial) is True
        assert stop_handler.handle(initial).decision is Decision.DENY

    def test_the_initial_thread_stays_the_holder_after_the_second_appears(
        self, stop_handler: CronStopEnforcerHandler
    ) -> None:
        stop_handler.matches(_stop("thread-1", _INITIAL_HOOK))
        stop_handler.matches(_stop("thread-2", _SPARE_HOOK))

        assert stop_handler.matches(_stop("thread-1", _INITIAL_HOOK)) is True

    def test_a_clear_in_the_initial_thread_keeps_holding(
        self, stop_handler: CronStopEnforcerHandler
    ) -> None:
        stop_handler.matches(_stop("before-clear", _INITIAL_HOOK))

        assert stop_handler.matches(_stop("after-clear", _INITIAL_HOOK)) is True
        assert stop_handler.matches(_stop("thread-2", _SPARE_HOOK)) is False

    def test_when_the_initial_thread_exits_the_next_thread_holds(
        self, stop_handler: CronStopEnforcerHandler, proc_root: Path
    ) -> None:
        stop_handler.matches(_stop("thread-1", _INITIAL_HOOK))
        assert stop_handler.matches(_stop("thread-2", _SPARE_HOOK)) is False

        remove_proc(proc_root, _INITIAL_HOOK)
        remove_proc(proc_root, _INITIAL_WORKER)

        reborn = _stop("thread-2-after", _SPARE_HOOK)
        assert stop_handler.matches(reborn) is True
        assert stop_handler.handle(reborn).decision is Decision.DENY

        add_thread(proc_root, _DAEMON, _SECOND_SPARE_WORKER, _SECOND_SPARE_HOOK, SPARE_WORKER_ARGV)
        assert stop_handler.matches(_stop("thread-3", _SECOND_SPARE_HOOK)) is False

    def test_a_session_with_no_daemon_run_ancestor_is_unchanged(
        self, stop_handler: CronStopEnforcerHandler
    ) -> None:
        for session in ("solo-a", "solo-b"):
            payload = _stop(session, _SOLO_HOOK)
            assert stop_handler.matches(payload) is True
            assert stop_handler.handle(payload).decision is Decision.DENY

    def test_a_payload_without_a_peer_pid_is_unchanged(
        self, stop_handler: CronStopEnforcerHandler
    ) -> None:
        stop_handler.matches(_stop("thread-1", _INITIAL_HOOK))

        assert stop_handler.matches(_stop("thread-2", None)) is True

    def test_an_unreadable_proc_is_unchanged(
        self,
        stop_handler: CronStopEnforcerHandler,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(stop_handler, "_proc_root", lambda: tmp_path / "no-such-proc")

        assert stop_handler.matches(_stop("thread-1", _INITIAL_HOOK)) is True
        assert stop_handler.matches(_stop("thread-2", _SPARE_HOOK)) is True

    def test_an_unrecognised_worker_shape_is_unchanged(
        self, stop_handler: CronStopEnforcerHandler, proc_root: Path
    ) -> None:
        add_thread(proc_root, _DAEMON, 600, 750, ["something", "else"])

        assert stop_handler.matches(_stop("odd-a", 750)) is True
        assert stop_handler.matches(_stop("odd-b", 750)) is True

    def test_a_reused_ancestor_pid_with_a_new_start_time_is_a_new_group(
        self, stop_handler: CronStopEnforcerHandler, proc_root: Path
    ) -> None:
        stop_handler.matches(_stop("old-thread-1", _INITIAL_HOOK))
        assert stop_handler.matches(_stop("old-thread-2", _SPARE_HOOK)) is False

        # The same pid now belongs to a different `claude daemon run`, whose only
        # live thread is the spare: with no initial thread there, it holds.
        stat = proc_root / str(_DAEMON) / "stat"
        stat.write_text(stat.read_text().replace(" 777 ", " 888 "))
        remove_proc(proc_root, _INITIAL_HOOK)
        remove_proc(proc_root, _INITIAL_WORKER)

        assert stop_handler.matches(_stop("new-thread", _SPARE_HOOK)) is True

    def test_the_holder_survives_a_restart(
        self,
        stop_handler: CronStopEnforcerHandler,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        stop_handler.matches(_stop("thread-1", _INITIAL_HOOK))

        restarted = CronStopEnforcerHandler()
        _wire(restarted, monkeypatch, _config(), tmp_path)

        assert restarted.matches(_stop("thread-2", _SPARE_HOOK)) is False
        assert restarted.matches(_stop("thread-1", _INITIAL_HOOK)) is True

    def test_the_option_off_makes_every_thread_hold_them(
        self,
        stop_handler: CronStopEnforcerHandler,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _wire(stop_handler, monkeypatch, _config(initial_thread_only=False), tmp_path)
        stop_handler.matches(_stop("thread-1", _INITIAL_HOOK))

        assert stop_handler.matches(_stop("thread-2", _SPARE_HOOK)) is True

    def test_one_stop_walks_the_process_tree_once(
        self, stop_handler: CronStopEnforcerHandler, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        calls: list[int] = []

        def counting_root() -> Path:
            calls.append(1)
            return tmp_path / "proc"

        monkeypatch.setattr(stop_handler, "_proc_root", counting_root)
        payload = _stop("thread-1", _INITIAL_HOOK)

        stop_handler.matches(payload)
        stop_handler.handle(payload)

        assert len(calls) == 1


class TestSubagentStopEnforcer:
    def test_a_second_thread_is_not_required_to_hold_them(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, proc_root: Path
    ) -> None:
        handler = CronSubagentStopEnforcerHandler()
        _wire(handler, monkeypatch, _config(), tmp_path)

        assert handler.matches(_stop("thread-1", _INITIAL_HOOK)) is True
        assert handler.matches(_stop("thread-2", _SPARE_HOOK)) is False


class TestAssertor:
    def test_the_initial_thread_is_told_the_declared_jobs(
        self, start_handler: PersistentCronAssertorHandler
    ) -> None:
        context = "\n".join(start_handler.handle(_start("thread-1", _INITIAL_HOOK)).context)

        assert "DECLARED PERSISTENT CRONS (1 job)" in context
        assert "sdlc" in context

    def test_a_second_thread_is_told_it_holds_none_and_why(
        self, start_handler: PersistentCronAssertorHandler
    ) -> None:
        start_handler.handle(_start("thread-1", _INITIAL_HOOK))
        second = _start("thread-2", _SPARE_HOOK)

        assert start_handler.matches(second) is True
        context = "\n".join(start_handler.handle(second).context)

        assert "holds none" in context
        assert "thread-1" in context
        assert "initial_thread_only" in context
        assert "23 * * * *" not in context

    def test_a_new_thread_starting_first_is_told_it_holds_none_without_a_name(
        self, start_handler: PersistentCronAssertorHandler
    ) -> None:
        context = "\n".join(start_handler.handle(_start("thread-2", _SPARE_HOOK)).context)

        assert "holds none" in context
        assert "None" not in context

        initial = "\n".join(start_handler.handle(_start("thread-1", _INITIAL_HOOK)).context)
        assert "DECLARED PERSISTENT CRONS (1 job)" in initial

    def test_a_session_with_no_daemon_run_ancestor_is_unchanged(
        self, start_handler: PersistentCronAssertorHandler
    ) -> None:
        for session in ("solo-a", "solo-b"):
            context = "\n".join(start_handler.handle(_start(session, _SOLO_HOOK)).context)
            assert "DECLARED PERSISTENT CRONS (1 job)" in context

    def test_the_option_off_tells_every_thread(
        self,
        start_handler: PersistentCronAssertorHandler,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _wire(start_handler, monkeypatch, _config(initial_thread_only=False), tmp_path)
        start_handler.handle(_start("thread-1", _INITIAL_HOOK))

        context = "\n".join(start_handler.handle(_start("thread-2", _SPARE_HOOK)).context)

        assert "DECLARED PERSISTENT CRONS (1 job)" in context


class TestConfigOption:
    def test_it_defaults_on(self) -> None:
        assert PersistentCronsConfig().initial_thread_only is True

    @pytest.mark.parametrize("value", ["yes", "false", 1, None])
    def test_a_non_boolean_is_rejected(self, value: object) -> None:
        with pytest.raises(ValueError, match="initial_thread_only"):
            PersistentCronsConfig.model_validate({"initial_thread_only": value})
