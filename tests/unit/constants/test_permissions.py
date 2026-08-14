"""Tests for :mod:`claude_code_hooks_daemon.constants.permissions` (Plan 00239).

The mask is asserted against the FILESYSTEM, not against its own literal. A test
that only reads ``FileMode.DAEMON_UMASK == 0o077`` back restates the source and
would keep passing if the value were changed to something equally wrong; creating
a real file and a real directory under the mask is what actually pins the
guarantee the daemon makes about everything it writes.
"""

import os
import stat
from pathlib import Path

from claude_code_hooks_daemon.constants.permissions import FileMode

# Every bit that must be denied to group and other: rwx for both.
_GROUP_AND_OTHER = stat.S_IRWXG | stat.S_IRWXO

# The daemon's one explicit-mode create (the start lock in ``daemon/server.py``).
# A mask that clipped this would break daemon startup rather than merely tighten
# permissions, so it is pinned here alongside the mask it has to survive.
_START_LOCK_MODE = 0o600


class TestDaemonUmask:
    """The daemon's file-creation mask."""

    def test_mask_denies_every_group_and_other_bit(self) -> None:
        """The mask must cover rwx for both group and other."""
        assert FileMode.DAEMON_UMASK & _GROUP_AND_OTHER == _GROUP_AND_OTHER

    def test_mask_leaves_owner_access_intact(self) -> None:
        """The daemon must still be able to read and write its own files."""
        assert FileMode.DAEMON_UMASK & stat.S_IRWXU == 0

    def test_created_file_is_owner_only(self, tmp_path: Path) -> None:
        """A file created under the mask exposes nothing to group or other."""
        previous = os.umask(FileMode.DAEMON_UMASK)
        try:
            target = tmp_path / "verdicts.jsonl"
            target.write_text("{}\n", encoding="utf-8")
            mode = stat.S_IMODE(target.stat().st_mode)
        finally:
            os.umask(previous)

        assert mode & _GROUP_AND_OTHER == 0, f"expected owner-only, got {mode:#o}"

    def test_created_directory_is_owner_only(self, tmp_path: Path) -> None:
        """A directory created under the mask is not group/other traversable."""
        previous = os.umask(FileMode.DAEMON_UMASK)
        try:
            target = tmp_path / "payload-capture"
            target.mkdir()
            mode = stat.S_IMODE(target.stat().st_mode)
        finally:
            os.umask(previous)

        assert mode & _GROUP_AND_OTHER == 0, f"expected owner-only, got {mode:#o}"

    def test_start_lock_mode_survives_the_mask(self) -> None:
        """The daemon's one explicit-mode create must be unaffected."""
        assert _START_LOCK_MODE & ~FileMode.DAEMON_UMASK == _START_LOCK_MODE
