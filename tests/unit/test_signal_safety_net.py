"""Plan 00466 N59 — the test run must never signal init, its own group or its callers.

A unit test's ``MagicMock`` Popen had a pid that coerces to 1, and
``os.killpg(os.getpgid(1), SIGKILL)`` killed the container's init twice. The
session-wide net in ``tests/signal_safety_net.py`` wraps ``os.kill`` and
``os.killpg`` and refuses such a target BEFORE any signal is delivered.

Every refusal here is proven on a net whose "real" delegates are recording
fakes, so a defect in the net can never deliver a signal. The installed net is
exercised only after the test has proven the wrapper is in place and that it
refuses the target in question.
"""

from __future__ import annotations

import os
import signal
import subprocess  # nosec B404 - spawns a trusted `sleep` child only
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from tests.signal_safety_net import (
    CLAUDE_CODE_PROCESS_NAME,
    DangerousSignalError,
    ProtectedTargets,
    SignalSafetyNet,
    installed_net,
    protected_targets_from_proc,
)

#: Stand-ins for processes this test process must never signal.
_OWN_PID = 4242
_OWN_GROUP = 4200
_ANCESTOR_PID = 4100
_ANCESTOR_GROUP = 4000
_CLAUDE_PID = 3900
#: A pid nothing protects, which the net must pass through untouched.
_UNRELATED_PID = 7777


