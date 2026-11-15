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
import logging
import os
import stat
from collections.abc import Callable
from pathlib import Path, PurePath
from typing import Final, TypeVar

from claude_code_hooks_daemon.utils.cron_hosts import process_environ
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

T = TypeVar("T")

logger = logging.getLogger(__name__)

#: The one variable taken from a peer's environment.
ENV_SSH_AUTH_SOCK: Final = "SSH_AUTH_SOCK"

#: The pid of the hook process whose request is being served, or None.
_request_peer_pid: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "request_peer_pid", default=None
)


class AgentSocketRejected(ValueError):
    """A candidate ``SSH_AUTH_SOCK`` value that may not be used.

    Carries only a fixed ``reason``; the rejected value is never held, so the
    exception can be logged without writing the socket path down.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def validated_agent_socket(value: str, uid: int | None = None) -> str:
    """``value`` (stripped) when it is an absolute path to a socket owned by ``uid``.

    Args:
        value: A candidate ``SSH_AUTH_SOCK`` value.
        uid: The owner required; the daemon's own uid when omitted.

    Raises:
        AgentSocketRejected: The value is empty, not absolute, unreadable, not a
            socket, or not owned by ``uid``. The exception names the reason only.
    """
    candidate = value.strip()
    if not candidate:
        raise AgentSocketRejected("empty")
    if not PurePath(candidate).is_absolute():
        raise AgentSocketRejected("not absolute")
    try:
        info = Path(candidate).stat()
    except (OSError, ValueError):
        # The OSError text names the path, so the cause is deliberately not chained.
        raise AgentSocketRejected("unreadable") from None
    if not stat.S_ISSOCK(info.st_mode):
        raise AgentSocketRejected("not a socket")
    owner = os.getuid() if uid is None else uid
    if info.st_uid != owner:
        raise AgentSocketRejected("not owned by the daemon user")
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
    :func:`validated_agent_socket`. None of those is an error. A rejected value
    is recorded through ``log_and_continue`` by reason only, never by value.
    """
    pid = _request_peer_pid.get()
    if pid is None:
        return None
    environ, _reason = process_environ(pid)
    if environ is None:
        return None
    value = (environ.get(ENV_SSH_AUTH_SOCK) or "").strip()
    if not value:
        return None
    accepted: str | None = None
    try:
        accepted = validated_agent_socket(value)
    except AgentSocketRejected as rejected:
        log_and_continue(
            logger,
            rejected,
            reason="the peer's SSH_AUTH_SOCK failed validation, so the daemon's own "
            "environment applies; the exception carries a fixed reason, never the value",
        )
    return accepted
