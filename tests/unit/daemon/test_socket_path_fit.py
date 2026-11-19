"""Plan 00628: one function fits every socket and PID path to the AF_UNIX limit.

A client seat with a long project path had every tool call denied: ``init.sh``
forced its own default socket path on the daemon through
``CLAUDE_HOOKS_SOCKET_PATH``, ``get_socket_path`` returned an override
verbatim, the bind failed ("AF_UNIX path too long"), and the CLI, invoked
without the override, reported a daemon RUNNING somewhere else. Whoever names
the path (the default, the env, the ``--socket`` flag, the config), the path
the daemon binds and the one every other caller computes must be the same
fitted path, and must never exceed the limit.

The short directory that replaces an over-limit path must keep the protection
the untracked directory had (owned by this user, closed to everyone else), and
never be a bare shared ``/tmp``.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import DaemonConfig
from claude_code_hooks_daemon.daemon import cli, paths
from claude_code_hooks_daemon.daemon.paths import (
    _UNIX_SOCKET_PATH_LIMIT,
    UnsafeRuntimeDirError,
    fit_pid_path,
    fit_socket_path,
    get_pid_path,
    get_socket_path,
    pid_path_for,
)

_HOST = "client-seat-dev-vm01"


@pytest.fixture
def runtime_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private runtime dir (0700, ours), as a real ``$XDG_RUNTIME_DIR`` is."""
    run = tmp_path / "run"
    run.mkdir(mode=0o700)
    run.chmod(0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(run))
    monkeypatch.setenv("HOSTNAME", _HOST)
    for name in ("CLAUDE_HOOKS_SOCKET_PATH", "CLAUDE_HOOKS_PID_PATH"):
        monkeypatch.delenv(name, raising=False)
    return run


@pytest.fixture
def long_project(tmp_path: Path) -> Path:
    """A project whose natural socket path is well over the limit."""
    root = tmp_path / ("p" * 120)
    (root / ".claude" / "hooks-daemon" / "untracked").mkdir(parents=True)
    return root


def _init_sh_default(project: Path, suffix: str) -> Path:
    """The path ``init.sh`` computes and forces: untracked dir + host suffix."""
    return project / ".claude" / "hooks-daemon" / "untracked" / f"daemon-{_HOST}.{suffix}"