class _RecordingDelegates:
    """Fake ``os.kill`` / ``os.killpg``: records calls, never signals."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object, object]] = []

    def kill(self, pid: object, sig: object) -> None:
        self.calls.append(("kill", pid, sig))

    def killpg(self, pgid: object, sig: object) -> None:
        self.calls.append(("killpg", pgid, sig))


def _fixed_targets() -> ProtectedTargets:
    return ProtectedTargets(
        pids=frozenset({1, _OWN_PID, _ANCESTOR_PID, _CLAUDE_PID}),
        groups=frozenset({1, _OWN_GROUP, _ANCESTOR_GROUP}),
    )


@pytest.fixture
def delegates() -> _RecordingDelegates:
    return _RecordingDelegates()


@pytest.fixture
def net(delegates: _RecordingDelegates) -> SignalSafetyNet:
    return SignalSafetyNet(
        real_kill=delegates.kill,
        real_killpg=delegates.killpg,
        protected_targets=_fixed_targets,
    )


class TestKillRefusesEveryTargetThatIsNotProvablySomeoneElse:
    @pytest.mark.parametrize("pid", [1, 0, -1])
    def test_init_own_group_and_broadcast_are_refused(
        self, net: SignalSafetyNet, delegates: _RecordingDelegates, pid: int
    ) -> None:
        with pytest.raises(DangerousSignalError):
            net.kill(pid, signal.SIGKILL)
        assert delegates.calls == []

    def test_a_magicmock_pid_is_refused_because_it_coerces_to_one(
        self, net: SignalSafetyNet, delegates: _RecordingDelegates
    ) -> None:
        with pytest.raises(DangerousSignalError):
            net.kill(MagicMock().pid, signal.SIGKILL)
        assert delegates.calls == []

    def test_a_bool_pid_is_refused(
        self, net: SignalSafetyNet, delegates: _RecordingDelegates
    ) -> None:
        with pytest.raises(DangerousSignalError):
            net.kill(True, signal.SIGTERM)
        assert delegates.calls == []

    @pytest.mark.parametrize("pid", [_OWN_PID, _ANCESTOR_PID, _CLAUDE_PID])
    def test_this_process_its_ancestors_and_claude_code_are_refused(
        self, net: SignalSafetyNet, delegates: _RecordingDelegates, pid: int
    ) -> None:
        with pytest.raises(DangerousSignalError):
            net.kill(pid, signal.SIGTERM)
        assert delegates.calls == []

    @pytest.mark.parametrize("group", [_OWN_GROUP, _ANCESTOR_GROUP])
    def test_a_negative_pid_naming_a_protected_group_is_refused(
        self, net: SignalSafetyNet, delegates: _RecordingDelegates, group: int
    ) -> None:
        with pytest.raises(DangerousSignalError):
            net.kill(-group, signal.SIGKILL)
        assert delegates.calls == []

    def test_an_unrelated_pid_passes_through_unchanged(
        self, net: SignalSafetyNet, delegates: _RecordingDelegates
    ) -> None:
        net.kill(_UNRELATED_PID, signal.SIGTERM)
        assert delegates.calls == [("kill", _UNRELATED_PID, signal.SIGTERM)]

    def test_an_unrelated_group_passes_through_unchanged(
        self, net: SignalSafetyNet, delegates: _RecordingDelegates
    ) -> None:
        net.kill(-_UNRELATED_PID, signal.SIGTERM)
        assert delegates.calls == [("kill", -_UNRELATED_PID, signal.SIGTERM)]

    def test_the_existence_probe_is_never_refused(
        self, net: SignalSafetyNet, delegates: _RecordingDelegates
    ) -> None:
        net.kill(1, 0)
        assert delegates.calls == [("kill", 1, 0)]

    def test_a_pid_that_is_not_an_integer_reaches_the_real_call_to_fail_there(
        self, net: SignalSafetyNet, delegates: _RecordingDelegates
    ) -> None:
        net.kill("not-a-pid", signal.SIGTERM)
        assert delegates.calls == [("kill", "not-a-pid", signal.SIGTERM)]


class TestKillpgRefusesInitsOwnAndCallersGroups:
    @pytest.mark.parametrize("pgid", [1, 0, -5])
    def test_init_group_own_group_alias_and_nonsense_are_refused(
        self, net: SignalSafetyNet, delegates: _RecordingDelegates, pgid: int
    ) -> None:
        with pytest.raises(DangerousSignalError):
            net.killpg(pgid, signal.SIGKILL)
        assert delegates.calls == []

    @pytest.mark.parametrize("pgid", [_OWN_GROUP, _ANCESTOR_GROUP, _OWN_PID, _CLAUDE_PID])
    def test_a_protected_group_or_one_led_by_a_protected_pid_is_refused(
        self, net: SignalSafetyNet, delegates: _RecordingDelegates, pgid: int
    ) -> None:
        with pytest.raises(DangerousSignalError):
            net.killpg(pgid, signal.SIGKILL)
        assert delegates.calls == []

    def test_a_magicmock_group_is_refused(
        self, net: SignalSafetyNet, delegates: _RecordingDelegates
    ) -> None:
        with pytest.raises(DangerousSignalError):
            net.killpg(MagicMock().pid, signal.SIGKILL)
        assert delegates.calls == []

    def test_an_unrelated_group_passes_through_unchanged(
        self, net: SignalSafetyNet, delegates: _RecordingDelegates
    ) -> None:
        net.killpg(_UNRELATED_PID, signal.SIGKILL)
        assert delegates.calls == [("killpg", _UNRELATED_PID, signal.SIGKILL)]

    def test_the_existence_probe_is_never_refused(
        self, net: SignalSafetyNet, delegates: _RecordingDelegates
    ) -> None:
        net.killpg(1, 0)
        assert delegates.calls == [("killpg", 1, 0)]


class TestARefusalCannotBeSwallowed:
    def test_a_refusal_caught_by_the_code_under_test_is_still_recorded(
        self, net: SignalSafetyNet
    ) -> None:
        try:
            net.kill(1, signal.SIGKILL)
        except Exception as caught:  # the shape of code that would hide it
            assert isinstance(caught, DangerousSignalError)
        violations = net.drain_violations()
        assert len(violations) == 1
        assert "pid 1" in violations[0]
        assert net.drain_violations() == []


def _write_proc_entry(
    proc: Path, pid: int, *, ppid: int, pgrp: int, comm: str, argv: list[str]
) -> None:
    entry = proc / str(pid)
    entry.mkdir()
    (entry / "stat").write_text(f"{pid} ({comm}) S {ppid} {pgrp} {pgrp} 0 -1\n", encoding="utf-8")
    (entry / "comm").write_text(f"{comm}\n", encoding="utf-8")
    (entry / "cmdline").write_bytes(b"\0".join(arg.encode() for arg in argv) + b"\0")


class TestProtectedTargetsAreReadFromProc:
    def test_own_pid_every_ancestor_and_their_groups_are_protected(self, tmp_path: Path) -> None:
        proc = tmp_path / "proc"
        proc.mkdir()
        _write_proc_entry(proc, 1, ppid=0, pgrp=1, comm="tini", argv=["tini"])
        _write_proc_entry(proc, 50, ppid=1, pgrp=50, comm="bash", argv=["bash"])
        _write_proc_entry(proc, 60, ppid=50, pgrp=60, comm="python3", argv=["pytest"])

        targets = protected_targets_from_proc(own_pid=60, proc_root=proc)

        assert {1, 50, 60} <= targets.pids
        assert {1, 50, 60} <= targets.groups

    def test_a_claude_code_process_that_is_not_an_ancestor_is_still_protected(
        self, tmp_path: Path
    ) -> None:
        proc = tmp_path / "proc"
        proc.mkdir()
        _write_proc_entry(proc, 1, ppid=0, pgrp=1, comm="tini", argv=["tini"])
        _write_proc_entry(proc, 60, ppid=1, pgrp=60, comm="python3", argv=["pytest"])
        _write_proc_entry(
            proc, 70, ppid=1, pgrp=70, comm="node", argv=[CLAUDE_CODE_PROCESS_NAME, "--continue"]
        )
        _write_proc_entry(proc, 80, ppid=1, pgrp=80, comm=CLAUDE_CODE_PROCESS_NAME, argv=["x"])
        _write_proc_entry(proc, 90, ppid=1, pgrp=90, comm="sleep", argv=["sleep", "9"])

        targets = protected_targets_from_proc(own_pid=60, proc_root=proc)

        assert {70, 80} <= targets.pids
        assert {70, 80} <= targets.groups
        assert 90 not in targets.pids
        assert 90 not in targets.groups

    def test_the_live_view_protects_this_process_its_parent_group_and_init(self) -> None:
        targets = protected_targets_from_proc(own_pid=os.getpid(), proc_root=Path("/proc"))

        assert {1, os.getpid(), os.getppid()} <= targets.pids
        assert {1, os.getpgid(0)} <= targets.groups


class TestTheNetIsInstalledForTheWholeRun:
    def test_os_kill_and_killpg_are_the_nets_wrappers(self) -> None:
        net = installed_net()
        assert net is not None
        assert os.kill == net.kill
        assert os.killpg == net.killpg

    def test_the_installed_net_refuses_init_without_delivering(self) -> None:
        net = installed_net()
        if net is None or os.kill != net.kill:
            pytest.fail("signal safety net is not installed; refusing to call os.kill(1, ...)")
        if net.refusal_for_kill(1, signal.SIGKILL) is None:
            pytest.fail("installed net would not refuse pid 1; refusing to call os.kill(1, ...)")

        with pytest.raises(DangerousSignalError):
            os.kill(1, signal.SIGKILL)
        assert len(net.drain_violations()) == 1

    def test_the_installed_net_refuses_this_process_group_without_delivering(self) -> None:
        net = installed_net()
        own_group = os.getpgid(0)
        if net is None or os.killpg != net.killpg:
            pytest.fail("signal safety net is not installed; refusing to call os.killpg")
        if net.refusal_for_killpg(own_group, signal.SIGKILL) is None:
            pytest.fail("installed net would not refuse our own group; refusing to call it")

        with pytest.raises(DangerousSignalError):
            os.killpg(own_group, signal.SIGKILL)
        assert len(net.drain_violations()) == 1

    def test_a_child_this_test_started_in_its_own_session_is_killed_normally(self) -> None:
        child = subprocess.Popen(  # nosec B603 - fixed argv, trusted binary
            [sys.executable, "-c", "import time; time.sleep(600)"],
            start_new_session=True,
        )
        try:
            assert os.getpgid(child.pid) == child.pid
            os.killpg(child.pid, signal.SIGKILL)
            assert child.wait(timeout=Timeout.PROCESS_SAMPLE) == -signal.SIGKILL
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=Timeout.PROCESS_SAMPLE)
