"""Tests for AccountDisplayHandler.

Plan 00238 Task 3.1 put an mtime gate in front of the conf read, so these tests
drive a REAL file under a fake home rather than mocking ``Path.exists`` /
``Path.read_text``. That is deliberate: the old mocks pinned the call shape of
an implementation detail, so they broke the moment the read moved behind a
cache even though every rendered character stayed identical. Writing a real
file pins the OUTPUT, which is the thing the plan promised not to change.
"""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.handlers.status_line import AccountDisplayHandler, account_display


@pytest.fixture(autouse=True)
def _isolate_cache() -> Iterator[None]:
    """The cache is module-level, so it outlives a test and would otherwise
    leak the developer's real username into every later assertion."""
    account_display._username_reader.clear()
    yield
    account_display._username_reader.clear()


@pytest.fixture
def fake_home(tmp_path: Path) -> Iterator[Path]:
    """Point ``Path.home()`` at a tmp dir with a real ``.claude/`` in it."""
    (tmp_path / ".claude").mkdir()
    with patch("pathlib.Path.home", return_value=tmp_path):
        yield tmp_path


def _write_conf(home: Path, content: str) -> Path:
    conf = home / ".claude" / ".last-launch.conf"
    conf.write_text(content)
    return conf


class TestAccountDisplayHandler:
    """Tests for AccountDisplayHandler."""

    @pytest.fixture
    def handler(self) -> AccountDisplayHandler:
        """Create handler instance."""
        return AccountDisplayHandler()

    def test_handler_properties(self, handler: AccountDisplayHandler) -> None:
        """Test handler has correct properties."""
        assert handler.name == "status-account-display"
        assert handler.priority == 5
        assert handler.terminal is False
        assert "status" in handler.tags
        assert "display" in handler.tags

    def test_matches_always_returns_true(self, handler: AccountDisplayHandler) -> None:
        """Handler should always match for status events."""
        assert handler.matches({}) is True
        assert handler.matches({"session_id": "test"}) is True

    def test_handle_with_valid_conf_file(
        self, handler: AccountDisplayHandler, fake_home: Path
    ) -> None:
        """Test formatting with valid .last-launch.conf file."""
        _write_conf(
            fake_home,
            """
# Last launch configuration
LAST_TOKEN="acme_rohil"
LAST_TIME="2025-01-29T10:30:00Z"
""",
        )

        result = handler.handle({})

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert "acme_rohil" in result.context[0]
        assert result.context[0] == "👤 acme_rohil |"

    def test_handle_with_different_username(
        self, handler: AccountDisplayHandler, fake_home: Path
    ) -> None:
        """Test formatting with different username."""
        _write_conf(fake_home, 'LAST_TOKEN="john_doe"')

        result = handler.handle({})

        assert result.decision == "allow"
        assert result.context == ["👤 john_doe |"]

    def test_handle_with_missing_file(
        self, handler: AccountDisplayHandler, fake_home: Path
    ) -> None:
        """Test handling when .last-launch.conf doesn't exist."""
        result = handler.handle({})

        # Should return empty context (silent fail)
        assert result.decision == "allow"
        assert result.context == []

    def test_handle_with_invalid_format(
        self, handler: AccountDisplayHandler, fake_home: Path
    ) -> None:
        """Test handling when .last-launch.conf has invalid format."""
        _write_conf(fake_home, "SOME_OTHER_VAR=value\nINVALID_LINE")

        result = handler.handle({})

        # Should return empty context (silent fail)
        assert result.decision == "allow"
        assert result.context == []

    def test_handle_with_read_error(self, handler: AccountDisplayHandler, fake_home: Path) -> None:
        """Test handling when reading file raises exception."""
        _write_conf(fake_home, 'LAST_TOKEN="acme_rohil"')

        with patch("pathlib.Path.read_text", side_effect=PermissionError("Access denied")):
            result = handler.handle({})

        # Should return empty context (silent fail)
        assert result.decision == "allow"
        assert result.context == []

    def test_handle_with_empty_token(self, handler: AccountDisplayHandler, fake_home: Path) -> None:
        """Test handling when token value is empty."""
        _write_conf(fake_home, 'LAST_TOKEN=""')

        result = handler.handle({})

        # Empty token should still be shown
        assert result.decision == "allow"
        assert result.context == ["👤  |"]

    def test_conf_file_path_is_correct(
        self, handler: AccountDisplayHandler, fake_home: Path
    ) -> None:
        """The handler reads ``~/.claude/.last-launch.conf`` and nowhere else."""
        _write_conf(fake_home, 'LAST_TOKEN="from_the_right_path"')
        # A decoy at the home root: without it, dropping the `.claude` segment
        # would still read *a* file and this test would pass silently.
        (fake_home / ".last-launch.conf").write_text('LAST_TOKEN="from_the_wrong_path"')

        result = handler.handle({})

        assert result.context == ["👤 from_the_right_path |"]


class TestTheReadIsMtimeGated:
    """Plan 00238 Task 3.1 — the reason this handler changed at all.

    The status line re-renders ~3,100 times an hour for the life of the daemon
    and this file's contents effectively never change, so the read must happen
    once per change rather than once per render.
    """

    @pytest.fixture
    def handler(self) -> AccountDisplayHandler:
        return AccountDisplayHandler()

    def test_repeat_renders_do_not_reread_the_file(
        self, handler: AccountDisplayHandler, fake_home: Path
    ) -> None:
        conf = _write_conf(fake_home, 'LAST_TOKEN="acme_rohil"')
        real_read_text = Path.read_text
        reads: list[str] = []

        def counting_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
            reads.append(str(self))
            return real_read_text(self, *args, **kwargs)

        with patch("pathlib.Path.read_text", counting_read_text):
            for _ in range(5):
                handler.handle({})

        assert reads.count(str(conf)) == 1

    def test_a_changed_file_is_picked_up(
        self, handler: AccountDisplayHandler, fake_home: Path
    ) -> None:
        """Anti-vacuity companion: proves the cache invalidates, so the test
        above is measuring a cache and not a handler that stopped reading."""
        conf = _write_conf(fake_home, 'LAST_TOKEN="before"')
        assert handler.handle({}).context == ["👤 before |"]

        conf.write_text('LAST_TOKEN="after"')
        # Filesystem mtime granularity can be coarse enough that two writes in
        # the same test share a stamp; force a distinct one.
        stat = conf.stat()
        os.utime(conf, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

        assert handler.handle({}).context == ["👤 after |"]
