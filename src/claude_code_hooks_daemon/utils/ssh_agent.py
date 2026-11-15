"""The session's SSH agent socket, for the daemon's remote-touching git calls.

A daemon started by an upgrade has no ``SSH_AUTH_SOCK``, so its ``git`` calls to an
ssh remote cannot authenticate, while the hook process on the other end of the
connection carries the session's. The daemon reads that variable, and ONLY that
variable, from the connecting process's ``/proc/<pid>/environ`` (the same
mechanism the hostname override uses).

The request is bound by the connecting process's pid, not by its value: the
environment is read lazily, when a remote git call is made, so a request that
never touches a remote costs nothing and the value is never stored on a payload
(where a payload capture could write it down).

Trust model: the value is used only when it is an absolute path to a socket owned
by the daemon's own uid; anything else is ignored and the daemon's own
environment applies. It is never logged. ``GIT_SSH_COMMAND``, ``GIT_SSH``,
``GIT_ASKPASS``, ``SSH_ASKPASS`` and ``SSH_AGENT_PID`` are never taken from a peer:
the first four run an arbitrary command in the daemon's context.
"""

from __future__ import annotations

import contextvars
import os
import stat
from collections.abc import Callable
from pathlib import Path, PurePath
from typing import Final, TypeVar

from claude_code_hooks_daemon.utils.cron_hosts import process_environ

T = TypeVar("T")

#: The one variable taken from a peer's environment.
ENV_SSH_AUTH_SOCK: Final = "SSH_AUTH_SOCK"

#: The pid of the hook process whose request is being served, or None.
_request_peer_pid: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "request_peer_pid", default=None
)


def validated_agent_socket(value: str | None, uid: int | None = None) -> str | None:
    """``value`` when it is an absolute path to a socket owned by ``uid``, else None.

    Args:
        value: A candidate ``SSH_AUTH_SOCK`` value.
        uid: The owner required; the daemon's own uid when omitted.
    """
    candidate = (value or "").strip()
    if not candidate or not PurePath(candidate).is_absolute():
        return None
    try:
        info = Path(candidate).stat()
    except (OSError, ValueError):
        return None
    owner = os.getuid() if uid is None else uid
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != owner:
        return None
    return candidate


def call_bound_to_peer(pid: int | None, fn: Callable[[], T]) -> T:
    """Run ``fn`` with the request bound to the hook process ``pid``.

    A pid that is unknown or not positive binds nothing. The binding is reset
    when ``fn`` returns, so a reused executor thread never carries it over.
    """
    token = _request_peer_pid.set(pid if pid is not None and pid > 0 else None)
    try:
        return fn()
    finally:
        _request_peer_pid.reset(token)


def forwarded_agent_socket() -> str | None:
    """The bound hook process's validated ``SSH_AUTH_SOCK``, or None.

    None means the daemon's own environment applies: no request is bound, the
    peer's environment is unreadable, it names no agent, or the value fails
    :func:`validated_agent_socket`. None of those is an error, and none logs.
    """
    pid = _request_peer_pid.get()
    if pid is None:
        return None
    environ, _reason = process_environ(pid)
    if environ is None:
        return None
    return validated_agent_socket(environ.get(ENV_SSH_AUTH_SOCK))
