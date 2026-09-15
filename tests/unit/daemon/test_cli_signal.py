"""Tests for the ``signal`` CLI command (Plan 00417).

Host-side tool for warning every session of this project that the machine is
about to reboot/shut down, mirroring ``inject-goal``/``--emit-model-switch``.
Unlike those, the channel is reachable from OUTSIDE the container, so the
payload is a closed ``kind`` plus, for the two kinds that need one, a bare
positive integer -- never free text. ``--all-sessions`` reaches every live
session of THIS project (every ``<session>.json`` context sidecar) instead of
just ``$CLAUDE_CODE_SESSION_ID``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.utils.operator_signal import SIGNAL_SUBDIR, SIGNAL_SUFFIX

_SESSION = "cli-signal-session"


@pytest.fixture(autouse=True)
def _reset_project_context():
    from claude_code_hooks_daemon.core.project_context import ProjectContext

    yield
    ProjectContext.reset()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", _SESSION)
    monkeypatch.setattr(
        "claude_code_hooks_daemon.core.project_context.ProjectContext.daemon_untracked_dir",
        classmethod(lambda cls: tmp_path / "untracked"),
    )
    return tmp_path


def _args(
    project_root: Path,
    *,
    kind: str = "reboot-warning",
    minutes: int | None = 10,
    all_sessions: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        kind=kind, minutes=minutes, all_sessions=all_sessions, project_root=project_root
    )


def _signal_path(project_root: Path, session_id: str = _SESSION) -> Path:
    return project_root / "untracked" / SIGNAL_SUBDIR / f"{session_id}{SIGNAL_SUFFIX}"


class TestSingleSessionMode:
    def test_writes_a_signal_for_the_current_session(self, project: Path, capsys) -> None:
        rc = cli.cmd_signal(_args(project))

        assert rc == 0
        data = json.loads(_signal_path(project).read_text(encoding="utf-8"))
        assert data["kind"] == "reboot-warning"
        assert data["minutes"] == 10
        assert data["session_id"] == _SESSION
        assert data["source"] == "cli"
        assert str(_signal_path(project)) in capsys.readouterr().out

    def test_refuses_without_a_session_id(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

        rc = cli.cmd_signal(_args(project))

        assert rc == 1
        assert "CLAUDE_CODE_SESSION_ID" in capsys.readouterr().err
        assert not _signal_path(project).exists()

    def test_reboot_cancelled_takes_no_minutes(self, project: Path) -> None:
        rc = cli.cmd_signal(_args(project, kind="reboot-cancelled", minutes=None))

        assert rc == 0
        data = json.loads(_signal_path(project).read_text(encoding="utf-8"))
        assert data["kind"] == "reboot-cancelled"
        assert "minutes" not in data


class TestValidationRefusals:
    def test_a_warning_kind_without_minutes_is_refused(self, project: Path, capsys) -> None:
        rc = cli.cmd_signal(_args(project, kind="reboot-warning", minutes=None))

        assert rc == 1
        assert "--minutes" in capsys.readouterr().err
        assert not _signal_path(project).exists()

    def test_cancelled_with_minutes_is_refused(self, project: Path, capsys) -> None:
        rc = cli.cmd_signal(_args(project, kind="reboot-cancelled", minutes=5))

        assert rc == 1
        assert "no --minutes" in capsys.readouterr().err
        assert not _signal_path(project).exists()

    def test_zero_minutes_is_refused(self, project: Path, capsys) -> None:
        rc = cli.cmd_signal(_args(project, kind="reboot-warning", minutes=0))

        assert rc == 1
        assert capsys.readouterr().err
        assert not _signal_path(project).exists()

    def test_negative_minutes_is_refused(self, project: Path, capsys) -> None:
        rc = cli.cmd_signal(_args(project, kind="shutdown-warning", minutes=-3))

        assert rc == 1
        assert not _signal_path(project).exists()


class TestAllSessions:
    def test_reaches_every_live_session_and_no_other(self, project: Path) -> None:
        sidecar_dir = project / "untracked" / SIGNAL_SUBDIR
        sidecar_dir.mkdir(parents=True)
        (sidecar_dir / "sess-a.json").write_text("{}", encoding="utf-8")
        (sidecar_dir / "sess-b.json").write_text("{}", encoding="utf-8")

        rc = cli.cmd_signal(_args(project, all_sessions=True))

        assert rc == 0
        assert json.loads(_signal_path(project, "sess-a").read_text(encoding="utf-8"))["kind"] == (
            "reboot-warning"
        )
        assert json.loads(_signal_path(project, "sess-b").read_text(encoding="utf-8"))["kind"] == (
            "reboot-warning"
        )
        # Not this project's own CLAUDE_CODE_SESSION_ID -- --all-sessions
        # replaces single-session targeting, it does not add to it.
        assert not _signal_path(project, _SESSION).exists()

    def test_no_live_session_is_refused(self, project: Path, capsys) -> None:
        rc = cli.cmd_signal(_args(project, all_sessions=True))

        assert rc == 1
        assert capsys.readouterr().err

    def test_does_not_require_claude_code_session_id(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole point: host-side tooling may run outside any session."""
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        sidecar_dir = project / "untracked" / SIGNAL_SUBDIR
        sidecar_dir.mkdir(parents=True)
        (sidecar_dir / "sess-a.json").write_text("{}", encoding="utf-8")

        rc = cli.cmd_signal(_args(project, all_sessions=True))

        assert rc == 0
        assert _signal_path(project, "sess-a").exists()
