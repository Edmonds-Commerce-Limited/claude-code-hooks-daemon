"""Tests for ``hooks-daemon usage-pause clear|status`` (Plan 00479 review C2b).

The owner's escape from a usage pause: a held prompt can never lift it by itself
when the ceiling is still reached, so a human runs ``bin/hooks-daemon usage-pause
clear`` in a terminal. Whether a ``!``-prefixed command passes through the hooks is
unverified, so the docs name the terminal.
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
    usage_override_active,
    write_usage_pause,
)
from claude_code_hooks_daemon.utils.usage_pause_gate import RESUME_MARGIN_SECONDS

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


class TestClearRecordsAnOverride:
    """Round 2 N4: clearing alone is undone by the next prompt while usage is still over.

    So ``clear`` also records an override valid until the latest reset among the windows
    over the ceiling (capped at 8 days); while it is valid no gate starts a pause.
    """

    def _override_active(self, project_root: Path, at: float) -> bool:
        return usage_override_active(project_root / "untracked", _SESSION, now=at)

    def test_the_override_runs_to_the_pause_records_reset(self, project: Path) -> None:
        _record(project)
        before = time.time()
        assert cli.cmd_usage_pause(_args(project, "clear")) == 0
        reset = before + 3600 - RESUME_MARGIN_SECONDS  # the record's resume_at less the margin
        assert self._override_active(project, reset - 5)
        assert not self._override_active(project, reset + 5)

    def test_it_is_extended_to_a_later_window_that_is_over_the_ceiling(self, project: Path) -> None:
        from claude_code_hooks_daemon.utils.usage_pause_gate import UsageBreach

        _record(project)
        later = time.time() + 3 * 86400
        breach = UsageBreach("seven_day", 90.0, 80.0, int(later))
        with patch(
            "claude_code_hooks_daemon.utils.usage_pause_gate.current_breaches",
            return_value=[breach],
        ):
            assert cli.cmd_usage_pause(_args(project, "clear")) == 0
        assert self._override_active(project, later - 5)
        assert not self._override_active(project, later + 5)

    def test_the_next_prompt_is_not_re_paused(self, project: Path) -> None:
        from claude_code_hooks_daemon.utils.usage_pause_gate import (
            PauseEnvironment,
            UsageBreach,
            start_pause,
        )

        _record(project)
        assert cli.cmd_usage_pause(_args(project, "clear")) == 0
        breach = UsageBreach("five_hour", 95.0, 80.0, int(time.time() + 3600))
        assert start_pause(_SESSION, [breach], PauseEnvironment()) is None
        assert not _live(project)

    def test_the_message_states_exactly_what_it_did(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _record(project)
        assert cli.cmd_usage_pause(_args(project, "clear")) == 0
        out = capsys.readouterr().out
        assert "no pause will be started" in out
        assert "UTC" in out
        assert "works again" not in out  # the old, untrue promise

    def test_no_pause_and_no_breach_records_no_override(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.cmd_usage_pause(_args(project, "clear")) == 0
        assert not self._override_active(project, time.time())

    def test_a_failed_override_write_leaves_the_pause_in_place(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Clearing without the override would just be undone, so neither happens."""
        _record(project)
        with patch(
            "claude_code_hooks_daemon.utils.usage_pause.write_usage_override",
            side_effect=OSError("full"),
        ):
            assert cli.cmd_usage_pause(_args(project, "clear")) == 1
        assert _live(project)
        assert "override" in capsys.readouterr().err.lower()


class TestStatus:
    def test_reports_an_override(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _record(project)
        cli.cmd_usage_pause(_args(project, "clear"))
        capsys.readouterr()
        assert cli.cmd_usage_pause(_args(project, "status")) == 0
        out = capsys.readouterr().out
        assert "override" in out.lower()

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
