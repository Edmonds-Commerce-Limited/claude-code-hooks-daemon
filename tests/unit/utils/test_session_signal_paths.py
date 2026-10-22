"""Tests for the shared per-session signal-file naming (Plan 00501 Task 1.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils import usage_pause
from claude_code_hooks_daemon.utils.session_signal_paths import (
    SESSION_ID_FALLBACK,
    SIGNAL_SUBDIR,
    session_stem,
)


class TestSessionStem:
    """``session_stem`` keeps an untrusted session id inside its directory."""

    def test_safe_id_is_unchanged(self) -> None:
        assert session_stem("abc-123_X.y") == "abc-123_X.y"

    @pytest.mark.parametrize("raw", ["", "   "])
    def test_blank_id_falls_back(self, raw: str) -> None:
        assert session_stem(raw) == SESSION_ID_FALLBACK

    def test_separators_are_replaced(self) -> None:
        assert session_stem("../../etc/passwd") == ".._.._etc_passwd"

    def test_surrounding_whitespace_is_stripped(self) -> None:
        assert session_stem("  sid  ") == "sid"


class TestUsagePauseSharesTheHelper:
    """usage_pause names its files through the shared helper (one stem rule)."""

    def test_pause_path_uses_the_shared_dir_and_stem(self, tmp_path: Path) -> None:
        path = usage_pause.pause_path(tmp_path, "a/b")
        assert SIGNAL_SUBDIR == "context-sidecar"
        assert path.parent == tmp_path / SIGNAL_SUBDIR
        assert path.name == f"{session_stem('a/b')}{usage_pause.SIGNAL_SUFFIX}"
