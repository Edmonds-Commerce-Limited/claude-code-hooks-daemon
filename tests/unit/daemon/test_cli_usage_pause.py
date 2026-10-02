"""Tests for ``hooks-daemon usage-pause clear|status`` (Plan 00479 review C2b).

The owner's escape from a usage pause: a held prompt can never lift it by itself
when the ceiling is still reached, so a human runs ``! bin/hooks-daemon usage-pause
clear`` (a ``!`` command is a shell run, not a prompt, so no gate sees it).
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.utils.usage_pause import (
    WINDOW_FIVE_HOUR,
    UsagePause,
    read_usage_pause,
    write_usage_pause,
)

_SESSION = "cli-usage-session"


@pytest.fixture(autouse=True)
def _reset_project_context() -> Iterator[None]:
    from claude_code_hooks_daemon.core.project_context import ProjectContext

    yield
    ProjectContext.reset()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", _SESSION)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "hooks-daemon.yaml").write_text('version: "2.0"\n', encoding="utf-8")
    with patch(
        "claude_code_hooks_daemon.core.project_context.ProjectContext.daemon_untracked_dir",
        return_value=tmp_path / "untracked",
    ):
        yield tmp_path


def _args(project_root: Path, action: str, session: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(project_root=project_root, action=action, session=session)


def _record(project_root: Path, session: str = _SESSION) -> None:
    now = time.time()
    write_usage_pause(
        project_root / "untracked",
        UsagePause(
            session_id=session,
            paused_at=now - 60,
            resume_at=now + 3600,
            window=WINDOW_FIVE_HOUR,
            used_percentage=91.0,
            ceiling=80.0,
            reason="five_hour window at 91% (ceiling 80%)",
        ),
    )


def _live(project_root: Path, session: str = _SESSION) -> bool:
    return read_usage_pause(project_root / "untracked", session, now=time.time()) is not None


class TestClear:
    def test_clears_this_sessions_pause(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _record(project)
        assert cli.cmd_usage_pause(_args(project, "clear")) == 0
        assert not _live(project)
        assert "cleared" in capsys.readouterr().out.lower()

    def test_an_explicit_session_wins_over_the_environment(self, project: Path) -> None:
        _record(project, "other")
        _record(project)
        assert cli.cmd_usage_pause(_args(project, "clear", "other")) == 0
        assert not _live(project, "other")
        assert _live(project)

    def test_nothing_to_clear_is_not_an_error(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.cmd_usage_pause(_args(project, "clear")) == 0
        assert "not paused" in capsys.readouterr().out.lower()

    def test_no_session_is_refused(
        self,
        project: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
        assert cli.cmd_usage_pause(_args(project, "clear")) == 1
        assert "--session" in capsys.readouterr().err

    def test_a_failed_removal_is_an_error_not_a_success(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _record(project)
        with patch.object(Path, "unlink", side_effect=PermissionError("denied")):
            assert cli.cmd_usage_pause(_args(project, "clear")) == 1
        assert "not cleared" in capsys.readouterr().err.lower()
        assert _live(project)


class TestStatus:
    def test_reports_a_live_pause(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _record(project)
        assert cli.cmd_usage_pause(_args(project, "status")) == 0
        out = capsys.readouterr().out
        assert "PAUSED" in out
        assert "five_hour" in out

    def test_reports_no_pause(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.cmd_usage_pause(_args(project, "status")) == 0
        assert "not paused" in capsys.readouterr().out.lower()


class TestTheParserSpellsIt:
    @pytest.mark.parametrize("action", ["clear", "status"])
    def test_usage_pause_takes_an_action_and_an_optional_session(self, action: str) -> None:
        seen: list[argparse.Namespace] = []

        def capture(args: argparse.Namespace) -> int:
            seen.append(args)
            return 0

        argv = ["claude-hooks-daemon", "usage-pause", action, "--session", "abc"]
        with patch("sys.argv", argv), patch.object(cli, "cmd_usage_pause", capture):
            cli.main()

        assert seen[0].action == action
        assert seen[0].session == "abc"
