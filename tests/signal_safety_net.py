"""Plan 00466 N59 — refuse any signal from the test run to init, itself or its callers.

Twice a unit test killed the whole container. Its ``MagicMock`` Popen had a pid
that coerces to 1 through ``__index__``, so ``os.killpg(os.getpgid(pid),
SIGKILL)`` became ``killpg(1, SIGKILL)`` and took out ``tini``, the container's
init, with every agent and session under it.

``tests/conftest.py`` installs :class:`SignalSafetyNet` over ``os.kill`` and
``os.killpg`` for the whole session. A nonzero signal whose target is pid 1,
group 1, this process, its group, any ancestor or a Claude Code process raises
:class:`DangerousSignalError` and is never delivered; everything else passes
through unchanged. Signal 0 is the existence probe, delivers nothing, and is
never refused.

The net deliberately shares no code with ``claude_code_hooks_daemon.utils.
safe_signal``, the production helper it backstops: a safety layer that reuses
the logic it guards fails in the same way at the same moment.

A refusal is also RECORDED, because code under test that wraps its kill in
``except Exception`` would otherwise swallow it; conftest fails any test that
leaves a recorded refusal behind.
"""

from __future__ import annotations

import operator
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, SupportsIndex

#: The process name Claude Code runs under, as ``comm`` or as ``argv[0]``.
CLAUDE_CODE_PROCESS_NAME: Final = "claude"

#: Init's pid, and the group it leads.
_INIT_PID: Final = 1

#: ``os.kill(0, sig)`` signals the caller's own group, ``os.kill(-1, sig)``
#: every process the caller may signal. Neither can name a process on purpose.
_GROUP_OR_BROADCAST_ALIASES: Final = frozenset({0, -1})

#: Guard against a malformed ``/proc`` making the ancestor walk loop.
_MAX_ANCESTOR_DEPTH: Final = 256

_REMEDY: Final = (
    "A test must never signal a pid it has not proven it started. A mocked "
    "Popen must set .pid to a nonexistent pid (e.g. 2**22 + 7) or the test "
    "must patch os.kill/os.killpg. See Plan 00466 N59."
)


class DangerousSignalError(RuntimeError):
    """A test tried to signal init, itself, its callers or Claude Code."""


@dataclass(frozen=True)
class ProtectedTargets:
    """Pids and process groups no signal from the test run may reach."""

    pids: frozenset[int]
    groups: frozenset[int]


def _read_stat(proc_root: Path, pid: int) -> tuple[int, int] | None:
    """``(ppid, pgrp)`` from ``/proc/<pid>/stat``, or None if it is gone."""
    try:
        text = (proc_root / str(pid) / "stat").read_text(encoding="utf-8")
    except OSError:
        return None
    # comm sits in parentheses and may itself contain spaces or ')'.
    fields = text[text.rfind(")") + 1 :].split()
    return int(fields[1]), int(fields[2])


def _is_claude_code(entry: Path) -> bool:
    """True when the process at ``entry`` runs as Claude Code."""
    try:
        comm = (entry / "comm").read_text(encoding="utf-8").strip()
        argv0 = (entry / "cmdline").read_bytes().split(b"\0", 1)[0].decode(errors="replace")
    except OSError:
        return False
    return CLAUDE_CODE_PROCESS_NAME in (comm, Path(argv0).name)


def protected_targets_from_proc(*, own_pid: int, proc_root: Path) -> ProtectedTargets:
    """This process, every ancestor up to init, every Claude Code process, and their groups.

    Args:
        own_pid: The pid whose ancestry is protected.
        proc_root: The procfs mount to read (``/proc``; a directory in tests).
    """
    pids: set[int] = {_INIT_PID, own_pid}
    groups: set[int] = {_INIT_PID}

    current = own_pid
    for _ in range(_MAX_ANCESTOR_DEPTH):
        stat = _read_stat(proc_root, current)
        if stat is None:
            break
        ppid, pgrp = stat
        pids.add(current)
        groups.add(pgrp)
        if ppid <= _INIT_PID or ppid in pids:
            break
        current = ppid

    for entry in proc_root.iterdir():
        if not entry.name.isdigit() or not _is_claude_code(entry):
            continue
        pid = int(entry.name)
        pids.add(pid)
        stat = _read_stat(proc_root, pid)
        if stat is not None:
            groups.add(stat[1])

    return ProtectedTargets(pids=frozenset(pids), groups=frozenset(groups))


