"""Tests for cmd_repair CLI command.

Covers:
- Successful venv repair via uv sync
- uv not found error
- uv sync failure
- uv sync timeout
- Verification failure after repair
- Stops running daemon before repair
"""

import argparse
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.daemon.cli import (
    _UV_SYNC_TIMEOUT_SECONDS,
    _VERIFY_IMPORT_TIMEOUT_SECONDS,
    _judge_repaired_venv_is_resolved,
    cmd_repair,
)
from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint
from claude_code_hooks_daemon.daemon.venv_lock import VenvLockTimeout

#: The uv every test here resolves, wherever this machine keeps its own.
_UV: str = "/opt/uv/bin/uv"


@pytest.fixture(autouse=True)
def _resolved_uv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("claude_code_hooks_daemon.daemon.cli.find_uv", lambda: _UV)


@pytest.fixture(autouse=True)
def _resolver_names_the_target(monkeypatch: pytest.MonkeyPatch) -> None:
    """The mocked syncs build nothing on disk, so let the resolver name the repair's target.

    The judge itself is tested for real in ``TestRepairIsJudgedByTheResolver``.
    """

    def _target(daemon_dir: Path | str) -> tuple[Path, list[str]]:
        keyed = Path(daemon_dir) / "untracked" / f"venv-{python_venv_fingerprint(daemon_dir)}"
        return keyed / "bin" / "python", []

    monkeypatch.setattr(
        "claude_code_hooks_daemon.daemon.cli.resolve_existing_venv_python_with_diagnostics",
        _target,
    )


class TestRepairIsJudgedByTheResolver:
    """Plan 00555 Task 2.1: a repair that the resolver does not pick is not a repair."""

    def test_the_resolved_venv_being_the_repaired_one_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        built = tmp_path / "untracked" / "venv-built"
        monkeypatch.setattr(
            "claude_code_hooks_daemon.daemon.cli.resolve_existing_venv_python_with_diagnostics",
            lambda _d: (built / "bin" / "python", []),
        )
        assert _judge_repaired_venv_is_resolved(tmp_path, built) == 0

    def test_another_venv_winning_resolution_fails_and_names_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        built = tmp_path / "untracked" / "venv-built"
        older = tmp_path / "untracked" / "venv-older"
        monkeypatch.setattr(
            "claude_code_hooks_daemon.daemon.cli.resolve_existing_venv_python_with_diagnostics",
            lambda _d: (older / "bin" / "python", []),
        )
        assert _judge_repaired_venv_is_resolved(tmp_path, built) == 1
        assert str(older) in capsys.readouterr().out

    def test_nothing_resolving_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            "claude_code_hooks_daemon.daemon.cli.resolve_existing_venv_python_with_diagnostics",
            lambda _d: (None, []),
        )
        assert _judge_repaired_venv_is_resolved(tmp_path, tmp_path / "untracked" / "venv-x") == 1
        assert "no venv" in capsys.readouterr().out


class TestCmdRepairUsesTheBuildsUv:
    """Review B2: the repair spawns the uv the gate and the bash build found.

    A bare ``uv`` spawn misses ``~/.local/bin`` (uv's default home), which the
    bash build puts on PATH itself. So ``bin/hooks-daemon repair`` built the
    venv and then failed with "'uv' not found", and the skill escalated.
    """

    def _args(self, tmp_path: Path) -> argparse.Namespace:
        return argparse.Namespace(project_root=tmp_path)

    def test_the_sync_spawns_the_resolved_uv(self, tmp_path: Path) -> None:
        done = MagicMock(returncode=0, stderr="", stdout="OK\n")
        with (
            patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("subprocess.run", return_value=done) as mock_run,
        ):
            assert cmd_repair(self._args(tmp_path)) == 0

        assert mock_run.call_args_list[0].args[0] == [_UV, "sync"]

    def test_no_uv_anywhere_names_both_places_and_spawns_nothing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("claude_code_hooks_daemon.daemon.cli.find_uv", lambda: None)
        with (
            patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("subprocess.run") as mock_run,
        ):
            assert cmd_repair(self._args(tmp_path)) == 1

        mock_run.assert_not_called()
        out = capsys.readouterr().out
        assert "'uv' not found" in out
        assert "~/.local/bin" in out


