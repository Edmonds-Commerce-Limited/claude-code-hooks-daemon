"""Tests for the standalone claude-supervise.py `DecisionLog`."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()
DecisionLog = _mod.DecisionLog


class TestDecisionLogExplicitPath:
    """Tests using an explicit path (no environment-derived default)."""

    def test_write_appends_timestamped_line(self, tmp_path: Path) -> None:
        log_path = tmp_path / "decision.log"
        log = DecisionLog(log_path)

        log.write("supervisor active (dry-run)")

        contents = log_path.read_text(encoding="utf-8")
        assert "supervisor active (dry-run)" in contents
        assert "T" in contents.splitlines()[0]

    def test_write_appends_multiple_lines(self, tmp_path: Path) -> None:
        log_path = tmp_path / "decision.log"
        log = DecisionLog(log_path)

        log.write("first")
        log.write("second")

        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert lines[0].endswith("first")
        assert lines[1].endswith("second")

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        log_path = tmp_path / "nested" / "dir" / "decision.log"

        log = DecisionLog(log_path)
        log.write("hello")

        assert log_path.exists()

    def test_path_property_returns_configured_path(self, tmp_path: Path) -> None:
        log_path = tmp_path / "decision.log"
        log = DecisionLog(log_path)

        assert log.path == log_path

    def test_unwritable_path_raises(self, tmp_path: Path) -> None:
        """FAIL FAST: an unwritable path raises rather than being swallowed."""
        blocker = tmp_path / "not_a_dir"
        blocker.write_text("i am a file, not a directory")
        log_path = blocker / "sub" / "decision.log"

        with pytest.raises(OSError):
            DecisionLog(log_path)


class TestDecisionLogNoopDedup:
    """`write_noop` records NOOP-reason lines but suppresses a CONSECUTIVE repeat.

    Plan 00168 Phase 1: the supervisor must record WHY a tick did nothing (the
    gate that blocked) so a red-but-not-compacting session is diagnosable from
    ``decision.log`` alone -- but deduplicated on the message so an unchanged
    gate held for minutes never floods the log every ~1-2s tick.
    """

    def test_write_noop_records_the_reason(self, tmp_path: Path) -> None:
        log = DecisionLog(tmp_path / "decision.log")
        log.write_noop("noop: cooldown active [critical]")
        contents = (tmp_path / "decision.log").read_text(encoding="utf-8")
        assert "noop: cooldown active [critical]" in contents

    def test_consecutive_identical_noop_is_written_once(self, tmp_path: Path) -> None:
        log = DecisionLog(tmp_path / "decision.log")
        for _ in range(5):
            log.write_noop("noop: sidecar stale")
        lines = (tmp_path / "decision.log").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1

    def test_changed_noop_reason_is_written(self, tmp_path: Path) -> None:
        log = DecisionLog(tmp_path / "decision.log")
        log.write_noop("noop: not red (tier=green)")
        log.write_noop("noop: not red (tier=green)")
        log.write_noop("noop: cooldown active [red]")
        lines = (tmp_path / "decision.log").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert lines[0].endswith("noop: not red (tier=green)")
        assert lines[1].endswith("noop: cooldown active [red]")

    def test_write_resets_dedup_so_following_identical_noop_relogs(self, tmp_path: Path) -> None:
        # A real action (injection / deferral / reap) between two identical NOOPs
        # must NOT be swallowed: the second NOOP re-logs so the log stays a
        # faithful transition record.
        log = DecisionLog(tmp_path / "decision.log")
        log.write_noop("noop: injection cap reached [critical]")
        log.write("would-compact: ...; injected '/compact'")
        log.write_noop("noop: injection cap reached [critical]")
        lines = (tmp_path / "decision.log").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3


class TestDecisionLogSizeCap:
    """Plan 00181: ``decision.log`` is front-capped so it cannot grow forever.

    The supervisor is a standalone process that cannot import the daemon's
    ``cap_log_file`` utility, so an inline size-cap mirrors it: when the file
    exceeds ``_DECISION_LOG_MAX_BYTES`` after a write, the oldest bytes are
    dropped so only the newest ``_DECISION_LOG_RETAIN_BYTES`` (whole lines)
    survive. A red-but-idle session ticks every ~1-2s forever, so an unbounded
    log is a genuine disk time-bomb.
    """

    def test_write_caps_file_when_over_budget(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_mod, "_DECISION_LOG_MAX_BYTES", 400)
        monkeypatch.setattr(_mod, "_DECISION_LOG_RETAIN_BYTES", 200)
        log_path = tmp_path / "decision.log"
        log = DecisionLog(log_path)

        for i in range(200):
            log.write(f"line {i:04d} " + "x" * 20)

        assert log_path.stat().st_size <= 400
        # The newest line always survives (front-truncation keeps the tail).
        assert "line 0199" in log_path.read_text(encoding="utf-8")

    def test_write_noop_caps_file_when_over_budget(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_mod, "_DECISION_LOG_MAX_BYTES", 400)
        monkeypatch.setattr(_mod, "_DECISION_LOG_RETAIN_BYTES", 200)
        log_path = tmp_path / "decision.log"
        log = DecisionLog(log_path)

        # Each reason is unique so the dedup never suppresses (worst case growth).
        for i in range(200):
            log.write_noop(f"noop reason {i:04d} " + "y" * 20)

        assert log_path.stat().st_size <= 400

    def test_cap_drops_partial_leading_line_keeps_whole_lines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_mod, "_DECISION_LOG_MAX_BYTES", 300)
        monkeypatch.setattr(_mod, "_DECISION_LOG_RETAIN_BYTES", 150)
        log_path = tmp_path / "decision.log"
        log = DecisionLog(log_path)

        for i in range(100):
            log.write(f"msg{i:04d}")

        lines = log_path.read_text(encoding="utf-8").splitlines()
        # Front-truncation drops everything up to and including the first newline,
        # so the first retained line must begin with a whole ISO timestamp (year),
        # never a fragment of the previous line.
        assert lines
        assert lines[0].startswith("20")

    def test_under_budget_file_is_untouched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_mod, "_DECISION_LOG_MAX_BYTES", 10_000)
        monkeypatch.setattr(_mod, "_DECISION_LOG_RETAIN_BYTES", 5_000)
        log_path = tmp_path / "decision.log"
        log = DecisionLog(log_path)

        log.write("first")
        log.write("second")

        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert lines[0].endswith("first")
        assert lines[1].endswith("second")


class TestDecisionLogDefaultPath:
    """Tests using the default (environment-derived) path."""

    def test_default_path_uses_claude_project_dir_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

        log = DecisionLog()

        assert log.path == tmp_path / "untracked" / "supervise" / "decision.log"

    def test_default_path_falls_back_to_cwd_when_env_var_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        monkeypatch.chdir(tmp_path)

        log = DecisionLog()

        assert log.path == tmp_path / "untracked" / "supervise" / "decision.log"
