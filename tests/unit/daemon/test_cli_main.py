"""Tests for CLI main() function and argument parsing."""

import contextlib
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon.cli import main


class TestCliMain:
    """Tests for main CLI entry point."""

    def test_main_no_command_shows_help(self) -> None:
        """main() shows help when no command specified."""
        with patch("sys.argv", ["claude-hooks-daemon"]):
            result = main()
            assert result == 1

    def test_main_start_command(self, tmp_path: Path) -> None:
        """main() executes start command."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        with (
            patch(
                "sys.argv",
                ["claude-hooks-daemon", "--project-root", str(tmp_path), "start"],
            ),
            patch("claude_code_hooks_daemon.daemon.cli.cmd_start", return_value=0) as mock_start,
        ):
            result = main()
            assert result == 0
            mock_start.assert_called_once()

    def test_main_stop_command(self, tmp_path: Path) -> None:
        """main() executes stop command."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        with (
            patch("sys.argv", ["claude-hooks-daemon", "--project-root", str(tmp_path), "stop"]),
            patch("claude_code_hooks_daemon.daemon.cli.cmd_stop", return_value=0) as mock_stop,
        ):
            result = main()
            assert result == 0
            mock_stop.assert_called_once()

    def test_main_status_command(self, tmp_path: Path) -> None:
        """main() executes status command."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        with (
            patch("sys.argv", ["claude-hooks-daemon", "--project-root", str(tmp_path), "status"]),
            patch("claude_code_hooks_daemon.daemon.cli.cmd_status", return_value=0) as mock_status,
        ):
            result = main()
            assert result == 0
            mock_status.assert_called_once()

    def test_main_restart_command(self, tmp_path: Path) -> None:
        """main() executes restart command."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        with (
            patch(
                "sys.argv",
                ["claude-hooks-daemon", "--project-root", str(tmp_path), "restart"],
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.cmd_restart", return_value=0
            ) as mock_restart,
        ):
            result = main()
            assert result == 0
            mock_restart.assert_called_once()

    def test_main_logs_command(self, tmp_path: Path) -> None:
        """main() executes logs command."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        with (
            patch("sys.argv", ["claude-hooks-daemon", "--project-root", str(tmp_path), "logs"]),
            patch("claude_code_hooks_daemon.daemon.cli.cmd_logs", return_value=0) as mock_logs,
        ):
            result = main()
            assert result == 0
            mock_logs.assert_called_once()

    def test_main_logs_with_options(self, tmp_path: Path) -> None:
        """main() passes logs options correctly."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        with (
            patch(
                "sys.argv",
                [
                    "claude-hooks-daemon",
                    "--project-root",
                    str(tmp_path),
                    "logs",
                    "-n",
                    "20",
                    "-l",
                    "ERROR",
                    "-f",
                ],
            ),
            patch("claude_code_hooks_daemon.daemon.cli.cmd_logs", return_value=0) as mock_logs,
        ):
            result = main()
            assert result == 0
            mock_logs.assert_called_once()
            args = mock_logs.call_args[0][0]
            assert args.count == 20
            assert args.level == "ERROR"
            assert args.follow is True

    def test_main_health_command(self, tmp_path: Path) -> None:
        """main() executes health command."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        with (
            patch("sys.argv", ["claude-hooks-daemon", "--project-root", str(tmp_path), "health"]),
            patch("claude_code_hooks_daemon.daemon.cli.cmd_health", return_value=0) as mock_health,
        ):
            result = main()
            assert result == 0
            mock_health.assert_called_once()

    def test_main_handlers_command(self, tmp_path: Path) -> None:
        """main() executes handlers command."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        with (
            patch(
                "sys.argv",
                ["claude-hooks-daemon", "--project-root", str(tmp_path), "handlers"],
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.cmd_handlers", return_value=0
            ) as mock_handlers,
        ):
            result = main()
            assert result == 0
            mock_handlers.assert_called_once()

    def test_main_handlers_with_json_option(self, tmp_path: Path) -> None:
        """main() passes --json option to handlers command."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        with (
            patch(
                "sys.argv",
                ["claude-hooks-daemon", "--project-root", str(tmp_path), "handlers", "--json"],
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.cmd_handlers", return_value=0
            ) as mock_handlers,
        ):
            result = main()
            assert result == 0
            mock_handlers.assert_called_once()
            args = mock_handlers.call_args[0][0]
            assert args.json is True

    def test_main_config_command(self, tmp_path: Path) -> None:
        """main() executes config command."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        with (
            patch("sys.argv", ["claude-hooks-daemon", "--project-root", str(tmp_path), "config"]),
            patch("claude_code_hooks_daemon.daemon.cli.cmd_config", return_value=0) as mock_config,
        ):
            result = main()
            assert result == 0
            mock_config.assert_called_once()

    def test_main_config_with_json_option(self, tmp_path: Path) -> None:
        """main() passes --json option to config command."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        with (
            patch(
                "sys.argv",
                ["claude-hooks-daemon", "--project-root", str(tmp_path), "config", "--json"],
            ),
            patch("claude_code_hooks_daemon.daemon.cli.cmd_config", return_value=0) as mock_config,
        ):
            result = main()
            assert result == 0
            mock_config.assert_called_once()
            args = mock_config.call_args[0][0]
            assert args.json is True

    def test_main_init_config_command(self, tmp_path: Path) -> None:
        """main() executes init-config command."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        with (
            patch(
                "sys.argv",
                ["claude-hooks-daemon", "--project-root", str(tmp_path), "init-config"],
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.cmd_init_config", return_value=0
            ) as mock_init,
        ):
            result = main()
            assert result == 0
            mock_init.assert_called_once()

    def test_main_init_config_with_minimal(self, tmp_path: Path) -> None:
        """main() passes --minimal option to init-config command."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        with (
            patch(
                "sys.argv",
                [
                    "claude-hooks-daemon",
                    "--project-root",
                    str(tmp_path),
                    "init-config",
                    "--minimal",
                ],
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.cmd_init_config", return_value=0
            ) as mock_init,
        ):
            result = main()
            assert result == 0
            mock_init.assert_called_once()
            args = mock_init.call_args[0][0]
            assert args.minimal is True

    def test_main_init_config_with_force(self, tmp_path: Path) -> None:
        """main() passes --force option to init-config command."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        with (
            patch(
                "sys.argv",
                [
                    "claude-hooks-daemon",
                    "--project-root",
                    str(tmp_path),
                    "init-config",
                    "--force",
                ],
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.cmd_init_config", return_value=0
            ) as mock_init,
        ):
            result = main()
            assert result == 0
            mock_init.assert_called_once()
            args = mock_init.call_args[0][0]
            assert args.force is True


