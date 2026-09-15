"""Resolve the hostname of the machine a session is REALLY running on.

Plan 00411. A container has its own UTS namespace, so ``hostname``,
``uname -n``, ``/etc/hostname`` and ``$HOSTNAME`` all agree on the container ID
— a value that answers "which container?" when the user asked "which machine?".

Probing a rootless podman container (Debian 12 guest, Fedora 44 host)
established that the host's name is not readable from inside one at all. There
is no ``/run/host``, no container socket mounted, ``/run/.containerenv`` is
zero bytes, and reverse DNS on the gateway returns nothing. That is a result,
not an unfinished search — so the only authoritative route is an explicit
hand-off from outside the namespace, and this module is built around consuming
one.

Resolution is a ladder, first hit wins:

1. :data:`ENV_HOST_HOSTNAME` — the explicit hand-off. Authoritative.
2. A configured override. Authoritative.
3. :func:`socket.gethostname`, but ONLY where it means something: on a host,
   or inside LXC. Authoritative.
4. A self-alias in ``/etc/hosts``. **Inferred** — see below.
5. Nothing. Rendered as nothing, never as a placeholder.

Rung 4 needs its caveat stated where the code is, because it looks more
reliable than it is. Podman really does inherit the host's ``/etc/hosts``, so a
host name genuinely can appear inside a container. But whether that file names
the host is a property of the HOST DISTRIBUTION: Debian and Ubuntu write
``127.0.1.1 <hostname>`` at install time, while Fedora leaves the file generic
because ``systemd-hostnamed`` owns the hostname. The same read therefore
succeeds on one host and finds nothing on the next, and nothing inside the
container can tell which case it is in. Hence: a hint, marked as one, ranked
below every route that cannot be wrong.
"""

from __future__ import annotations

import logging
import os
import socket
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from claude_code_hooks_daemon.utils.container_detection import detect_container_runtime

logger = logging.getLogger(__name__)

#: Environment variable carrying the host's name across the namespace boundary.
#: A wrapper that starts the container (the ccy supervisor, a run script) is the
#: only thing positioned to know this, so it is the only thing that can set it.
ENV_HOST_HOSTNAME = "HOOKS_DAEMON_HOST_HOSTNAME"

#: Overridable for tests; the real file otherwise.
ENV_ETC_HOSTS_PATH = "HOOKS_DAEMON_ETC_HOSTS_PATH"
_DEFAULT_ETC_HOSTS_PATH = "/etc/hosts"

#: Container runtimes whose own hostname ANSWERS "which machine am I on?".
#: An LXC guest is normally a long-lived, deliberately named machine, so its
#: hostname is what the user wanted. Podman/Docker containers are ephemeral and
#: named by ID, so theirs is not. ``None`` (no container) is host-level.
_HOSTNAME_MEANINGFUL_RUNTIMES: frozenset[str | None] = frozenset({None, "lxc"})

#: Only ``127.x`` lines describe the machine itself. A LAN entry names some
#: OTHER host, and a container inherits a pile of them from the host's file.
_IPV4_LOOPBACK_PREFIX = "127."

#: ``localhost``, ``localhost.localdomain``, ``localhost4``… are the generic
#: aliases every distribution ships. None of them is a machine name.
_LOCALHOST_ALIAS_PREFIX = "localhost"

_COMMENT_MARKER = "#"


class HostNameSource(Enum):
    """Which rung of the ladder produced a name."""

    ENVIRONMENT = "environment"
    CONFIG = "config"
    LOCAL = "local"
    ETC_HOSTS_HINT = "etc-hosts-hint"


@dataclass(frozen=True)
class HostName:
    """A resolved host name together with how it was obtained.

    The source is carried rather than discarded because a caller rendering this
    must be able to distinguish a value that was READ from one that was
    INFERRED. A status-line segment answering "which machine am I on?" is worse
    than blank when it is confidently wrong.
    """

    name: str
    source: HostNameSource

    @property
    def inferred(self) -> bool:
        """True when the name is a hint rather than a reading."""
        return self.source is HostNameSource.ETC_HOSTS_HINT


