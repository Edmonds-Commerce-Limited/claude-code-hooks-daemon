"""Tests for :mod:`claude_code_hooks_daemon.utils.private_io` (Plan 00239).

These helpers are defence in depth, so every test here sets a DELIBERATELY
PERMISSIVE process umask first. Under the daemon's own ``0o077`` mask the modes
would come out right even with no explicit mode passed at all, which would make
the tests pass for the wrong reason and prove nothing about the guarantee these
helpers exist to make: that the sensitive artefacts stay owner-only even if the
umask fix is later undone.
"""

import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.private_io import make_private_dir, open_private_append

_GROUP_AND_OTHER = stat.S_IRWXG | stat.S_IRWXO

# The mask the daemon shipped with, and the exact condition these helpers must
# survive: a cleared mask, where an unguarded create lands 0666 / 0777.
_CLEARED_UMASK = 0


@pytest.fixture
def cleared_umask() -> Iterator[None]:
    """Run the test body with a cleared umask, restoring it afterwards."""
    previous = os.umask(_CLEARED_UMASK)
    try:
        yield
    finally:
        os.umask(previous)


class TestOpenPrivateAppend:
    """``open_private_append`` — owner-only append handles."""

    @pytest.mark.usefixtures("cleared_umask")
    def test_created_file_is_owner_only_despite_cleared_umask(self, tmp_path: Path) -> None:
        """A new file must not inherit 0666 from a permissive mask."""
        target = tmp_path / "verdicts.jsonl"

        with open_private_append(target) as handle:
            handle.write("{}\n")

        assert stat.S_IMODE(target.stat().st_mode) & _GROUP_AND_OTHER == 0

    @pytest.mark.usefixtures("cleared_umask")
    def test_appends_rather_than_truncates(self, tmp_path: Path) -> None:
        """Reopening must preserve existing content — these are append logs."""
        target = tmp_path / "verdicts.jsonl"

        with open_private_append(target) as handle:
            handle.write("first\n")
        with open_private_append(target) as handle:
            handle.write("second\n")

        assert target.read_text(encoding="utf-8") == "first\nsecond\n"

    @pytest.mark.usefixtures("cleared_umask")
    def test_writes_utf8(self, tmp_path: Path) -> None:
        """Non-ASCII content round-trips, matching the callers' prior encoding."""
        target = tmp_path / "verdicts.jsonl"

        with open_private_append(target) as handle:
            handle.write("café — ✅\n")

        assert target.read_text(encoding="utf-8") == "café — ✅\n"

    def test_existing_file_mode_is_left_alone(self, tmp_path: Path) -> None:
        """An existing file is NOT re-chmodded — appending must not surprise.

        Remediating files already on disk is deliberately out of scope for the
        write path (a daemon silently chmodding a user's tree is its own risk);
        it is handled by the documented upgrade remediation instead.
        """
        target = tmp_path / "verdicts.jsonl"
        target.write_text("existing\n", encoding="utf-8")
        target.chmod(0o666)

        with open_private_append(target) as handle:
            handle.write("more\n")

        assert stat.S_IMODE(target.stat().st_mode) == 0o666


class TestMakePrivateDir:
    """``make_private_dir`` — owner-only directories."""

    @pytest.mark.usefixtures("cleared_umask")
    def test_created_directory_is_owner_only_despite_cleared_umask(self, tmp_path: Path) -> None:
        """A new directory must not inherit 0777 from a permissive mask."""
        target = tmp_path / "payload-capture"

        make_private_dir(target)

        assert stat.S_IMODE(target.stat().st_mode) & _GROUP_AND_OTHER == 0

    @pytest.mark.usefixtures("cleared_umask")
    def test_parent_directories_are_also_private(self, tmp_path: Path) -> None:
        """``Path.mkdir(parents=True, mode=...)`` applies the mode to the LEAF only.

        The intermediate directories are created with the default 0o777 masked by
        the umask, so under a cleared mask they would land world-writable — which
        would leave a private leaf inside a world-writable parent. This is the
        specific trap that makes a bare ``mkdir(mode=...)`` insufficient.
        """
        target = tmp_path / "logs" / "hooks"

        make_private_dir(target)

        assert stat.S_IMODE((tmp_path / "logs").stat().st_mode) & _GROUP_AND_OTHER == 0
        assert stat.S_IMODE(target.stat().st_mode) & _GROUP_AND_OTHER == 0

    def test_existing_directory_is_idempotent_and_unchanged(self, tmp_path: Path) -> None:
        """An existing directory must not raise, and keeps its mode.

        Same rationale as the file case: retro-fixing what is already on disk is
        the upgrade remediation's job, not the write path's.
        """
        target = tmp_path / "payload-capture"
        target.mkdir()
        target.chmod(0o777)

        make_private_dir(target)

        assert stat.S_IMODE(target.stat().st_mode) == 0o777
