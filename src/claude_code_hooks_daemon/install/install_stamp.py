"""The version stamp an install leaves in its venv (Plan 00291).

A release install stamps ``vX.Y.Z``. A guarded branch install (the
first-party-only mechanism described in the plan's design note) stamps
``vX.Y.Z+<ref>.<shortsha>``: the version the branch is heading towards, the
tracked ref with ``/`` replaced by ``-``, and the installed commit.

This module is the single reader of that stamp. ``status``, the
``version_check`` session-start handler and the UNRELEASED-manifest loaders
all ask it, so they can never disagree about whether the running install is
a release.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

#: Written by ``scripts/install/venv.sh::stamp_venv_version`` into the venv root.
STAMP_FILENAME: Final[str] = ".daemon-version"

_STAMP_RE: Final[re.Pattern[str]] = re.compile(
    r"^v(?P<version>\d+\.\d+\.\d+)(?:\+(?P<ref>[0-9A-Za-z._-]+?)\.(?P<sha>[0-9a-f]{7,40}))?$"
)


@dataclass(frozen=True)
class InstallStamp:
    """A parsed ``.daemon-version`` stamp."""

    raw: str
    version: str
    ref: str | None
    sha: str | None

    @property
    def is_branch_install(self) -> bool:
        """True when the stamp records a tracked ref rather than a release."""
        return self.ref is not None


def parse_install_stamp(text: str) -> InstallStamp:
    """Parse a stamp string.

    Raises:
        ValueError: when the text is neither ``vX.Y.Z`` nor
            ``vX.Y.Z+<ref>.<shortsha>``.
    """
    raw = text.strip()
    match = _STAMP_RE.match(raw)
    if match is None:
        raise ValueError(f"not an install stamp: {raw!r}")
    return InstallStamp(
        raw=raw,
        version=match.group("version"),
        ref=match.group("ref"),
        sha=match.group("sha"),
    )


def read_install_stamp(venv_root: Path | None = None) -> InstallStamp | None:
    """Read the stamp of a venv, defaulting to the running interpreter's own.

    Returns ``None`` when there is no stamp or it is unparseable: both mean
    "nothing is known about this install", which every caller treats as a
    release install rather than as an error.
    """
    root = Path(sys.prefix) if venv_root is None else venv_root
    stamp_path = root / STAMP_FILENAME
    try:
        text = stamp_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return parse_install_stamp(text)
    except ValueError:
        return None


def is_branch_install(venv_root: Path | None = None) -> bool:
    """True when the venv (default: the running one) is a branch install."""
    stamp = read_install_stamp(venv_root)
    return stamp is not None and stamp.is_branch_install