def host_name_from_hosts_file(text: str) -> str | None:
    """Return the machine's own name from ``/etc/hosts`` content, if present.

    Looks for an IPv4 loopback line carrying a non-``localhost`` alias — the
    ``127.0.1.1 <hostname>`` entry Debian and Ubuntu write at install time.

    IPv6 ``::1`` is deliberately NOT considered: in practice it carries only
    generic aliases, and including it would return ``localhost.localdomain`` on
    some systems, which is worse than returning nothing.
    """
    for raw_line in text.splitlines():
        line = raw_line.split(_COMMENT_MARKER, 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) < 2 or not fields[0].startswith(_IPV4_LOOPBACK_PREFIX):
            continue
        for alias in fields[1:]:
            if not alias.startswith(_LOCALHOST_ALIAS_PREFIX):
                return alias
    return None


def _read_hosts_file(hosts_path: Path) -> str:
    """Return the file's content, or an empty string if it cannot be read.

    A missing or unreadable ``/etc/hosts`` is an ordinary condition for the
    bottom rung of a ladder, not a failure worth propagating — and it is
    INDISTINGUISHABLE in effect from a file that simply carries no self-alias,
    which is the overwhelmingly common case on a Fedora-family host. Both mean
    "no name available here", so both are represented the same way rather than
    given separate paths that reconverge one line later.

    The failure is still recorded at debug level, so a genuinely broken file is
    diagnosable rather than silent.
    """
    try:
        return hosts_path.read_text(errors="replace")
    except OSError as exc:
        logger.debug("Could not read %s for host-name inference: %s", hosts_path, exc)
        return ""


def _etc_hosts_path(override: Path | None) -> Path:
    """Resolve which hosts file to read, honouring the test override."""
    if override is not None:
        return override
    return Path(os.environ.get(ENV_ETC_HOSTS_PATH, _DEFAULT_ETC_HOSTS_PATH))


def _non_blank(value: object) -> str | None:
    """Return ``value`` stripped, or None when it is absent, blank or not text.

    An exporter whose own lookup failed sets the variable to an empty string.
    Treating that as an answer would render a blank name AND stop every lower
    rung from being tried, which is the worst of both.

    ``object`` rather than ``str | None`` because the configured override
    reaches a handler through the registry's untyped ``setattr`` from
    user-authored YAML. ``host_name: 12345`` is a plausible thing to write, and
    it would otherwise raise inside a status-line render — where the cost of an
    exception is a broken status line on every refresh.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def resolve_host_name(
    configured: str | None = None,
    *,
    hosts_path: Path | None = None,
) -> HostName | None:
    """Resolve the host's name, or None when no rung of the ladder answers.

    Args:
        configured: A per-machine override from project config, if any.
        hosts_path: Override for the hosts file location (tests).

    Returns:
        A :class:`HostName` carrying the name and its provenance, or None.
    """
    from_env = _non_blank(os.environ.get(ENV_HOST_HOSTNAME))
    if from_env is not None:
        return HostName(name=from_env, source=HostNameSource.ENVIRONMENT)

    from_config = _non_blank(configured)
    if from_config is not None:
        return HostName(name=from_config, source=HostNameSource.CONFIG)

    runtime = detect_container_runtime()
    if runtime in _HOSTNAME_MEANINGFUL_RUNTIMES:
        local = _non_blank(socket.gethostname())
        if local is not None:
            return HostName(name=local, source=HostNameSource.LOCAL)
        return None

    inferred = host_name_from_hosts_file(_read_hosts_file(_etc_hosts_path(hosts_path)))
    if inferred is None:
        return None
    return HostName(name=inferred, source=HostNameSource.ETC_HOSTS_HINT)
