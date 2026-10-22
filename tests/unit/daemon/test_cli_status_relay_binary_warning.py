"""``cmd_status`` warns loudly when a configured relay's binary is unusable (Plan 00529, N523).

The exit code stays liveness-only: 0 running, 1 not running.
"""

import argparse
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError as PydanticValidationError

from claude_code_hooks_daemon.config.models import Config, TransportConfig
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.cli import cmd_status


@pytest.fixture(autouse=True)
def mock_git_checks(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "claude_code_hooks_daemon.core.project_context.ProjectContext._get_git_repo_name",
        lambda project_root: "test-repo",
    )
    monkeypatch.setattr(
        "claude_code_hooks_daemon.core.project_context.ProjectContext._get_git_toplevel",
        lambda project_root: project_root,
    )


@pytest.fixture(autouse=True)
def reset_project_context() -> None:
    ProjectContext._initialized = False


def _make_project(tmp_path: Path, binary: Path, *, relay_enabled: bool = True) -> Path:
    claude_dir = tmp_path / ".claude"
    untracked_dir = claude_dir / "hooks-daemon" / "untracked" / "venv"
    untracked_dir.mkdir(parents=True)
    socket_path = untracked_dir / "socket"
    socket_path.touch()
    (claude_dir / "hooks-daemon.yaml").write_text(
        "version: '1.0'\ndaemon:\n  log_level: INFO\n  transport:\n"
        f"    relay_enabled: {'true' if relay_enabled else 'false'}\n"
        f"    relay_binary: {binary}\n"
    )
    return socket_path


def _run(tmp_path: Path, socket_path: Path, pid: int | None) -> int:
    args = argparse.Namespace(project_root=tmp_path)
    with (
        patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=pid),
        patch("claude_code_hooks_daemon.daemon.cli.get_socket_path", return_value=socket_path),
    ):
        return cmd_status(args)


class TestStatusRelayBinaryWarning:
    def test_running_with_missing_binary_warns_and_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        binary = tmp_path / "hooks-relay"
        socket_path = _make_project(tmp_path, binary)

        result = _run(tmp_path, socket_path, 12345)

        out = capsys.readouterr().out
        assert result == 0
        assert "WARNING: relay is enabled but its binary is missing" in out
        assert str(binary) in out
        assert "transport on" in out

    def test_not_running_with_missing_binary_warns_and_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        binary = tmp_path / "hooks-relay"
        socket_path = _make_project(tmp_path, binary)

        result = _run(tmp_path, socket_path, None)

        out = capsys.readouterr().out
        assert result == 1
        assert "Daemon: NOT RUNNING" in out
        assert "WARNING: relay is enabled but its binary is missing" in out
        assert str(binary) in out

    def test_present_binary_is_silent(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        binary = tmp_path / "hooks-relay"
        # A file the relay guard would run (relay_binary_defect is None).
        binary.write_bytes(b"\x7fELF" + b"\x00" * 60)
        binary.chmod(0o755)
        socket_path = _make_project(tmp_path, binary)

        _run(tmp_path, socket_path, 12345)

        assert "relay is enabled but" not in capsys.readouterr().out

    def test_disabled_relay_is_silent_in_both_branches(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        socket_path = _make_project(tmp_path, tmp_path / "hooks-relay", relay_enabled=False)

        _run(tmp_path, socket_path, 12345)
        _run(tmp_path, socket_path, None)

        assert "relay is enabled but" not in capsys.readouterr().out


def _invalid_transport_error() -> PydanticValidationError:
    try:
        TransportConfig.model_validate({"relay_enabled": "not-a-bool"})
    except PydanticValidationError as exc:
        return exc
    raise AssertionError("relay_enabled: 'not-a-bool' must fail validation")


class TestStatusUnreadableTransportConfig:
    """The project already validated at startup; a loader failure inside status is loud."""

    @pytest.mark.parametrize(("pid", "expected_exit"), [(12345, 0), (None, 1)])
    def test_invalid_config_warns_loudly_and_keeps_liveness_exit_code(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        pid: int | None,
        expected_exit: int,
    ) -> None:
        socket_path = _make_project(tmp_path, tmp_path / "hooks-relay")

        with patch.object(Config, "find_and_load", side_effect=_invalid_transport_error()):
            result = _run(tmp_path, socket_path, pid)

        out = capsys.readouterr().out
        assert result == expected_exit
        assert "WARNING: transport config unreadable (" in out
        assert "relay and listener state unknown" in out
        assert "config-validate" in out

    def test_absent_config_is_a_legitimate_silent_state(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        socket_path = _make_project(tmp_path, tmp_path / "hooks-relay")

        with patch.object(Config, "find_and_load", side_effect=FileNotFoundError("gone")):
            result = _run(tmp_path, socket_path, 12345)

        out = capsys.readouterr().out
        assert result == 0
        assert "transport config unreadable" not in out
        assert "relay is enabled but" not in out
