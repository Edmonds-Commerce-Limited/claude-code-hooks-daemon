"""The hostname a ``persistent_crons`` job's ``hosts:`` is matched against.

Plan 00470 Task 6.1 (owner ruling; issues #60 and #62). A job is global, or
carries ``hosts:`` and is declared only where the EFFECTIVE hostname matches one
of its entries. One resolver and one matcher live here so every consumer of the
declared jobs (the SessionStart assertor, the Stop enforcers, ``cron-pause``,
the tick suppression) agrees on both.

Effective hostname, first non-empty of:

1. ``HOOKS_DAEMON_HOSTNAME`` -- a session takes a role (``cchd-sdlc-runner``)
   without a real hostname entering the tracked, public config;
2. ``CCY_HOST_HOSTNAME`` -- ccy sets it to the host machine's name, since a
   container's own hostname is a random id;
3. ``socket.gethostname()``.

**Whose environment?** The session's. The daemon is a long-lived process whose
environment is whatever started it, so it does not see what the user exported
in the session. The session's value therefore reaches it on the payload, under
:attr:`HookInputField.SESSION_HOSTNAME`: stamped by the ``init.sh`` transport,
or -- on the byte-pump relay, which never rewrites the payload -- by the daemon
reading the environment of the process on the other end of the socket
(:func:`hostname_override_of_process`). :func:`effective_hostname` prefers that
stamp and falls back to this process's own environment, which is the right
answer for the CLI (it runs inside the session) and when no override was set.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import socket
from collections.abc import Mapping, Sequence
from typing import Any, Final

from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.utils.host_identity import ENV_CCY_HOST_HOSTNAME

logger = logging.getLogger(__name__)

#: The session-role override; outranks :data:`ENV_CCY_HOST_HOSTNAME`.
ENV_HOSTNAME_OVERRIDE: Final = "HOOKS_DAEMON_HOSTNAME"

#: Override variables in precedence order.
HOSTNAME_OVERRIDE_ENV_VARS: Final[tuple[str, ...]] = (
    ENV_HOSTNAME_OVERRIDE,
    ENV_CCY_HOST_HOSTNAME,
)


def hostname_override(environ: Mapping[str, str]) -> str | None:
    """The first non-empty override in ``environ``, or None when none is set."""
    for name in HOSTNAME_OVERRIDE_ENV_VARS:
        value = environ.get(name, "").strip()
        if value:
            return value
    return None


def resolve_hostname_from_environ(environ: Mapping[str, str]) -> str:
    """The effective hostname for an environment: its override, else the system's."""
    return hostname_override(environ) or socket.gethostname()


def effective_hostname(hook_input: Mapping[str, Any] | None = None) -> str:
    """The hostname to match ``hosts:`` against.

    Args:
        hook_input: The hook payload, when there is one. Its stamped session
            hostname wins over this process's environment.

    Returns:
        The session's hostname override when the payload carries one, else the
        effective hostname of this process's own environment.
    """
    if hook_input is not None:
        stamped = hook_input.get(HookInputField.SESSION_HOSTNAME)
        if isinstance(stamped, str) and stamped.strip():
            return stamped.strip()
    return resolve_hostname_from_environ(os.environ)


def hostname_matches(hosts: Sequence[str], hostname: str) -> bool:
    """Whether ``hostname`` matches any entry of ``hosts`` (exact, or an fnmatch glob).

    Case-sensitive (``fnmatchcase``): hostnames are compared as written, on
    every platform.
    """
    return any(fnmatch.fnmatchcase(hostname, pattern) for pattern in hosts)


def hostname_override_of_process(pid: int) -> str | None:
    """The hostname override exported in another process's environment.

    Reads ``/proc/<pid>/environ``, which a process of the same user may read.
    That is the environment the process was EXECUTED with -- for a hook, the
    session's. Linux only: anywhere else, or for a process that is gone, in
    another PID namespace or not readable, the answer is None and the caller
    falls back to its own resolution.

    Args:
        pid: The process id. Non-positive ids (an unknown peer) yield None.

    Returns:
        The override, or None when unknown or when the process set neither
        variable.
    """
    if pid <= 0:
        return None
    try:
        with open(f"/proc/{pid}/environ", "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        logger.debug("cron_hosts: cannot read the environment of pid %s: %s", pid, exc)
        return None
    environ: dict[str, str] = {}
    for entry in raw.split(b"\0"):
        name, separator, value = entry.partition(b"=")
        if separator:
            environ[name.decode("utf-8", "replace")] = value.decode("utf-8", "replace")
    return hostname_override(environ)
