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
from tests.unit.utils.test_session_thread_group import DAEMON_ARGV, add_proc

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

# Pids of the fake tree: two hooks under the same `claude daemon run` (589).
_FRONT_END_DAEMON = 589
_HOOK_THREAD_1 = 701
_HOOK_THREAD_2 = 702
_HOOK_OTHER_SESSION = 801


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
    add_proc(root, _FRONT_END_DAEMON, 1, DAEMON_ARGV, start=777)
    for worker, hook in ((590, _HOOK_THREAD_1), (591, _HOOK_THREAD_2)):
        add_proc(root, worker, _FRONT_END_DAEMON, ["claude", "bg-pty-host"])
        add_proc(root, hook, worker, ["relay"])
    # A separate session: no `claude daemon run` above it.
    add_proc(root, 800, 1, ["claude"])
    add_proc(root, _HOOK_OTHER_SESSION, 800, ["relay"])
    return root


def _wire(handler: Any, monkeypatch: pytest.MonkeyPatch, config: Config, tmp_path: Path) -> None:
    monkeypatch.setattr(handler, "_load_config", lambda: config)
    monkeypatch.setattr(handler, "_proc_root", lambda: tmp_path / "proc")
    monkeypatch.setattr(handler, "_thread_groups_path", lambda: tmp_path / "state" / "groups.json")