class TestCmdRepair:
    """Tests for cmd_repair command."""

    def _make_args(self, tmp_path: Path) -> argparse.Namespace:
        """Create args namespace with project_root."""
        return argparse.Namespace(project_root=tmp_path)

    def test_uv_sync_timeout_is_in_seconds_not_milliseconds(self, tmp_path: Path) -> None:
        """The timeout handed to subprocess.run must be SECONDS, not the
        millisecond BASH_DEFAULT constant.

        Regression: cmd_repair passed Timeout.BASH_DEFAULT (=120_000 ms)
        straight into subprocess.run(timeout=...), whose unit is SECONDS, so
        ``uv sync`` effectively never timed out (~33 hours).
        """
        args = self._make_args(tmp_path)

        mock_sync = MagicMock()
        mock_sync.returncode = 0
        mock_sync.stderr = ""

        mock_verify = MagicMock()
        mock_verify.returncode = 0
        mock_verify.stdout = "OK\n"

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("subprocess.run", side_effect=[mock_sync, mock_verify]) as mock_run,
        ):
            result = cmd_repair(args)

        assert result == 0
        sync_call = mock_run.call_args_list[0]
        passed_timeout = sync_call.kwargs["timeout"]
        # Must be the named seconds constant, NOT the millisecond BASH_DEFAULT.
        assert passed_timeout == _UV_SYNC_TIMEOUT_SECONDS
        assert passed_timeout == Timeout.BASH_DEFAULT // 1000
        assert passed_timeout != Timeout.BASH_DEFAULT

    def test_verification_subprocess_has_explicit_timeout(self, tmp_path: Path) -> None:
        """Finding #35: the post-repair import verification subprocess must be
        bounded by an explicit timeout (seconds), like the ``uv sync`` call.

        Without it, an interpreter that hangs on import made ``repair`` hang
        forever with no recovery.
        """
        args = self._make_args(tmp_path)

        mock_sync = MagicMock()
        mock_sync.returncode = 0
        mock_sync.stderr = ""

        mock_verify = MagicMock()
        mock_verify.returncode = 0
        mock_verify.stdout = "OK\n"

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("subprocess.run", side_effect=[mock_sync, mock_verify]) as mock_run,
        ):
            result = cmd_repair(args)

        assert result == 0
        verify_call = mock_run.call_args_list[1]
        assert verify_call.kwargs["timeout"] == _VERIFY_IMPORT_TIMEOUT_SECONDS
        assert _VERIFY_IMPORT_TIMEOUT_SECONDS > 0

    def test_verification_timeout_returns_failure(self, tmp_path: Path) -> None:
        """Finding #35: a hung verification import (TimeoutExpired) is a repair
        failure, returning 1 rather than crashing with an uncaught exception.
        """
        args = self._make_args(tmp_path)

        mock_sync = MagicMock()
        mock_sync.returncode = 0
        mock_sync.stderr = ""

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch(
                "subprocess.run",
                side_effect=[
                    mock_sync,
                    subprocess.TimeoutExpired("python", _VERIFY_IMPORT_TIMEOUT_SECONDS),
                ],
            ),
        ):
            result = cmd_repair(args)

        assert result == 1

    def test_successful_repair(self, tmp_path: Path) -> None:
        """cmd_repair returns 0 on successful uv sync + verification."""
        args = self._make_args(tmp_path)

        mock_sync = MagicMock()
        mock_sync.returncode = 0
        mock_sync.stderr = ""

        mock_verify = MagicMock()
        mock_verify.returncode = 0
        mock_verify.stdout = "OK\n"

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("subprocess.run", side_effect=[mock_sync, mock_verify]),
        ):
            result = cmd_repair(args)
            assert result == 0

    def test_uv_not_found(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """cmd_repair returns 1, and names uv, when uv is not installed."""
        args = self._make_args(tmp_path)

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("subprocess.run", side_effect=FileNotFoundError("uv")),
        ):
            result = cmd_repair(args)
            assert result == 1
        assert "'uv' not found" in capsys.readouterr().out

    def test_a_lock_layer_file_not_found_is_not_reported_as_a_missing_uv(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Only the uv SPAWN can mean a missing toolchain.

        A FileNotFoundError raised anywhere else — the venv lock is the one
        that races, by construction — is a different fault, and printing
        "install uv" for it sends the reader to fix something that is not
        broken.
        """
        args = self._make_args(tmp_path)
        lock_path = tmp_path / "untracked" / ".venv-bootstrap.lock.d"

        @contextmanager
        def broken_lock(_project_root: Path, **_kwargs: object) -> Iterator[None]:
            raise FileNotFoundError(2, "No such file or directory", str(lock_path))
            yield

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("claude_code_hooks_daemon.daemon.cli.venv_lock", broken_lock),
            patch("subprocess.run") as mock_run,
        ):
            result = cmd_repair(args)

        assert result == 1
        mock_run.assert_not_called()
        out = capsys.readouterr().out
        assert "'uv' not found" not in out
        assert ".venv-bootstrap.lock" in out

    def test_uv_sync_failure(self, tmp_path: Path) -> None:
        """cmd_repair returns 1 when uv sync fails."""
        args = self._make_args(tmp_path)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error: could not resolve dependencies"

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = cmd_repair(args)
            assert result == 1

    def test_uv_sync_timeout(self, tmp_path: Path) -> None:
        """cmd_repair returns 1 when uv sync times out."""
        args = self._make_args(tmp_path)

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired("uv", 120)),
        ):
            result = cmd_repair(args)
            assert result == 1

    def test_verification_failure(self, tmp_path: Path) -> None:
        """cmd_repair returns 1 when import verification fails after sync."""
        args = self._make_args(tmp_path)

        mock_sync = MagicMock()
        mock_sync.returncode = 0
        mock_sync.stderr = ""

        mock_verify = MagicMock()
        mock_verify.returncode = 1
        mock_verify.stderr = "ModuleNotFoundError: No module named 'claude_code_hooks_daemon'"

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("subprocess.run", side_effect=[mock_sync, mock_verify]),
        ):
            result = cmd_repair(args)
            assert result == 1

    def test_uv_sync_runs_under_the_venv_build_lock(self, tmp_path: Path) -> None:
        """Plan 00100 Task 4.3: repair contends on the same lock as ensure_venv.

        The ``uv sync`` must run INSIDE the lock's context — a lock taken and
        released around nothing would satisfy a call-count assertion and
        protect nothing.
        """
        args = self._make_args(tmp_path)
        events: list[str] = []

        @contextmanager
        def fake_lock(daemon_dir: Path, **_kwargs: object) -> Iterator[None]:
            # tmp_path has no src/ tree, so it is a CLIENT layout: the lock
            # belongs to the daemon dir beneath it (Plan 00456).
            assert daemon_dir == tmp_path / ".claude" / "hooks-daemon"
            events.append("lock")
            yield
            events.append("unlock")

        def fake_run(*_a: object, **_k: object) -> MagicMock:
            events.append("uv sync" if not events.count("uv sync") else "verify")
            done = MagicMock()
            done.returncode = 0
            done.stderr = ""
            done.stdout = "OK\n"
            return done

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("claude_code_hooks_daemon.daemon.cli.venv_lock", fake_lock),
            patch("subprocess.run", side_effect=fake_run),
        ):
            result = cmd_repair(args)

        assert result == 0
        assert events[0] == "lock" and events[-1] == "unlock", events
        assert "uv sync" in events[1:-1], f"uv sync must run inside the lock: {events}"

    def test_lock_timeout_is_reported_not_raised(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A held lock past the bound is a clear failure exit, not a traceback."""
        args = self._make_args(tmp_path)

        @contextmanager
        def held_lock(_project_root: Path, **_kwargs: object) -> Iterator[None]:
            raise VenvLockTimeout("gave up waiting for the venv lock after 120s: /x/lock")
            yield

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("claude_code_hooks_daemon.daemon.cli.venv_lock", held_lock),
            patch("subprocess.run") as mock_run,
        ):
            result = cmd_repair(args)

        assert result == 1
        mock_run.assert_not_called()
        assert "gave up waiting for the venv lock" in capsys.readouterr().out

    def test_stops_daemon_before_repair(self, tmp_path: Path) -> None:
        """cmd_repair stops running daemon before repairing."""
        args = self._make_args(tmp_path)

        mock_sync = MagicMock()
        mock_sync.returncode = 0
        mock_sync.stderr = ""

        mock_verify = MagicMock()
        mock_verify.returncode = 0
        mock_verify.stdout = "OK\n"

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch("claude_code_hooks_daemon.daemon.cli.cmd_stop") as mock_stop,
            patch("subprocess.run", side_effect=[mock_sync, mock_verify]),
            patch("time.sleep"),
        ):
            result = cmd_repair(args)
            assert result == 0
            mock_stop.assert_called_once_with(args)


