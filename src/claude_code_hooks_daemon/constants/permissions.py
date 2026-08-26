"""File-permission constants — single source of truth for daemon file modes.

Plan 00239. The daemon daemonises with the textbook Stevens sequence
(``chdir("/")`` / ``setsid()`` / ``umask(...)``). The published recipe clears the
mask entirely, which is correct ONLY for a daemon that passes an explicit mode to
every single create. This one does not: of 98 runtime create sites, exactly one
(the start lock) passes a mode, so a cleared mask meant every log, sidecar, PID
file and capture directory landed group- and world-writable.

The mask is therefore the choke point that fixes every current and future create
at once, rather than a per-site audit obligation that has already been missed 97
times out of 98.
"""

from typing import Final


class FileMode:
    """Named file modes and masks used by the daemon.

    Values are octal permission bits, matching :func:`os.chmod` and
    :func:`os.umask`.
    """

    # Deny ALL group and other access on anything the daemon creates without an
    # explicit mode. Files land 0600, directories 0700.
    #
    # Deliberately 0o077 and NOT the group-preserving 0o007. The 0o007 variant was
    # proposed on the grounds that group access is load-bearing here — the socket
    # is chmod 0o660 after bind, and a host and a container are documented as
    # sharing one daemon. Both premises fail on inspection: the comment above that
    # chmod describes 0o640 ("group read, world none"), so the mode is a copied
    # idiom rather than a design, and nothing in the codebase ever sets a group
    # (no chown/chgrp, no SO_PEERCRED peer check) — the "group" is only ever the
    # daemon's own primary group. Cross-UID sharing is already impossible whatever
    # the mask, because the start lock is opened 0600 and left on disk for reuse,
    # so a second UID's start gets EACCES.
    #
    # 0o007 is therefore never safer than 0o077, and on a host with a shared
    # primary group (staff, users, a service account) it leaves the verdict log
    # and payload-capture/ group-READABLE and group-WRITABLE. 0o077 is
    # deployment-invariant.
    DAEMON_UMASK: Final[int] = 0o077

    # Explicit modes for the artefacts whose CONTENTS are known-sensitive: the
    # payload capture directory (raw hook payloads), the verdict log and the
    # stop-event log. Passed at the create site so the posture survives someone
    # later "restoring" the textbook umask(0) above — the mask and these modes are
    # deliberately redundant, and neither is load-bearing alone.
    #
    # Narrow on purpose. The other 90-odd create sites are covered by the mask
    # only: pinning a mode at every one of them is the per-site audit obligation
    # that produced this defect in the first place.
    PRIVATE_FILE: Final[int] = 0o600
    PRIVATE_DIR: Final[int] = 0o700

    # Same bit pattern as ``DAEMON_UMASK`` (any group/other permission bit),
    # purpose-named for the OTHER use of this mask: testing whether an
    # EXISTING file (one the daemon did not itself create, e.g. a protected
    # secret file being audited for hygiene) is group- or world-readable.
    # ``DAEMON_UMASK`` is a mask applied at process startup to shape what
    # `os.umask()` clears on every future create; a permission AUDIT of an
    # already-existing file reads more naturally under its own name than
    # under the umask one, even though the bits are identical by design
    # (Plan 00272 code review).
    GROUP_OTHER_MASK: Final[int] = 0o077