def _stop(session: str, pid: int | None, crons: list[dict[str, Any]] | None = None) -> dict:
    payload: dict[str, Any] = {
        HookInputField.SESSION_ID: session,
        "stop_hook_active": False,
        "session_crons": [] if crons is None else crons,
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
        payload = _stop("thread-1", _HOOK_THREAD_1)

        assert stop_handler.matches(payload) is True
        assert stop_handler.handle(payload).decision is Decision.DENY

    def test_a_second_thread_is_not_required_to_hold_them(
        self, stop_handler: CronStopEnforcerHandler
    ) -> None:
        first = _stop("thread-1", _HOOK_THREAD_1)
        second = _stop("thread-2", _HOOK_THREAD_2)
        stop_handler.matches(first)  # the initial thread is seen first

        assert stop_handler.matches(second) is False
        assert stop_handler.handle(second).decision is Decision.ALLOW

    def test_the_initial_thread_stays_the_holder_after_the_second_appears(
        self, stop_handler: CronStopEnforcerHandler
    ) -> None:
        stop_handler.matches(_stop("thread-1", _HOOK_THREAD_1))
        stop_handler.matches(_stop("thread-2", _HOOK_THREAD_2))

        assert stop_handler.matches(_stop("thread-1", _HOOK_THREAD_1)) is True

    def test_a_session_with_no_daemon_run_ancestor_is_unchanged(
        self, stop_handler: CronStopEnforcerHandler
    ) -> None:
        for session in ("solo-a", "solo-b"):
            payload = _stop(session, _HOOK_OTHER_SESSION)
            assert stop_handler.matches(payload) is True
            assert stop_handler.handle(payload).decision is Decision.DENY

    def test_a_payload_without_a_peer_pid_is_unchanged(
        self, stop_handler: CronStopEnforcerHandler
    ) -> None:
        stop_handler.matches(_stop("thread-1", _HOOK_THREAD_1))

        assert stop_handler.matches(_stop("thread-2", None)) is True

    def test_an_unreadable_proc_is_unchanged(
        self,
        stop_handler: CronStopEnforcerHandler,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(stop_handler, "_proc_root", lambda: tmp_path / "no-such-proc")

        assert stop_handler.matches(_stop("thread-1", _HOOK_THREAD_1)) is True
        assert stop_handler.matches(_stop("thread-2", _HOOK_THREAD_2)) is True

    def test_a_reused_ancestor_pid_with_a_new_start_time_is_a_new_group(
        self, stop_handler: CronStopEnforcerHandler, proc_root: Path
    ) -> None:
        stop_handler.matches(_stop("old-thread-1", _HOOK_THREAD_1))
        assert stop_handler.matches(_stop("old-thread-2", _HOOK_THREAD_2)) is False

        # The same pid now belongs to a different `claude daemon run`.
        add_proc_stat = proc_root / str(_FRONT_END_DAEMON) / "stat"
        add_proc_stat.write_text(add_proc_stat.read_text().replace(" 777 ", " 888 "))

        assert stop_handler.matches(_stop("new-thread-1", _HOOK_THREAD_1)) is True

    def test_the_holder_survives_a_restart(
        self,
        stop_handler: CronStopEnforcerHandler,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        stop_handler.matches(_stop("thread-1", _HOOK_THREAD_1))

        restarted = CronStopEnforcerHandler()
        _wire(restarted, monkeypatch, _config(), tmp_path)

        assert restarted.matches(_stop("thread-2", _HOOK_THREAD_2)) is False
        assert restarted.matches(_stop("thread-1", _HOOK_THREAD_1)) is True

    def test_the_option_off_makes_every_thread_hold_them(
        self,
        stop_handler: CronStopEnforcerHandler,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _wire(stop_handler, monkeypatch, _config(initial_thread_only=False), tmp_path)
        stop_handler.matches(_stop("thread-1", _HOOK_THREAD_1))

        assert stop_handler.matches(_stop("thread-2", _HOOK_THREAD_2)) is True


class TestSubagentStopEnforcer:
    def test_a_second_thread_is_not_required_to_hold_them(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, proc_root: Path
    ) -> None:
        handler = CronSubagentStopEnforcerHandler()
        _wire(handler, monkeypatch, _config(), tmp_path)

        assert handler.matches(_stop("thread-1", _HOOK_THREAD_1)) is True
        assert handler.matches(_stop("thread-2", _HOOK_THREAD_2)) is False


class TestAssertor:
    def test_the_initial_thread_is_told_the_declared_jobs(
        self, start_handler: PersistentCronAssertorHandler
    ) -> None:
        context = "\n".join(start_handler.handle(_start("thread-1", _HOOK_THREAD_1)).context)

        assert "DECLARED PERSISTENT CRONS (1 job)" in context
        assert "sdlc" in context

    def test_a_second_thread_is_told_it_holds_none_and_why(
        self, start_handler: PersistentCronAssertorHandler
    ) -> None:
        start_handler.handle(_start("thread-1", _HOOK_THREAD_1))
        second = _start("thread-2", _HOOK_THREAD_2)

        assert start_handler.matches(second) is True
        context = "\n".join(start_handler.handle(second).context)

        assert "holds none" in context
        assert "thread-1" in context
        assert "initial_thread_only" in context
        assert "23 * * * *" not in context

    def test_a_session_with_no_daemon_run_ancestor_is_unchanged(
        self, start_handler: PersistentCronAssertorHandler
    ) -> None:
        for session in ("solo-a", "solo-b"):
            context = "\n".join(start_handler.handle(_start(session, _HOOK_OTHER_SESSION)).context)
            assert "DECLARED PERSISTENT CRONS (1 job)" in context

    def test_the_option_off_tells_every_thread(
        self,
        start_handler: PersistentCronAssertorHandler,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _wire(start_handler, monkeypatch, _config(initial_thread_only=False), tmp_path)
        start_handler.handle(_start("thread-1", _HOOK_THREAD_1))

        context = "\n".join(start_handler.handle(_start("thread-2", _HOOK_THREAD_2)).context)

        assert "DECLARED PERSISTENT CRONS (1 job)" in context


class TestConfigOption:
    def test_it_defaults_on(self) -> None:
        assert PersistentCronsConfig().initial_thread_only is True

    @pytest.mark.parametrize("value", ["yes", "false", 1, None])
    def test_a_non_boolean_is_rejected(self, value: object) -> None:
        with pytest.raises(ValueError, match="initial_thread_only"):
            PersistentCronsConfig.model_validate({"initial_thread_only": value})
