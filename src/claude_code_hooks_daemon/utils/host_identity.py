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

1. :data:`HOST_HOSTNAME_ENV_VARS` — the explicit hand-off, ``CCY_HOST_HOSTNAME``
   first and ``HOOKS_DAEMON_HOST_HOSTNAME`` second. Authoritative.
2. :func:`socket.gethostname`, but ONLY where it means something: on a host,
   or inside LXC. Authoritative.
3. A self-alias in ``/etc/hosts``. **Inferred** — see below.
4. Nothing. Rendered as nothing, never as a placeholder.

There is deliberately NO config-file override. A hostname is per-machine, and
``.claude/hooks-daemon.yaml`` is tracked in git and routinely public — an
option inviting a machine name into it is an invitation to publish one, and the
resulting leak is discoverable only by searching history that is never
rewritten. The environment carries per-machine values; the config does not.

Rung 3 needs its caveat stated where the code is, because it looks more
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
import re
import socket
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from claude_code_hooks_daemon.utils.container_detection import detect_container_runtime

logger = logging.getLogger(__name__)

#: The ccy supervisor's variable. ccy starts the container, so it is the thing
#: actually positioned to know the host's name — checked FIRST because in a ccy
#: session it is the real answer, and anything else is a stand-in for it.
ENV_CCY_HOST_HOSTNAME = "CCY_HOST_HOSTNAME"

#: The daemon's own variable, for setups with no ccy: a run script, a compose
#: file, a hand-rolled `podman run`. Same authority, second only because a ccy
#: session should not depend on the operator also setting this one.
ENV_HOST_HOSTNAME = "HOOKS_DAEMON_HOST_HOSTNAME"

#: Checked in order, first non-blank wins. Both are authoritative: each is an
#: explicit hand-off from outside the namespace, which is the only way the host
#: name can cross into a container at all.
HOST_HOSTNAME_ENV_VARS: tuple[str, ...] = (ENV_CCY_HOST_HOSTNAME, ENV_HOST_HOSTNAME)

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

#: Characters a host name may contain. RFC 1123 allows letters, digits and
#: hyphens per label, dots between labels; underscores appear in practice.
#:
#: This is an ALLOWLIST, and that direction is the whole point. The resolved
#: name is written STRAIGHT INTO A TERMINAL once per second, so a value
#: carrying an ANSI escape is not a cosmetic problem: `\033[` sequences can
#: reposition the cursor and repaint the line, and OSC sequences (`\033]`) can
#: set the window title or, in some terminals, reach the clipboard. A blocklist
#: of "dangerous" characters would have to anticipate every such sequence; an
#: allowlist of the nine characters a hostname actually uses cannot be
#: outflanked by one nobody thought of.
#:
#: The value is not hypothetically attacker-controlled either. It arrives from
#: an environment variable set outside this process, or from `/etc/hosts` —
#: which, inside a container, is a file the container runtime wrote and a
#: compromised image or a hostile `--add-host` could shape.
_DISALLOWED_HOST_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]")

#: Longer than any real machine name, short enough that it cannot flood the
#: status line. A DNS label maxes at 63 octets and a full name at 253; a value
#: past this is not a hostname, so it is refused rather than truncated — a
#: truncated unknown is still an unknown, displayed with more confidence.
_MAX_HOST_NAME_CHARS = 64


class HostNameSource(Enum):
    """Which rung of the ladder produced a name."""

    ENVIRONMENT = "environment"
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
            if alias.startswith(_LOCALHOST_ALIAS_PREFIX):
                continue
            # Sanitised HERE rather than only at the call site: this file is
            # written by the container runtime and shaped by whoever built the
            # image, so it is the least trustworthy rung of the ladder. A
            # rejected alias falls through to the next candidate rather than
            # abandoning the line, so one hostile entry cannot mask a real one.
            cleaned = _clean_host_name(alias)
            if cleaned is not None:
                return cleaned
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


def _clean_host_name(value: str | None) -> str | None:
    """Return ``value`` as a safe host name, or None if it is not one.

    Applied to EVERY rung of the ladder, not only the environment variables.
    ``/etc/hosts`` inside a container is written by the runtime and shaped by
    whoever built the image; even ``gethostname()`` is only as trustworthy as
    whatever set it. Sanitising centrally means a new rung cannot be added
    without inheriting the check.

    Three refusals, each failing CLOSED — no segment rather than a bad one:

    - blank or absent. An exporter whose own lookup failed sets the variable to
      an empty string, and treating that as an answer would both render a blank
      name and stop every lower rung from being tried.
    - anything outside :data:`_DISALLOWED_HOST_NAME_CHARS`' allowlist, which is
      what keeps terminal escape sequences out of a string printed to a
      terminal once a second.
    - longer than :data:`_MAX_HOST_NAME_CHARS`.

    Refusing rather than stripping is deliberate. A name with the escape
    sequence filtered out is no longer the machine's name, and displaying the
    remains as though it were would be a quieter version of the same lie the
    tilde marker exists to prevent.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if len(stripped) > _MAX_HOST_NAME_CHARS:
        logger.debug(
            "Refusing host name: %d characters exceeds the %d-character limit",
            len(stripped),
            _MAX_HOST_NAME_CHARS,
        )
        return None
    if _DISALLOWED_HOST_NAME_CHARS.search(stripped):
        # The rejected value is deliberately NOT logged: it is the thing that
        # might carry an escape sequence, and a log is read in a terminal too.
        logger.debug("Refusing host name: contains characters outside the allowlist")
        return None
    return stripped


def resolve_host_name(*, hosts_path: Path | None = None) -> HostName | None:
    """Resolve the host's name, or None when no rung of the ladder answers.

    Args:
        hosts_path: Override for the hosts file location (tests).

    Returns:
        A :class:`HostName` carrying the name and its provenance, or None.
    """
    for env_var in HOST_HOSTNAME_ENV_VARS:
        from_env = _clean_host_name(os.environ.get(env_var))
        if from_env is not None:
            return HostName(name=from_env, source=HostNameSource.ENVIRONMENT)

    runtime = detect_container_runtime()
    if runtime in _HOSTNAME_MEANINGFUL_RUNTIMES:
        local = _clean_host_name(socket.gethostname())
        if local is not None:
            return HostName(name=local, source=HostNameSource.LOCAL)
        # Falls through rather than returning. This rung's condition is about
        # the RUNTIME -- whether gethostname means anything here -- not about
        # the value it produced, so a refused value is a rung that did not hit,
        # and "first hit wins" hands the question to the next one. Rung 3 is
        # already ranked below every route that cannot be wrong and labels
        # itself a hint, which is exactly the standing it deserves here.

    inferred = host_name_from_hosts_file(_read_hosts_file(_etc_hosts_path(hosts_path)))
    if inferred is None:
        return None
    return HostName(name=inferred, source=HostNameSource.ETC_HOSTS_HINT)