class _Execed(Exception):
    """Raised by the patched ``os.execv``: the process would be replaced."""


class TestAStartNamingNoRootIsRerunNamingIt:
    """Plan 00466 round 6 (Sh-1): a daemon started without ``--project-root``
    serves the project its working directory finds, and leaves that
    directory at once, so its command line named the project owning its
    venv instead. ``main`` re-runs such a start naming the project, so every
    daemon's command line says which project it serves."""

    _CLI = "claude_code_hooks_daemon.daemon.cli"

    @contextlib.contextmanager
    def _main(self, argv: list[str], project: Path) -> Iterator[tuple[Any, Any, Any]]:
        """``main``'s collaborators for ``argv``: the execv, start and restart mocks."""
        with (
            patch("sys.argv", ["claude-hooks-daemon", *argv]),
            patch(f"{self._CLI}.get_project_path", return_value=project),
            patch(f"{self._CLI}.cmd_start", return_value=0) as start,
            patch(f"{self._CLI}.cmd_restart", return_value=0) as restart,
            patch("os.execv", side_effect=_Execed) as execv,
        ):
            yield execv, start, restart

    @pytest.mark.parametrize("subcommand", ["start", "restart"])
    def test_a_launch_naming_no_root_is_rerun_naming_it(
        self, tmp_path: Path, subcommand: str
    ) -> None:
        socket_path = str(tmp_path / "daemon.sock")
        with self._main(["--socket", socket_path, subcommand], tmp_path) as (
            execv,
            start,
            restart,
        ):
            with pytest.raises(_Execed):
                main()
        execv.assert_called_once_with(
            sys.executable,
            [
                sys.executable,
                "-m",
                self._CLI,
                "--project-root",
                str(tmp_path),
                "--socket",
                socket_path,
                subcommand,
            ],
        )
        start.assert_not_called()
        restart.assert_not_called()

    def test_a_launch_naming_its_root_runs_as_it_is(self, tmp_path: Path) -> None:
        argv = ["--project-root", str(tmp_path), "start"]
        with self._main(argv, tmp_path) as (execv, start, _restart):
            assert main() == 0
        execv.assert_not_called()
        start.assert_called_once()

    def test_another_command_naming_no_root_runs_as_it_is(self, tmp_path: Path) -> None:
        with (
            self._main(["stop"], tmp_path) as (execv, _start, _restart),
            patch(f"{self._CLI}.cmd_stop", return_value=0) as stop,
        ):
            assert main() == 0
        execv.assert_not_called()
        stop.assert_called_once()
