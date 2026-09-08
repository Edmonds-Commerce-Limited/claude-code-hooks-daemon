"""A Write target the daemon cannot stat must still be guarded.

``matches()`` reads::

    # Creating a new file destroys nothing.
    if not Path(path).is_file():
        return False

That is correct for a path that genuinely does not exist. It is a **bypass** for
a path the daemon merely cannot LOOK at: ``is_file()`` raises ``PermissionError``
when any ancestor directory lacks ``+x`` for the daemon's user, because EACCES
is not among the stat failures ``pathlib`` swallows.

Both outcomes of that raise are wrong, and which one you get is decided by a
setting the daemon does not control:

- ``strict_mode: false`` — the client default — ``chain.py`` catches it and the
  guard silently stops applying. An unread file behind an unreadable directory
  is clobbered with no warning: the exact loss this handler exists to prevent.
- ``strict_mode: true`` — this repository — a spurious DENY attributed to a
  crash rather than to a policy.

The handler already contains the right answer, one method away. ``_count_lines``
degrades to reporting ``0`` on an unreadable file, and says why: *"A file that
cannot be read is still worth blocking -- the agent knows even less about it --
so this degrades the message rather than the decision."* Line 155 exempts the
file before that reasoning is ever reached.

So this site is the one where the naive fallback inverts the guard. Mirroring
pathlib (``False`` = "not a file") reads as principled and produces
``not False`` → "treat as new" → ``matches()`` returns ``False`` → no guard.
The safe answer here is ``True``.

Every test FORCES the error. Mode bits do nothing when the suite runs as root,
which is exactly how the originating instance reached CI unnoticed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.write_clobber_guard import (
    WriteClobberGuardHandler,
)

_SESSION = "session-eacces"
_UNREADABLE = "/root/.claude/projects/-workspace/memory/MEMORY.md"


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> Any:
    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture
def stat_always_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    """``is_file()`` raises EACCES, as an untraversable parent really does."""

    def _denied(self: Path) -> bool:
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "is_file", _denied)


def _write(path: str, session: str = _SESSION) -> dict[str, Any]:
    return {
        "tool_name": "Write",
        "session_id": session,
        "tool_input": {"file_path": path, "content": "replacement"},
    }


def _read(path: str, session: str = _SESSION) -> dict[str, Any]:
    return {
        "tool_name": "Read",
        "session_id": session,
        "tool_input": {"file_path": path},
    }


class TestTheFixtureIsNotVacuous:
    def test_is_file_really_raises(self, stat_always_denied: None) -> None:
        """Without this, a fixture that failed to patch would make every
        assertion below pass against the unfixed handler."""
        with pytest.raises(PermissionError):
            Path("/anything").is_file()

    def test_an_ordinary_unread_file_is_blocked_without_the_patch(self, tmp_path: Path) -> None:
        """Pins the behaviour the EACCES case has to match. If this ever stops
        denying, the tests below would be asserting against a guard that does
        not guard anything."""
        target = tmp_path / "tracked.md"
        target.write_text("content worth keeping\n", encoding="utf-8")

        handler = WriteClobberGuardHandler()

        assert handler.handle(_write(str(target))).decision == Decision.DENY


class TestAnUnstattableTargetIsStillGuarded:
    def test_matches_does_not_raise(self, stat_always_denied: None) -> None:
        """``chain.py`` catching this is not a fix. It converts the raise into a
        silent exemption or a spurious crash-DENY depending on ``strict_mode``,
        and neither is a decision this handler made."""
        handler = WriteClobberGuardHandler()

        assert handler.matches(_write(_UNREADABLE)) is True

    def test_the_write_is_denied(self, stat_always_denied: None) -> None:
        """The whole point. A file the daemon cannot even stat is one the agent
        knows *less* about than an ordinary unread file, so the guard must fire
        rather than stand down."""
        handler = WriteClobberGuardHandler()

        result = handler.handle(_write(_UNREADABLE))

        assert result.decision == Decision.DENY, (
            "an unstattable Write target was treated as a new file, so the "
            "clobber guard silently exempted exactly the case where the agent "
            "knows least about what it is destroying"
        )

    def test_handle_survives_counting_lines_it_cannot_read(self, stat_always_denied: None) -> None:
        """Deciding to fire sends control into ``_count_lines``, which opens the
        file. Assuming a path exists is only safe if everything downstream of
        that assumption also tolerates being wrong."""
        handler = WriteClobberGuardHandler()

        assert handler.handle(_write(_UNREADABLE)).reason is not None


class TestTheExemptionsStillWork:
    """The fallback must not deny things the guard was never meant to catch."""

    def test_a_file_read_this_session_is_still_allowed(self, stat_always_denied: None) -> None:
        """Reading records the path, and that record is what the guard consults.
        An unreadable path the session has somehow read is not a clobber risk,
        and ``_is_known`` never touches the filesystem."""
        handler = WriteClobberGuardHandler()
        handler.handle(_read(_UNREADABLE))

        assert handler.handle(_write(_UNREADABLE)).decision == Decision.ALLOW

    def test_an_edit_is_still_ignored(self, stat_always_denied: None) -> None:
        """Edit replaces known text, not the file, so it is out of scope
        regardless of whether the path can be stat'ed."""
        handler = WriteClobberGuardHandler()
        hook_input: dict[str, Any] = {
            "tool_name": "Edit",
            "session_id": _SESSION,
            "tool_input": {"file_path": _UNREADABLE, "old_string": "a", "new_string": "b"},
        }

        assert handler.matches(hook_input) is False

    def test_a_genuinely_missing_file_is_still_allowed(self, tmp_path: Path) -> None:
        """ENOENT is not EACCES. pathlib already answers ``False`` for a missing
        path, so creating a new file must stay unblocked -- widening the
        fallback to cover that would deny every first write in the repo."""
        handler = WriteClobberGuardHandler()

        assert handler.handle(_write(str(tmp_path / "brand-new.md"))).decision == Decision.ALLOW
