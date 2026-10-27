"""Which relay binary the host can execute.

Low-level on purpose: imports nothing from the package, so config models,
the installer and the handlers can all read the same answer. The relay is a
static musl ELF and ``relay/build.sh`` needs GNU userland tools, so only Linux
on x86_64 or aarch64 is supported; anywhere else the legacy transport is used.
"""

from __future__ import annotations

import platform
import sys
from typing import Final, Literal

#: Rust target triple per normalised machine name (Linux only).
_TARGET_BY_MACHINE: Final[dict[str, str]] = {
    "x86_64": "x86_64-unknown-linux-musl",
    "amd64": "x86_64-unknown-linux-musl",
    "aarch64": "aarch64-unknown-linux-musl",
    "arm64": "aarch64-unknown-linux-musl",
}

#: ELF ``e_machine`` value per Rust target triple.
_ELF_MACHINE_BY_TARGET: Final[dict[str, int]] = {
    "x86_64-unknown-linux-musl": 62,
    "aarch64-unknown-linux-musl": 183,
}


def host_relay_target() -> str | None:
    """The Rust target triple of the relay this host can run, or None when unsupported."""
    if not sys.platform.startswith("linux"):
        return None
    return _TARGET_BY_MACHINE.get(platform.machine().lower())


def host_elf_machine() -> int | None:
    """The ELF ``e_machine`` a relay binary must carry to run here, or None when unsupported."""
    target = host_relay_target()
    return None if target is None else _ELF_MACHINE_BY_TARGET[target]


def relay_supported_by_host() -> bool:
    """True when a relay binary exists for this host's OS and architecture."""
    return host_relay_target() is not None


def relay_fix_subcommand() -> Literal["on", "off"]:
    """The ``transport`` subcommand that fixes a relay problem on this host.

    ``on`` provisions the binary where one can run; on an unsupported host no
    binary can ever work, so the fix is ``off``.
    """
    return "on" if relay_supported_by_host() else "off"
