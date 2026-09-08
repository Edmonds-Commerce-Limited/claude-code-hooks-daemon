"""A destination the daemon cannot stat must not crash the accessor.

``_written_paths`` asks ``Path(destination).is_dir()`` to decide whether a copy
verb expands to ``dest/<basename>`` or writes ``dest`` itself. ``pathlib``
swallows ``OSError`` for the *expected* stat failures — ENOENT, ENOTDIR, ELOOP,
EBADF — and returns ``False``. ``EACCES`` is not in that set, so
``PermissionError`` propagates out of ``is_dir()``, out of
``get_bash_write_targets``, and out of every handler that calls it.

The paths this accessor receives come from a command a user typed, so the
daemon has no say in whether it can stat them. A directory anywhere in the
parent chain without ``+x`` for the daemon's user is enough.

**Found by CI, and only by CI.** The memory-policy tests in
``test_markdown_organization.py`` name ``/root/.claude/projects/-workspace/
memory/MEMORY.md``. In a container running as root that path is statable and
the tests pass; on a GitHub runner ``/root`` is not traversable by the
``runner`` user, so 39 assertions in that file died with ``PermissionError``.
The bug is in the accessor, not the fixture — a handler must not raise because
a path is unreadable.

These tests force the error rather than relying on filesystem permissions,
because a permission-based fixture reproduces nothing when the suite runs as
root — which is exactly how this reached CI in the first place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import pytest

from claude_code_hooks_daemon.core.utils import get_bash_write_targets

_UNREADABLE: Final[str] = "/root/.claude/projects/-workspace/memory/MEMORY.md"
_UNREADABLE_DIR: Final[str] = "/root/.claude/projects/-workspace/memory"


@pytest.fixture
def stat_always_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every ``is_dir()`` raise EACCES, as an untraversable parent does."""

    def _denied(self: Path) -> bool:
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "is_dir", _denied)


def _bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class TestTheFixtureIsNotVacuous:
    def test_is_dir_really_raises(self, stat_always_denied: None) -> None:
        """Without this, a fixture that silently failed to patch would make
        every assertion below pass against the unfixed accessor."""
        with pytest.raises(PermissionError):
            Path("/anything").is_dir()


class TestAnUnstattableDestinationDoesNotRaise:
    @pytest.mark.parametrize(
        "command",
        [
            f"echo x > {_UNREADABLE}",
            f"echo x >> {_UNREADABLE}",
            f"echo x >| {_UNREADABLE}",
            f"echo x | tee {_UNREADABLE}",
            f"cp /tmp/a.md {_UNREADABLE}",
            f"mv /tmp/a.md {_UNREADABLE}",
            f"install /tmp/a.md {_UNREADABLE}",
            f"dd if=/tmp/a of={_UNREADABLE}",
        ],
        ids=[
            "redirect",
            "append",
            "clobber",
            "tee",
            "cp",
            "mv",
            "install",
            "dd",
        ],
    )
    def test_every_write_shape_survives(self, command: str, stat_always_denied: None) -> None:
        """The accessor is called by handlers on every Bash event, so raising
        here takes the hook down rather than returning a decision."""
        assert get_bash_write_targets(_bash(command)) is not None


class TestTheTargetIsStillNamed:
    def test_the_destination_is_reported(self, stat_always_denied: None) -> None:
        """Not crashing is not enough — a guard that names nothing is a bypass.

        Treating an unstattable path as "not a directory" is what ``pathlib``
        already does for every other stat failure, and it keeps the common
        shape (a redirect to a FILE) covered. Returning nothing instead would
        turn an unreadable parent directory into a blanket exemption from every
        path-keyed guard, which is the direction a guard must never fail in.
        """
        targets = get_bash_write_targets(_bash(f"echo x > {_UNREADABLE}"))

        assert _UNREADABLE in targets, (
            "an unstattable destination was dropped, so every path-keyed guard "
            f"silently stops covering it: {targets!r}"
        )

    def test_a_copy_into_an_unstattable_directory_is_not_fabricated(
        self, stat_always_denied: None
    ) -> None:
        """The other half of the same decision, and it must NOT overclaim.

        ``cp a.md dir/`` expands to ``dir/a.md`` only when ``dir`` is known to
        be a directory. It is not known here, and the accessor's contract is
        explicit that a WRONG path is worse than no path — it would attribute a
        write to a file that was never touched. The trailing slash declares a
        directory, so the shell would refuse a non-directory outright.
        """
        targets = get_bash_write_targets(_bash(f"cp /tmp/a.md {_UNREADABLE_DIR}/"))

        assert f"{_UNREADABLE_DIR}/a.md" not in targets, (
            "the accessor invented a path inside a directory it could not "
            f"stat, attributing a write to a file it cannot know about: {targets!r}"
        )