class TestEveryCallerGetsAFittedPath:
    def test_forced_over_limit_socket_is_the_one_the_cli_computes(
        self, runtime_dir: Path, long_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        computed = get_socket_path(long_project)
        monkeypatch.setenv("CLAUDE_HOOKS_SOCKET_PATH", str(_init_sh_default(long_project, "sock")))

        forced = get_socket_path(long_project)

        assert len(str(forced)) <= _UNIX_SOCKET_PATH_LIMIT
        assert forced == computed, "a hook's forced start and the CLI must agree on one socket"
        assert forced.parent == runtime_dir

    def test_forced_over_limit_pid_is_the_one_the_cli_computes(
        self, runtime_dir: Path, long_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_HOOKS_PID_PATH", str(_init_sh_default(long_project, "pid")))

        assert get_pid_path(long_project) == pid_path_for(long_project)
        assert get_pid_path(long_project).parent == runtime_dir

    def test_a_short_forced_path_is_honoured_verbatim(
        self, runtime_dir: Path, long_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_HOOKS_SOCKET_PATH", "/tmp/short.sock")
        monkeypatch.setenv("CLAUDE_HOOKS_PID_PATH", "/tmp/short.pid")

        assert get_socket_path(long_project) == Path("/tmp/short.sock")
        assert get_pid_path(long_project) == Path("/tmp/short.pid")

    def test_cli_socket_flag_is_fitted(self, runtime_dir: Path, long_project: Path) -> None:
        flag = argparse.Namespace(socket=str(_init_sh_default(long_project, "sock")))
        pid_flag = argparse.Namespace(pid_file=str(_init_sh_default(long_project, "pid")))

        assert cli._resolve_socket_path(flag, long_project) == get_socket_path(long_project)
        assert cli._resolve_pid_path(pid_flag, long_project) == pid_path_for(long_project)

    def test_configured_paths_are_fitted(self, runtime_dir: Path, long_project: Path) -> None:
        config = DaemonConfig(
            socket_path=str(_init_sh_default(long_project, "sock")),
            pid_file_path=str(_init_sh_default(long_project, "pid")),
        )

        assert config.get_socket_path(long_project) == get_socket_path(long_project)
        assert config.get_pid_file_path(long_project) == pid_path_for(long_project)

    @pytest.mark.parametrize("length", [_UNIX_SOCKET_PATH_LIMIT, _UNIX_SOCKET_PATH_LIMIT + 1, 300])
    def test_no_requested_length_yields_an_over_limit_socket(
        self, runtime_dir: Path, long_project: Path, length: int
    ) -> None:
        requested = Path("/" + "s" * (length - len("/.sock")) + ".sock")
        assert len(str(requested)) == length

        fitted = fit_socket_path(long_project, requested)

        assert len(str(fitted)) <= _UNIX_SOCKET_PATH_LIMIT
        if length <= _UNIX_SOCKET_PATH_LIMIT:
            assert fitted == requested

    def test_pid_fit_decides_on_the_pid_paths_own_length(
        self, runtime_dir: Path, long_project: Path
    ) -> None:
        at_limit = Path("/" + "s" * (_UNIX_SOCKET_PATH_LIMIT - len("/.pid")) + ".pid")
        assert fit_pid_path(long_project, at_limit) == at_limit
        over = Path(str(at_limit).replace("/s", "/ss", 1))
        assert fit_pid_path(long_project, over) == pid_path_for(long_project)


class TestOneFunctionDecides:
    def test_every_caller_delegates_to_fit_socket_path(
        self, runtime_dir: Path, long_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sentinel = Path("/decided/by/fit.sock")
        monkeypatch.setattr(paths, "fit_socket_path", lambda _project, _requested=None: sentinel)
        monkeypatch.setenv("CLAUDE_HOOKS_SOCKET_PATH", "/x.sock")

        assert get_socket_path(long_project) == sentinel
        assert cli._resolve_socket_path(argparse.Namespace(socket="/y.sock"), long_project) == (
            sentinel
        )
        assert DaemonConfig(socket_path="/z.sock").get_socket_path(long_project) == sentinel


@pytest.fixture
def no_runtime_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """No ``$XDG_RUNTIME_DIR`` and no ``/run/user/<uid>``; a fake shared ``/tmp``."""
    shared = tmp_path / "shared-tmp"
    shared.mkdir()
    shared.chmod(0o1777)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("HOSTNAME", _HOST)
    monkeypatch.setattr(paths, "_RUN_USER_ROOT", tmp_path / "no-run-user")
    monkeypatch.setattr(paths, "_SHARED_TMP", shared)
    for name in ("CLAUDE_HOOKS_SOCKET_PATH", "CLAUDE_HOOKS_PID_PATH"):
        monkeypatch.delenv(name, raising=False)
    yield shared


class TestShortPathRootIsPrivate:
    def test_a_group_or_world_open_runtime_dir_is_not_used(
        self, runtime_dir: Path, long_project: Path, no_runtime_dir: Path, monkeypatch
    ) -> None:
        runtime_dir.chmod(0o755)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir))

        socket_path = get_socket_path(long_project)

        assert runtime_dir not in socket_path.parents

    def test_a_symlinked_runtime_dir_is_not_used(
        self, runtime_dir: Path, long_project: Path, no_runtime_dir: Path, monkeypatch
    ) -> None:
        link = runtime_dir.parent / "run-link"
        link.symlink_to(runtime_dir)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(link))

        assert link not in get_socket_path(long_project).parents

    def test_without_a_runtime_dir_a_private_subdir_of_tmp_is_used(
        self, long_project: Path, no_runtime_dir: Path
    ) -> None:
        socket_path = get_socket_path(long_project)

        assert socket_path.parent != no_runtime_dir, "never a bare shared /tmp"
        assert socket_path.parent.parent == no_runtime_dir
        st = os.lstat(socket_path.parent)
        assert st.st_uid == os.geteuid()
        assert st.st_mode & 0o077 == 0
        assert len(str(socket_path)) <= _UNIX_SOCKET_PATH_LIMIT

    def test_a_squatted_tmp_subdir_fails_closed(
        self, long_project: Path, no_runtime_dir: Path
    ) -> None:
        squatted = no_runtime_dir / f"hooks-daemon-{os.geteuid()}"
        squatted.mkdir()
        squatted.chmod(0o777)

        with pytest.raises(UnsafeRuntimeDirError, match=str(squatted)):
            get_socket_path(long_project)

    def test_a_symlinked_tmp_subdir_fails_closed(
        self, long_project: Path, no_runtime_dir: Path, tmp_path: Path
    ) -> None:
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir(mode=0o700)
        (no_runtime_dir / f"hooks-daemon-{os.geteuid()}").symlink_to(elsewhere)

        with pytest.raises(UnsafeRuntimeDirError):
            get_socket_path(long_project)

    def test_cli_start_reports_the_unsafe_dir_and_does_not_fork(
        self,
        long_project: Path,
        no_runtime_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (no_runtime_dir / f"hooks-daemon-{os.geteuid()}").mkdir(mode=0o777)
        (no_runtime_dir / f"hooks-daemon-{os.geteuid()}").chmod(0o777)

        def _no_fork() -> int:
            raise AssertionError("must not fork with no safe socket directory")

        monkeypatch.setattr(os, "fork", _no_fork)
        monkeypatch.setattr(cli, "get_project_path", lambda _root: long_project)
        assert cli.cmd_start(argparse.Namespace(project_root=long_project)) == 1
        assert "hooks-daemon-" in capsys.readouterr().err