def _live_protected_targets() -> ProtectedTargets:
    """The protected set for this process, read fresh at each signal."""
    from_proc = protected_targets_from_proc(own_pid=os.getpid(), proc_root=Path("/proc"))
    return ProtectedTargets(
        pids=from_proc.pids,
        groups=from_proc.groups | {os.getpgid(0)},
    )


def _as_int(value: object) -> int | None:
    """The integer the kernel would receive, as ``os.kill`` coerces it; None if none.

    A ``MagicMock`` and a ``bool`` both have ``__index__``, and both coerce to 1.
    """
    if not isinstance(value, SupportsIndex):
        return None
    return operator.index(value)


class SignalSafetyNet:
    """``os.kill``/``os.killpg`` replacements that refuse a protected target."""

    # The delegates are typed Any-in because they receive exactly what the
    # caller passed: the real call must see, and reject, a non-integer itself.
    def __init__(
        self,
        *,
        real_kill: Callable[[Any, Any], None],
        real_killpg: Callable[[Any, Any], None],
        protected_targets: Callable[[], ProtectedTargets],
    ) -> None:
        self._real_kill = real_kill
        self._real_killpg = real_killpg
        self._protected_targets = protected_targets
        self._violations: list[str] = []
        self._lock = threading.Lock()

    def refusal_for_kill(self, pid: object, sig: object) -> str | None:
        """Why ``os.kill(pid, sig)`` must not run, or None when it may."""
        target = _as_int(pid)
        if target is None or _as_int(sig) == 0:
            return None
        if target in _GROUP_OR_BROADCAST_ALIASES or target == _INIT_PID:
            return f"os.kill to pid {target} reaches init, our own group or every process"
        if target < 0:
            return self._group_refusal(-target, call="os.kill")
        if target in self._protected_targets().pids:
            return f"os.kill to pid {target} reaches this test process, an ancestor or Claude Code"
        return None

    def refusal_for_killpg(self, pgid: object, sig: object) -> str | None:
        """Why ``os.killpg(pgid, sig)`` must not run, or None when it may."""
        target = _as_int(pgid)
        if target is None or _as_int(sig) == 0:
            return None
        return self._group_refusal(target, call="os.killpg")

    def _group_refusal(self, group: int, *, call: str) -> str | None:
        if group <= _INIT_PID:
            return f"{call} to group {group} reaches init's group or our own"
        targets = self._protected_targets()
        # A group led by a protected process is that process's group.
        if group in targets.groups or group in targets.pids:
            return (
                f"{call} to group {group} reaches the group of this test process, "
                f"an ancestor or Claude Code"
            )
        return None

    def _refuse(self, reason: str, sig: object) -> DangerousSignalError:
        message = f"REFUSED signal {sig!r}: {reason}. {_REMEDY}"
        with self._lock:
            self._violations.append(message)
        return DangerousSignalError(message)

    def kill(self, pid: object, sig: object) -> None:
        """``os.kill`` that raises instead of signalling a protected target."""
        reason = self.refusal_for_kill(pid, sig)
        if reason is not None:
            raise self._refuse(reason, sig)
        self._real_kill(pid, sig)

    def killpg(self, pgid: object, sig: object) -> None:
        """``os.killpg`` that raises instead of signalling a protected group."""
        reason = self.refusal_for_killpg(pgid, sig)
        if reason is not None:
            raise self._refuse(reason, sig)
        self._real_killpg(pgid, sig)

    def drain_violations(self) -> list[str]:
        """Every refusal since the last drain, oldest first."""
        with self._lock:
            drained, self._violations = self._violations, []
        return drained


_installed: SignalSafetyNet | None = None


def installed_net() -> SignalSafetyNet | None:
    """The net currently wrapping ``os.kill``/``os.killpg``, if any."""
    return _installed


def install() -> SignalSafetyNet:
    """Wrap ``os.kill`` and ``os.killpg`` for the rest of the process."""
    global _installed
    if _installed is not None:
        raise RuntimeError("signal safety net is already installed")
    net = SignalSafetyNet(
        real_kill=os.kill,
        real_killpg=os.killpg,
        protected_targets=_live_protected_targets,
    )
    os.kill = net.kill
    os.killpg = net.killpg
    _installed = net
    return net


def uninstall(net: SignalSafetyNet) -> None:
    """Restore the real ``os.kill`` and ``os.killpg``."""
    global _installed
    if _installed is not net:
        raise RuntimeError("uninstall called with a net that is not the installed one")
    os.kill = net._real_kill
    os.killpg = net._real_killpg
    _installed = None
