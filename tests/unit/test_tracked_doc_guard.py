"""The tracked-doc guard must never be the thing that destroys work.

``tests/conftest.py`` protects ``CLAUDE.md`` and ``.claude/HOOKS-DAEMON.md``
from being rewritten by a test that points ``DaemonController`` at the real
repository. That protection is worth having. Its RESTORE, however, took its
baseline from a SESSION-scoped snapshot, so it reverted the file to whatever it
held when pytest started — not to what it held when the offending test began.

An edit made by a developer or agent while the suite runs therefore landed
inside some test's window, was attributed to that test, and was silently undone,
losing minutes of work with no trace beyond a failure pointing at an innocent
test. The fixture's own docstring conceded it could not tell the two apart.

Two properties close that, and both are pinned here:

- the baseline is captured per TEST, shrinking the destructive window from a
  whole session to one test;
- whatever is about to be overwritten is preserved first, so even inside that
  window nothing becomes unrecoverable.
"""

from __future__ import annotations

from pathlib import Path

import tests.conftest as conftest


class TestBaselineIsPerTest:
    """A session-scoped baseline is the defect; it must not come back."""

    def test_no_session_scoped_restore_baseline_exists(self) -> None:
        """The session snapshot reverted edits made since pytest STARTED.

        Restoring from it undoes any change since session start, which includes
        every edit a developer made while the suite ran.
        """
        assert not hasattr(conftest, "_tracked_doc_snapshot"), (
            "a session-scoped baseline reverts every edit made since pytest "
            "started, not just the one the failing test made"
        )

    def test_a_per_test_byte_baseline_helper_exists(self) -> None:
        """The guard captures its own baseline at test setup."""
        captured = conftest._tracked_file_bytes()

        assert isinstance(captured, dict)
        for name in conftest._TRACKED_FILES_NO_TEST_MAY_WRITE:
            if (conftest._REPO_ROOT / name).exists():
                assert name in captured, f"{name} must be captured to be restorable"
                assert isinstance(captured[name], bytes)


class TestRejectedWriteIsRecoverable:
    """Restoring must not be the only copy of what was there."""

    def test_content_is_preserved_before_it_is_overwritten(self, tmp_path: Path) -> None:
        """The about-to-be-discarded bytes are written somewhere recoverable."""
        victim = tmp_path / "CLAUDE.md"
        victim.write_text("the edit that would otherwise be lost\n", encoding="utf-8")

        preserved = conftest._preserve_rejected_write("CLAUDE.md", victim, tmp_path)

        assert preserved is not None, "a rejected write must be preserved, not just discarded"
        assert preserved.exists()
        assert preserved.read_text(encoding="utf-8") == "the edit that would otherwise be lost\n"

    def test_a_missing_file_preserves_nothing_and_does_not_raise(self, tmp_path: Path) -> None:
        """A file that vanished has nothing to preserve; that is not an error.

        The guard runs in a fixture teardown, so raising here would replace a
        useful assertion failure with an unrelated one.
        """
        assert conftest._preserve_rejected_write("gone.md", tmp_path / "gone.md", tmp_path) is None
