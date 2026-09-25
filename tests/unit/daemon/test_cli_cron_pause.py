"""Tests for the ``cron-pause`` / ``cron-resume`` CLI commands (ledger 00422 N4).

The only way to set a session-scoped cron pause. Each names ONE declared job and
the pause carries a reason, so the enforcer's output can say who paused what and
why. A job the project never declared is refused: a pause for a typo would sit
there doing nothing while the real job kept being demanded.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.utils.cron_pause import (
    CRON_PAUSES_FILENAME,
    PAUSE_TTL_SECONDS,
    read_pauses,
)

_SESSION = "cli-cron-session"
_CONFIG = """version: "2.0"
persistent_crons:
  enabled: true
  jobs:
    - id: issue-sdlc
      schedule: "23 * * * *"
      prompt: "Invoke the issue-sdlc skill."
    - id: dormant
      schedule: "41 * * * *"
      prompt: "q"
      enabled: false
"""


@pytest.fixture(autouse=True)
def _reset_project_context() -> Iterator[None]:
    from claude_code_hooks_daemon.core.project_context import ProjectContext

    yield
    ProjectContext.reset()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", _SESSION)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "hooks-daemon.yaml").write_text(_CONFIG, encoding="utf-8")
    with patch(
        "claude_code_hooks_daemon.core.project_context.ProjectContext.daemon_untracked_dir",
        return_value=tmp_path / "untracked",
    ):
        yield tmp_path


def _pause_args(project_root: Path, job: str, reason: str | None) -> argparse.Namespace:
    return argparse.Namespace(project_root=project_root, job=job, reason=reason)


def _resume_args(project_root: Path, job: str) -> argparse.Namespace:
    return argparse.Namespace(project_root=project_root, job=job)


def _pauses(project_root: Path) -> list[object]:
    return list(read_pauses(project_root / "untracked" / CRON_PAUSES_FILENAME))


class TestPause:
    def test_pauses_a_declared_job_for_this_session(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.cmd_cron_pause(_pause_args(project, "issue-sdlc", "owner said stop")) == 0

        [pause] = read_pauses(project / "untracked" / CRON_PAUSES_FILENAME)
        assert pause.job_id == "issue-sdlc"
        assert pause.session_id == _SESSION
        assert pause.reason == "owner said stop"
        out = capsys.readouterr().out
        assert "issue-sdlc" in out
        assert "Expires:" in out

    def test_the_pause_expires_within_a_day(self, project: Path) -> None:
        assert cli.cmd_cron_pause(_pause_args(project, "issue-sdlc", "r")) == 0

        [pause] = read_pauses(project / "untracked" / CRON_PAUSES_FILENAME)
        assert pause.expires_at - pause.recorded_at == PAUSE_TTL_SECONDS

    def test_an_unknown_job_is_refused_and_the_declared_ids_are_listed(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.cmd_cron_pause(_pause_args(project, "isue-sdlc", "typo")) == 1

        err = capsys.readouterr().err
        assert "isue-sdlc" in err
        assert "issue-sdlc" in err
        assert _pauses(project) == []

    def test_a_disabled_job_is_refused(self, project: Path) -> None:
        """Nothing enforces a disabled job, so there is nothing to pause."""
        assert cli.cmd_cron_pause(_pause_args(project, "dormant", "r")) == 1
        assert _pauses(project) == []

    @pytest.mark.parametrize("reason", [None, "", "   "])
    def test_a_reason_is_required(self, project: Path, reason: str | None) -> None:
        assert cli.cmd_cron_pause(_pause_args(project, "issue-sdlc", reason)) == 1
        assert _pauses(project) == []

    def test_a_multi_line_reason_is_kept_on_one_line(self, project: Path) -> None:
        assert cli.cmd_cron_pause(_pause_args(project, "issue-sdlc", "first\n\nsecond")) == 0

        [pause] = read_pauses(project / "untracked" / CRON_PAUSES_FILENAME)
        assert pause.reason == "first second"

    def test_refuses_without_a_session_id(
        self,
        project: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

        assert cli.cmd_cron_pause(_pause_args(project, "issue-sdlc", "r")) == 1

        assert "CLAUDE_CODE_SESSION_ID" in capsys.readouterr().err
        assert _pauses(project) == []

    def test_an_unwritable_untracked_dir_is_reported_as_a_failure(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (project / "untracked").write_text("not a directory", encoding="utf-8")

        assert cli.cmd_cron_pause(_pause_args(project, "issue-sdlc", "r")) == 1

        assert "not recorded" in capsys.readouterr().err


class TestResume:
    def test_resume_removes_the_pause(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cli.cmd_cron_pause(_pause_args(project, "issue-sdlc", "r"))

        assert cli.cmd_cron_resume(_resume_args(project, "issue-sdlc")) == 0

        assert _pauses(project) == []
        assert "CronCreate" in capsys.readouterr().out

    def test_resuming_a_job_that_is_not_paused_is_not_an_error(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.cmd_cron_resume(_resume_args(project, "issue-sdlc")) == 0

        assert "not paused" in capsys.readouterr().out

    def test_an_unknown_job_is_refused(self, project: Path) -> None:
        assert cli.cmd_cron_resume(_resume_args(project, "nope")) == 1

    def test_refuses_without_a_session_id(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

        assert cli.cmd_cron_resume(_resume_args(project, "issue-sdlc")) == 1


class TestTheParserSpellsIt:
    def test_cron_pause_takes_a_job_and_a_reason(self) -> None:
        seen: list[argparse.Namespace] = []

        def capture(args: argparse.Namespace) -> int:
            seen.append(args)
            return 0

        argv = ["claude-hooks-daemon", "cron-pause", "issue-sdlc", "--reason", "owner said stop"]
        with patch("sys.argv", argv), patch.object(cli, "cmd_cron_pause", capture):
            cli.main()

        assert len(seen) == 1
        assert seen[0].job == "issue-sdlc"
        assert seen[0].reason == "owner said stop"

    def test_cron_resume_takes_a_job(self) -> None:
        seen: list[argparse.Namespace] = []

        def capture(args: argparse.Namespace) -> int:
            seen.append(args)
            return 0

        argv = ["claude-hooks-daemon", "cron-resume", "issue-sdlc"]
        with patch("sys.argv", argv), patch.object(cli, "cmd_cron_resume", capture):
            cli.main()

        assert len(seen) == 1
        assert seen[0].job == "issue-sdlc"