class TestCmdRepairTargetsTheDaemonDir:
    """Plan 00456: the repair builds the venv the resolver will look for.

    In a client install the daemon dir is ``{project}/.claude/hooks-daemon``,
    not the project root. Bash ``ensure_venv`` and the resolver key the venv,
    its lock and its ``uv sync`` on the DAEMON dir. A repair keyed on the
    project root takes a different lock, names ``venv-<project-slug>-…`` (which
    the resolver's slug check refuses, Plan 00313), and runs ``uv sync`` in
    the client's own project. Self-install hides all three, because there the
    two directories are one.
    """

    def _repair(self, project_root: Path) -> tuple[int, list[dict[str, object]], list[Path]]:
        sync_calls: list[dict[str, object]] = []
        locked: list[Path] = []

        @contextmanager
        def fake_lock(daemon_dir: Path, **_kwargs: object) -> Iterator[None]:
            locked.append(daemon_dir)
            yield

        def fake_run(argv: list[str], **kwargs: object) -> MagicMock:
            if argv[:2] == [_UV, "sync"]:
                sync_calls.append({"argv": argv, **kwargs})
            done = MagicMock()
            done.returncode = 0
            done.stderr = ""
            done.stdout = "OK\n"
            return done

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=project_root,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("claude_code_hooks_daemon.daemon.cli.venv_lock", fake_lock),
            patch("subprocess.run", side_effect=fake_run),
        ):
            rc = cmd_repair(argparse.Namespace(project_root=project_root))
        return rc, sync_calls, locked

    def test_client_install_repairs_under_the_daemon_dir(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint

        project = tmp_path / "client"
        daemon_dir = project / ".claude" / "hooks-daemon"
        daemon_dir.mkdir(parents=True)

        rc, sync_calls, locked = self._repair(project)

        assert rc == 0
        assert locked == [daemon_dir], "the lock must be the one bash ensure_venv takes"
        assert len(sync_calls) == 1
        assert sync_calls[0]["cwd"] == str(daemon_dir), "uv sync must sync the DAEMON's project"
        env = sync_calls[0]["env"]
        assert isinstance(env, dict)
        expected = daemon_dir / "untracked" / f"venv-{python_venv_fingerprint(daemon_dir)}"
        assert env["UV_PROJECT_ENVIRONMENT"] == str(expected)

    def test_repair_records_the_lock_it_built_for(self, tmp_path: Path) -> None:
        """Plan 00474 N469: a repaired venv is PROVEN built for the current source.

        ``repair`` is the fix the stale-venv advisory names. Without metadata the
        resolver cannot rank the repaired venv first, and the advisory cannot
        tell it was repaired, so it would keep firing.
        """
        import json
        import sys

        from claude_code_hooks_daemon.daemon.paths import (
            _compute_project_lock_hash_stdlib,
            python_venv_fingerprint,
            venv_lock_drift,
        )

        project = tmp_path / "daemon-repo"
        (project / "src" / "claude_code_hooks_daemon").mkdir(parents=True)
        (project / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        venv = project / "untracked" / f"venv-{python_venv_fingerprint(project)}"
        (venv / "bin").mkdir(parents=True)
        (venv / "bin" / "python").symlink_to(Path(sys.executable).resolve())

        rc, _sync_calls, _locked = self._repair(project)

        assert rc == 0
        metadata = json.loads((venv / ".daemon-metadata.json").read_text())
        assert metadata["lock_hash"] == _compute_project_lock_hash_stdlib(project)
        assert venv_lock_drift(project, venv) is None

    def test_self_install_is_unchanged(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint

        project = tmp_path / "daemon-repo"
        (project / "src" / "claude_code_hooks_daemon").mkdir(parents=True)

        rc, sync_calls, locked = self._repair(project)

        assert rc == 0
        assert locked == [project]
        assert sync_calls[0]["cwd"] == str(project)
        env = sync_calls[0]["env"]
        assert isinstance(env, dict)
        expected = project / "untracked" / f"venv-{python_venv_fingerprint(project)}"
        assert env["UV_PROJECT_ENVIRONMENT"] == str(expected)


class TestRepairInstallsDevExtrasOnSelfInstallOnly:
    """Plan 00555 Task 3.1: ``dev`` is an extra, so a bare ``uv sync`` omits it."""

    def _sync_argv(self, daemon_dir: Path) -> list[str]:
        from claude_code_hooks_daemon.daemon.cli import _repair_venv_locked

        venv_path = daemon_dir / "untracked" / "venv-x-py311-00000000"
        done = MagicMock(returncode=1, stderr="stop here", stdout="")
        with patch("subprocess.run", return_value=done) as mock_run:
            _repair_venv_locked(daemon_dir, venv_path, {})
        argv: list[str] = mock_run.call_args_list[0].args[0]
        return argv

    def test_self_install_layout_syncs_with_the_dev_extra(self, tmp_path: Path) -> None:
        assert self._sync_argv(tmp_path / "checkout") == [_UV, "sync", "--extra", "dev"]

    def test_client_layout_syncs_without_extras(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "project" / ".claude" / "hooks-daemon"
        assert self._sync_argv(daemon_dir) == [_UV, "sync"]
