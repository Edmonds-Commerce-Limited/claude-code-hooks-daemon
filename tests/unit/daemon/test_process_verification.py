"""Tests for daemon process verification logic."""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import psutil
import pytest

from claude_code_hooks_daemon.daemon.paths import prospective_socket_path
from claude_code_hooks_daemon.daemon.process_verification import (
    PROJECT_ROOT_ENV_VAR,
    RootProof,
    daemon_process_project_root,
    find_all_daemon_processes,
    is_this_users_process,
    root_names_project,
)

_MODULE = "claude_code_hooks_daemon.daemon.cli"


def _client_project(root: Path) -> Path:
    """A client project at ``root``: its daemon's files live under
    ``.claude/hooks-daemon/untracked``."""
    (root / ".claude" / "hooks-daemon" / "untracked").mkdir(parents=True)
    return root


def _self_install_project(root: Path) -> Path:
    """A self-install checkout at ``root``: the daemon's source is its own."""
    (root / "src" / "claude_code_hooks_daemon").mkdir(parents=True)
    (root / "untracked").mkdir()
    return root


def _natural_socket(project: Path, *, self_install: bool = False) -> Path:
    return prospective_socket_path(project, self_install=self_install)


def _listening(path: Path) -> SimpleNamespace:
    """A unix connection psutil reports for a socket bound at ``path``."""
    return SimpleNamespace(laddr=str(path), raddr="", status=psutil.CONN_NONE)


# A pid no real process carries (above the kernel's pid_max ceiling), so no
# test here can ever name a live process even if a mock is bypassed.
_UNREAL_PID = 2**22 + 7
_OWN_ROOT = "/srv/projects/ours"
_DAEMON_CMDLINE = [
    f"{_OWN_ROOT}/untracked/venv/bin/python",
    "-m",
    "claude_code_hooks_daemon.daemon.cli",
    "--project-root",
    _OWN_ROOT,
    "start",
]


class TestFindAllDaemonProcesses:
    """Tests for find_all_daemon_processes()."""

    def test_no_daemon_processes_exist(self) -> None:
        """Returns empty list when no daemon processes found."""
        mock_processes = [
            self._create_mock_process(pid=100, name="python", cmdline=["python", "script.py"]),
            self._create_mock_process(pid=200, name="bash", cmdline=["bash"]),
            self._create_mock_process(pid=300, name="systemd", cmdline=["systemd"]),
        ]

        with patch("psutil.process_iter", return_value=mock_processes):
            result = find_all_daemon_processes()

        assert result == []

    def test_single_daemon_process_exists(self) -> None:
        """Returns single PID when one daemon process found."""
        mock_processes = [
            self._create_mock_process(pid=100, name="python", cmdline=["python", "script.py"]),
            self._create_mock_process(
                pid=200,
                name="python",
                cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.cli", "start"],
            ),
            self._create_mock_process(pid=300, name="bash", cmdline=["bash"]),
        ]

        with patch("psutil.process_iter", return_value=mock_processes):
            result = find_all_daemon_processes()

        assert result == [200]

    def test_multiple_daemon_processes_exist(self) -> None:
        """Returns all server PIDs; transient CLI helpers are excluded."""
        mock_processes = [
            self._create_mock_process(
                pid=100,
                name="python",
                cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.cli", "start"],
            ),
            self._create_mock_process(pid=200, name="bash", cmdline=["bash"]),
            self._create_mock_process(
                pid=300,
                name="python",
                cmdline=[
                    "/usr/bin/python3",
                    "-m",
                    "claude_code_hooks_daemon.daemon.cli",
                    "restart",
                ],
            ),
            # Transient CLI helper — NOT a daemon server, must be excluded.
            self._create_mock_process(
                pid=400,
                name="python",
                cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.cli", "status"],
            ),
        ]

        with patch("psutil.process_iter", return_value=mock_processes):
            result = find_all_daemon_processes()

        assert sorted(result) == [100, 300]

    def test_broad_substring_matches_are_rejected(self) -> None:
        """The old name/substring matching is gone: only a cli module + launch
        subcommand cmdline counts as a daemon server."""
        mock_processes = [
            # NOT a server: package string only in the process name.
            self._create_mock_process(pid=100, name="claude_code_hooks_daemon", cmdline=["daemon"]),
            # NOT a server: package string only as a wrapper-script substring.
            self._create_mock_process(
                pid=400,
                name="python",
                cmdline=["python", "my_claude_code_hooks_daemon_wrapper.py"],
            ),
            # NOT a server: bare package module, no .daemon.cli, no subcommand.
            self._create_mock_process(
                pid=500,
                name="python",
                cmdline=["python", "-m", "claude_code_hooks_daemon"],
            ),
            # The only real server in the set.
            self._create_mock_process(
                pid=600,
                name="python",
                cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.cli", "start"],
            ),
        ]

        with patch("psutil.process_iter", return_value=mock_processes):
            result = find_all_daemon_processes()

        assert result == [600]

    def test_handles_permission_errors_gracefully(self) -> None:
        """Ignores processes whose cmdline() raises AccessDenied."""
        mock_process_ok = self._create_mock_process(
            pid=100,
            name="python",
            cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.cli", "start"],
        )
        mock_process_denied = MagicMock(spec=psutil.Process)
        mock_process_denied.pid = 200
        mock_process_denied.cmdline.side_effect = psutil.AccessDenied(pid=200)

        mock_processes = [mock_process_ok, mock_process_denied]

        with patch("psutil.process_iter", return_value=mock_processes):
            result = find_all_daemon_processes()

        # Should only find the accessible process
        assert result == [100]

    def test_handles_no_such_process_errors_gracefully(self) -> None:
        """Ignores processes that disappeared during iteration."""
        mock_process_ok = self._create_mock_process(
            pid=100,
            name="python",
            cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.cli", "start"],
        )
        mock_process_gone = MagicMock(spec=psutil.Process)
        mock_process_gone.pid = 200
        mock_process_gone.cmdline.side_effect = psutil.NoSuchProcess(pid=200)

        mock_processes = [mock_process_ok, mock_process_gone]

        with patch("psutil.process_iter", return_value=mock_processes):
            result = find_all_daemon_processes()

        # Should only find the still-existing process
        assert result == [100]

    def test_excludes_current_process(self) -> None:
        """Does not include the current process PID in results."""
        current_pid = os.getpid()
        mock_processes = [
            self._create_mock_process(
                pid=current_pid,
                name="python",
                cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.cli", "start"],
            ),
            self._create_mock_process(
                pid=current_pid + 1,
                name="python",
                cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.cli", "start"],
            ),
        ]

        with patch("psutil.process_iter", return_value=mock_processes):
            result = find_all_daemon_processes()

        # Should only include the other process, not current
        assert result == [current_pid + 1]

    @staticmethod
    def _create_mock_process(pid: int, name: str, cmdline: list[str]) -> MagicMock:
        """Create a mock psutil.Process with given attributes."""
        mock_proc = MagicMock(spec=psutil.Process)
        mock_proc.pid = pid
        mock_proc.name.return_value = name
        mock_proc.cmdline.return_value = cmdline
        return mock_proc


class TestFindAllDaemonProcessesProjectRootFilter:
    """Tests for project-root scoping of find_all_daemon_processes().

    Regression for the cross-project daemon-kill outage: a container daemon's
    single-process enforcement must NEVER kill a daemon serving a DIFFERENT
    project root, even when PID namespaces are shared and the other project's
    daemon is visible. Scoping the search to our own project root prevents that.
    """

    @staticmethod
    def _proc(pid: int, cmdline: list[str], name: str = "python") -> MagicMock:
        mock_proc = MagicMock(spec=psutil.Process)
        mock_proc.pid = pid
        mock_proc.name.return_value = name
        mock_proc.cmdline.return_value = cmdline
        return mock_proc

    def test_filter_excludes_other_project_daemon_by_its_socket(self, tmp_path: Path) -> None:
        """A daemon naming no root is attributed by the socket it listens on
        (Plan 00466 round 6, Sh-1)."""
        ours_root, other_root = _client_project(tmp_path / "ours"), _client_project(
            tmp_path / "other"
        )
        ours = self._proc(
            pid=100,
            cmdline=[f"{ours_root}/untracked/venv-py311/bin/python", "-m", _MODULE, "start"],
        )
        ours.net_connections.return_value = [_listening(_natural_socket(ours_root))]
        other = self._proc(
            pid=200,
            cmdline=[f"{ours_root}/untracked/venv-py311/bin/python", "-m", _MODULE, "restart"],
        )
        other.net_connections.return_value = [_listening(_natural_socket(other_root))]

        with patch("psutil.process_iter", return_value=[ours, other]):
            result = find_all_daemon_processes(project_root=str(ours_root))

        assert result == [100]

    def test_the_venv_a_daemon_runs_from_attributes_nothing(self, tmp_path: Path) -> None:
        """Round 6 (Sh-1): with no root named, the daemon serves whatever its
        working directory found, so a venv under ``ours`` is no proof: a
        worktree using this checkout's venv was attributed to this checkout,
        and single-daemon enforcement would have terminated it."""
        ours_root = _client_project(tmp_path / "ours")
        stranger = self._proc(
            pid=300,
            cmdline=[
                f"{ours_root}/.claude/hooks-daemon/untracked/venv-py314/bin/python",
                "-m",
                _MODULE,
                "start",
            ],
        )
        stranger.net_connections.return_value = []

        with patch("psutil.process_iter", return_value=[stranger]):
            assert find_all_daemon_processes(project_root=str(ours_root)) == []

    def test_filter_matches_via_project_root_flag(self) -> None:
        """The --project-root cmdline flag identifies the daemon's project."""
        proc = self._proc(
            pid=400,
            cmdline=[
                "python",
                "-m",
                "claude_code_hooks_daemon.daemon.cli",
                "--project-root",
                "/workspace",
                "start",
            ],
        )

        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes(project_root="/workspace") == [400]
            assert find_all_daemon_processes(project_root="/other") == []

    def test_filter_matches_via_project_root_flag_equals_form(self) -> None:
        """The --project-root=PATH form is also recognised."""
        proc = self._proc(
            pid=500,
            cmdline=[
                "python",
                "-m",
                "claude_code_hooks_daemon.daemon.cli",
                "--project-root=/workspace",
                "start",
            ],
        )

        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes(project_root="/workspace") == [500]

    def test_filter_excludes_daemon_with_undeterminable_root(self) -> None:
        """When a daemon's project root cannot be determined, it is NOT killed.

        Conservative default: never terminate a daemon we cannot positively
        attribute to our own project.
        """
        # A real server cmdline (bare "python", no venv path, no --project-root)
        # whose project root cannot be determined → conservatively NOT killed.
        proc = self._proc(
            pid=600,
            cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.cli", "start"],
        )

        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes(project_root="/workspace") == []

    def test_filter_normalizes_trailing_slash(self) -> None:
        """Trailing-slash differences in the project root still match."""
        proc = self._proc(
            pid=700,
            cmdline=["python", "-m", _MODULE, "--project-root", "/workspace", "start"],
        )

        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes(project_root="/workspace/") == [700]

    def test_no_filter_returns_all_daemons(self) -> None:
        """Passing no project_root preserves the legacy system-wide behaviour."""
        ours = self._proc(
            pid=100,
            cmdline=[
                "/workspace/untracked/venv-py311-28fb230b/bin/python",
                "-m",
                "claude_code_hooks_daemon.daemon.cli",
                "start",
            ],
        )
        other = self._proc(
            pid=200,
            cmdline=[
                "/home/user/project/.claude/hooks-daemon/untracked/venv-py314-fefc85e6/bin/python",
                "-m",
                "claude_code_hooks_daemon.daemon.cli",
                "start",
            ],
        )

        with patch("psutil.process_iter", return_value=[ours, other]):
            assert sorted(find_all_daemon_processes()) == [100, 200]


class TestFilterMatchesViaTheDaemonsRecordedEnvironmentVariable:
    """Plan 00466 N59 gate fix: a daemon started with NO ``--project-root``
    flag (the shape ``cmd_start`` actually produces) whose interpreter lives
    in a DIFFERENT project's venv is still correctly attributed, via the
    ``CLAUDE_HOOKS_DAEMON_PROJECT_ROOT`` env var it records at startup --
    exactly what a shared venv serving an isolated test project root needs."""

    @staticmethod
    def _proc(pid: int, cmdline: list[str], environ: dict[str, str]) -> MagicMock:
        mock_proc = MagicMock(spec=psutil.Process)
        mock_proc.pid = pid
        mock_proc.name.return_value = "python"
        mock_proc.cmdline.return_value = cmdline
        mock_proc.environ.return_value = environ
        return mock_proc

    def test_env_var_overrides_the_interpreter_venv_heuristic(self) -> None:
        """The interpreter's own venv path would misattribute this daemon to
        `/workspace`; the recorded env var is what it actually serves."""
        proc = self._proc(
            pid=800,
            cmdline=[
                "/workspace/untracked/venv-py311-28fb230b/bin/python",
                "-m",
                "claude_code_hooks_daemon.daemon.cli",
                "start",
            ],
            environ={"CLAUDE_HOOKS_DAEMON_PROJECT_ROOT": "/tmp/isolated-project"},
        )

        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes(project_root="/tmp/isolated-project") == [800]
            assert find_all_daemon_processes(project_root="/workspace") == []

    def test_explicit_flag_still_wins_over_the_env_var(self) -> None:
        """When the two disagree, the more explicit ``--project-root`` flag
        is authoritative over the recorded env var."""
        proc = self._proc(
            pid=801,
            cmdline=[
                "python",
                "-m",
                "claude_code_hooks_daemon.daemon.cli",
                "--project-root",
                "/from-flag",
                "start",
            ],
            environ={"CLAUDE_HOOKS_DAEMON_PROJECT_ROOT": "/from-env"},
        )

        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes(project_root="/from-flag") == [801]
            assert find_all_daemon_processes(project_root="/from-env") == []

    def test_a_mock_without_a_modelled_environ_is_not_misread(self) -> None:
        """``proc.environ()`` left unconfigured returns a bare ``MagicMock``,
        not a ``dict`` -- must be read as 'no answer', never stringified into
        a bogus path that happens to satisfy nothing (or, worse, something)."""
        proc = MagicMock(spec=psutil.Process)
        proc.pid = 802
        proc.name.return_value = "python"
        proc.cmdline.return_value = [
            "python",
            "-m",
            "claude_code_hooks_daemon.daemon.cli",
            "start",
        ]

        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes(project_root="/anything") == []


class TestDaemonServerMatching:
    """find_all_daemon_processes must match ONLY genuine daemon SERVER
    processes — those launched via ``cli start`` / ``cli restart`` — and never
    transient CLI helpers (status/stop/logs/...) or hook forwarders. Plan 00119.

    Verified in daemon/cli.py: daemonization (os.fork/os.setsid/HooksDaemon/
    asyncio.run) happens only in cmd_start, reachable only from the ``start``
    subcommand and from cmd_restart (the ``restart`` subcommand). os.fork does
    not rewrite argv, so the detached daemon's cmdline carries ``start`` or
    ``restart``.
    """

    _MODULE = "claude_code_hooks_daemon.daemon.cli"

    @staticmethod
    def _proc(pid: int, cmdline: list[str], name: str = "python") -> MagicMock:
        mock_proc = MagicMock(spec=psutil.Process)
        mock_proc.pid = pid
        mock_proc.name.return_value = name
        mock_proc.cmdline.return_value = cmdline
        return mock_proc

    def test_start_launched_daemon_matches(self) -> None:
        proc = self._proc(700, ["python", "-m", self._MODULE, "start"])
        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes() == [700]

    def test_restart_launched_daemon_matches(self) -> None:
        proc = self._proc(701, ["python", "-m", self._MODULE, "restart"])
        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes() == [701]

    def test_start_with_global_project_root_flag_matches(self) -> None:
        proc = self._proc(
            702, ["python", "-m", self._MODULE, "--project-root", "/workspace", "start"]
        )
        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes() == [702]

    def test_transient_cli_helpers_not_matched(self) -> None:
        transient = [
            "status",
            "stop",
            "logs",
            "health",
            "repair",
            "check-truth-changes",
            "generate-docs",
        ]
        procs = [
            self._proc(800 + i, ["python", "-m", self._MODULE, sub])
            for i, sub in enumerate(transient)
        ]
        with patch("psutil.process_iter", return_value=procs):
            assert find_all_daemon_processes() == []

    def test_hook_forwarder_not_matched(self) -> None:
        proc = self._proc(900, ["python", "-m", "claude_code_hooks_daemon.hooks.pre_tool_use"])
        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes() == []

    def test_bare_cli_without_subcommand_not_matched(self) -> None:
        proc = self._proc(901, ["python", "-m", self._MODULE])
        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes() == []

    def test_name_substring_alone_not_matched(self) -> None:
        proc = self._proc(
            902,
            ["python", "my_claude_code_hooks_daemon_wrapper.py"],
            name="claude_code_hooks_daemon",
        )
        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes() == []

    def test_launch_subcommands_allowlist_is_exactly_start_and_restart(self) -> None:
        """Guard: the allowlist is provably complete (only start/restart reach
        cmd_start). If a future subcommand daemonizes, add it here AND update
        this guard — do not silently widen the match."""
        from claude_code_hooks_daemon.daemon.process_verification import (
            _DAEMON_LAUNCH_SUBCOMMANDS,
        )

        assert _DAEMON_LAUNCH_SUBCOMMANDS == ("start", "restart")


class TestDaemonProcessProjectRoot:
    """Tests for daemon_process_project_root(): the proof ``stop`` needs before it signals."""

    def _process(self, cmdline: list[str]) -> MagicMock:
        process = MagicMock(spec=psutil.Process)
        process.cmdline.return_value = cmdline
        return process

    def test_returns_the_root_a_daemon_server_names(self) -> None:
        with patch("psutil.Process", return_value=self._process(_DAEMON_CMDLINE)):
            assert daemon_process_project_root(_UNREAL_PID).root == os.path.realpath(_OWN_ROOT)

    def test_a_non_daemon_process_has_no_root(self) -> None:
        with patch("psutil.Process", return_value=self._process(["/usr/bin/vim", _OWN_ROOT])):
            assert daemon_process_project_root(_UNREAL_PID).root is None

    def test_a_daemon_whose_root_cannot_be_attributed_has_no_root(self) -> None:
        unattributable = ["/usr/bin/python3", "-m", "claude_code_hooks_daemon.daemon.cli", "start"]
        with patch("psutil.Process", return_value=self._process(unattributable)):
            assert daemon_process_project_root(_UNREAL_PID).root is None

    def test_a_vanished_or_inaccessible_process_has_no_root(self) -> None:
        for error in (
            psutil.NoSuchProcess(pid=_UNREAL_PID),
            psutil.AccessDenied(pid=_UNREAL_PID),
            psutil.ZombieProcess(pid=_UNREAL_PID),
        ):
            with patch("psutil.Process", side_effect=error):
                assert daemon_process_project_root(_UNREAL_PID).root is None

    def test_init_our_own_pid_and_non_positive_pids_are_never_attributed(self) -> None:
        """Even a daemon-shaped cmdline cannot make pid 1, 0, a negative pid or
        this process a signal target (Plan 00466 N59: a pid that coerced to 1
        killed the container)."""
        with patch("psutil.Process", return_value=self._process(_DAEMON_CMDLINE)) as proc_cls:
            for pid in (1, 0, -1, os.getpid()):
                assert daemon_process_project_root(pid).root is None
            proc_cls.assert_not_called()

    def test_a_non_int_pid_is_never_attributed(self) -> None:
        """A MagicMock pid coerces to 1 through ``__index__``; it must be refused
        before anything reads it as a number."""
        with patch("psutil.Process", return_value=self._process(_DAEMON_CMDLINE)) as proc_cls:
            assert daemon_process_project_root(MagicMock()).root is None
            assert daemon_process_project_root(True).root is None
            proc_cls.assert_not_called()

    def test_every_unproven_pid_says_why(self) -> None:
        """Plan 00466 N24 review 3 MA5: "no root" is a typed refusal with a
        reason the caller prints, never a bare None."""
        with patch("psutil.Process", side_effect=psutil.AccessDenied(pid=_UNREAL_PID)):
            inaccessible = daemon_process_project_root(_UNREAL_PID)
        with patch("psutil.Process", return_value=self._process(["/usr/bin/vim"])):
            not_a_daemon = daemon_process_project_root(_UNREAL_PID)

        assert inaccessible.root is None
        assert "cannot be inspected" in (inaccessible.refusal or "")
        assert not_a_daemon.root is None
        assert "not a hooks daemon server" in (not_a_daemon.refusal or "")

    def test_the_proof_names_how_the_root_was_attributed(self) -> None:
        with patch("psutil.Process", return_value=self._process(_DAEMON_CMDLINE)):
            proof = daemon_process_project_root(_UNREAL_PID)

        assert proof.refusal is None
        assert proof.source == "its --project-root flag"

    def _daemon_naming_no_root(self, venv_root: Path, *sockets: Path) -> MagicMock:
        process = self._process(
            [f"{venv_root}/untracked/venv-py313/bin/python", "-m", _MODULE, "start"]
        )
        process.net_connections.return_value = [_listening(path) for path in sockets]
        return process

    def test_a_daemon_naming_no_root_serves_the_project_whose_socket_it_listens_on(
        self, tmp_path: Path
    ) -> None:
        """Round 6 (Sh-1): it was attributed to the project owning its venv,
        not to the one its working directory found, which it serves."""
        venv_owner = _client_project(tmp_path / "venv-owner")
        served = _client_project(tmp_path / "served")
        process = self._daemon_naming_no_root(venv_owner, _natural_socket(served))
        with patch("psutil.Process", return_value=process):
            proof = daemon_process_project_root(_UNREAL_PID)

        assert proof.root == os.path.realpath(served)
        assert proof.source == "the socket it listens on"

    def test_a_self_install_is_attributed_by_its_socket(self, tmp_path: Path) -> None:
        served = _self_install_project(tmp_path / "dogfood")
        process = self._daemon_naming_no_root(served, _natural_socket(served, self_install=True))
        with patch("psutil.Process", return_value=process):
            assert daemon_process_project_root(_UNREAL_PID).root == os.path.realpath(served)

    def test_a_socket_in_a_daemon_clone_belongs_to_the_project_holding_it(
        self, tmp_path: Path
    ) -> None:
        """A client install's clone is itself a self-install tree, but a
        daemon never serves it: ``get_project_path`` skips it."""
        served = _client_project(tmp_path / "client")
        clone = served / ".claude" / "hooks-daemon"
        (clone / "src" / "claude_code_hooks_daemon").mkdir(parents=True)
        process = self._daemon_naming_no_root(served, _natural_socket(served))
        with patch("psutil.Process", return_value=process):
            assert daemon_process_project_root(_UNREAL_PID).root == os.path.realpath(served)

    def test_no_projects_socket_attributes_nothing(self, tmp_path: Path) -> None:
        served = _client_project(tmp_path / "served")
        other = _client_project(tmp_path / "other")
        for sockets in (
            (),
            (tmp_path / "elsewhere.sock",),
            (served / ".claude" / "hooks-daemon" / "untracked" / "stray.sock",),
            (_natural_socket(served), _natural_socket(other)),
        ):
            process = self._daemon_naming_no_root(served, *sockets)
            with patch("psutil.Process", return_value=process):
                proof = daemon_process_project_root(_UNREAL_PID)
            assert proof.root is None, sockets
            assert "names no project" in (proof.refusal or ""), sockets

    def test_sockets_that_cannot_be_read_attribute_nothing(self, tmp_path: Path) -> None:
        process = self._daemon_naming_no_root(_client_project(tmp_path / "served"))
        process.net_connections.side_effect = psutil.AccessDenied(pid=_UNREAL_PID)
        with patch("psutil.Process", return_value=process):
            assert daemon_process_project_root(_UNREAL_PID).root is None

    def test_a_daemon_naming_no_root_is_attributed_by_its_recorded_env_var(
        self, tmp_path: Path
    ) -> None:
        """The stop proof and the process scan share one resolution order:
        flag, then the env var main's relaunch records, then the socket."""
        venv_owner = _client_project(tmp_path / "venv-owner")
        served = _client_project(tmp_path / "served")
        process = self._daemon_naming_no_root(venv_owner)
        process.environ.return_value = {PROJECT_ROOT_ENV_VAR: str(served)}
        with patch("psutil.Process", return_value=process):
            proof = daemon_process_project_root(_UNREAL_PID)

        assert proof.root == os.path.realpath(served)
        assert proof.source == f"its {PROJECT_ROOT_ENV_VAR} environment variable"

    def test_the_flag_outranks_the_recorded_env_var(self) -> None:
        process = self._process(_DAEMON_CMDLINE)
        process.environ.return_value = {PROJECT_ROOT_ENV_VAR: "/srv/projects/other"}
        with patch("psutil.Process", return_value=process):
            proof = daemon_process_project_root(_UNREAL_PID)

        assert proof.root == os.path.realpath(_OWN_ROOT)
        assert proof.source == "its --project-root flag"


_OTHER_ROOT = "/srv/projects/other"

# Arguments after the cli module that its parser accepts, and the root each
# names. ``bin/hooks-daemon`` puts its own root first and the caller's after
# it, and argparse keeps the last (Plan 00466 N203).
_ACCEPTED_LAUNCHES: list[tuple[list[str], str | None]] = [
    (["--project-root", _OWN_ROOT, "start"], _OWN_ROOT),
    (["--project-root", _OWN_ROOT, "--project-root", _OTHER_ROOT, "start"], _OTHER_ROOT),
    (["--project-root", _OTHER_ROOT, "--project-root", _OWN_ROOT, "restart"], _OWN_ROOT),
    (["--project-root", _OWN_ROOT, "--project-r", _OTHER_ROOT, "start"], _OTHER_ROOT),
    (["--project-root", _OWN_ROOT, f"--pr={_OTHER_ROOT}", "start"], _OTHER_ROOT),
    ([f"--project-root={_OTHER_ROOT}", "--project-root", _OWN_ROOT, "start"], _OWN_ROOT),
    (
        ["--pid-file", "/run/d.pid", "--project-root", _OWN_ROOT, "--socket", "/run/d.s", "start"],
        _OWN_ROOT,
    ),
    (["--project-root", _OWN_ROOT, "--socket", _OTHER_ROOT, "start"], _OWN_ROOT),
    (["--socket", "/run/d.sock", "start"], None),
]

# Arguments its parser rejects, so no running daemon was launched with them.
_REJECTED_LAUNCHES: list[list[str]] = [
    ["--project-root", _OWN_ROOT, "--p", _OTHER_ROOT, "start"],
    ["--project-root", _OWN_ROOT, "start", "--project-root", _OTHER_ROOT],
    ["--project-root", _OWN_ROOT, "start", "extra"],
    ["--project-root", "start"],
    ["--project-root", _OWN_ROOT, "-h", "start"],
    ["--project-root", _OWN_ROOT, "--unknown", "start"],
]


class TestTheFlagIsReadAsTheDaemonsOwnParserReadsIt:
    """Plan 00466 N203: the first ``--project-root`` was taken, where
    argparse keeps the last, so a daemon launched as ``bin/hooks-daemon
    --project-root B start`` from A's wrapper serves B and was attributed to
    A. A's single-daemon enforcement would then have stopped B's daemon."""

    def _proof_for(self, arguments: list[str], environ: dict[str, str] | None = None) -> RootProof:
        process = MagicMock(spec=psutil.Process)
        process.cmdline.return_value = ["/usr/bin/python3", "-m", _MODULE, *arguments]
        process.environ.return_value = environ or {}
        process.net_connections.return_value = []
        with patch("psutil.Process", return_value=process):
            return daemon_process_project_root(_UNREAL_PID)

    def test_a_second_root_is_the_one_the_daemon_serves(self) -> None:
        proof = self._proof_for(
            ["--project-root", _OWN_ROOT, "--project-root", _OTHER_ROOT, "start"]
        )

        assert proof.root == os.path.realpath(_OTHER_ROOT)

    def test_every_accepted_launch_is_attributed_to_the_root_its_parser_kept(self) -> None:
        for arguments, served in _ACCEPTED_LAUNCHES:
            proof = self._proof_for(arguments)
            expected = None if served is None else os.path.realpath(served)
            assert proof.root == expected, arguments

    def test_a_launch_its_parser_rejects_proves_nothing_however_else_it_is_attributed(
        self,
    ) -> None:
        """Its environment names our root too, so only the refusal keeps it
        from being attributed to us."""
        for arguments in _REJECTED_LAUNCHES:
            proof = self._proof_for(arguments, {PROJECT_ROOT_ENV_VAR: _OWN_ROOT})
            assert proof.root is None, arguments
            assert "parser" in (proof.refusal or ""), arguments

    def test_a_relative_root_names_a_directory_the_daemon_has_left(self) -> None:
        proof = self._proof_for(["--project-root", "projects/ours", "start"])

        assert proof.root is None
        assert "relative" in (proof.refusal or "")

    @pytest.mark.parametrize(
        "root",
        ["/var/run/../workspace", f"{_OWN_ROOT}/../ours", f"{_OWN_ROOT}/.."],
    )
    def test_a_root_that_is_not_its_own_normal_form_proves_nothing(self, root: str) -> None:
        """Review 8, S8-1 (N225): ``cmd_start`` serves ``Path.resolve()``,
        which follows ``/var/run`` to ``/run`` before it meets ``..``, while
        the proof collapsed ``..`` first. ``/var/run/../workspace`` served
        ``/workspace`` and was attributed to ``/var/workspace``. Its
        environment names our root too, so only the refusal keeps it from
        being attributed."""
        proof = self._proof_for(
            ["--project-root", "/wrapperroot", "--project-root", root, "start"],
            {PROJECT_ROOT_ENV_VAR: _OWN_ROOT},
        )

        assert proof.root is None
        assert "normal form" in (proof.refusal or ""), proof.refusal

    @pytest.mark.parametrize(
        "root", [f"{_OWN_ROOT}/", "/srv//projects/ours", "/srv/./projects/ours"]
    )
    def test_a_root_its_parser_normalises_is_attributed_as_parsed(self, root: str) -> None:
        """Its parser reads the root as a ``Path``, which drops these, so
        they name the root ``cmd_start`` serves."""
        proof = self._proof_for(["--project-root", root, "start"])

        assert proof.root == os.path.realpath(_OWN_ROOT)

    def test_the_reading_agrees_with_the_cli_parser_itself(self) -> None:
        """The same arguments through ``cli``'s own parser keep the same root,
        or launch no daemon: it rejects them, or reads no subcommand."""
        from claude_code_hooks_daemon.daemon.cli import build_parser

        for arguments, served in _ACCEPTED_LAUNCHES:
            kept = build_parser().parse_args(arguments).global_project_root
            assert (None if kept is None else str(kept)) == served, arguments
        for arguments in _REJECTED_LAUNCHES:
            with patch("sys.stdout"), patch("sys.stderr"):
                try:
                    command = build_parser().parse_args(arguments).command
                except SystemExit:
                    command = None
            assert command is None, arguments


class TestADaemonsRootTextIsNeverResolved:
    """Review 9, DR-1 (coordinator ruling): the daemon's normalised root text
    is matched with the caller's root as given and as resolved; the
    daemon's own text is never resolved."""

    def test_the_same_link_on_both_sides_names_the_project(self, tmp_path: Path) -> None:
        (tmp_path / "real" / "project").mkdir(parents=True)
        (tmp_path / "link").symlink_to(tmp_path / "real")
        linked = tmp_path / "link" / "project"

        assert root_names_project(str(linked), linked)

    def test_the_real_root_names_a_caller_naming_it_through_a_link(self, tmp_path: Path) -> None:
        (tmp_path / "real" / "project").mkdir(parents=True)
        (tmp_path / "link").symlink_to(tmp_path / "real")

        assert root_names_project(str(tmp_path / "real" / "project"), tmp_path / "link" / "project")

    def test_a_link_since_re_pointed_names_nothing(self, tmp_path: Path) -> None:
        (tmp_path / "old" / "project").mkdir(parents=True)
        (tmp_path / "new" / "project").mkdir(parents=True)
        (tmp_path / "link").symlink_to(tmp_path / "new")

        assert not root_names_project(
            str(tmp_path / "link" / "project"), tmp_path / "new" / "project"
        )

    def test_the_callers_logical_root_names_a_daemon_started_through_it(
        self, tmp_path: Path
    ) -> None:
        """Round 9b: ``bin/hooks-daemon`` names its root resolved, and hands
        over the link it was invoked through, which is how a daemon an older
        ``init.sh`` started names it."""
        (tmp_path / "real" / "project").mkdir(parents=True)
        (tmp_path / "link").symlink_to(tmp_path / "real")
        linked = tmp_path / "link" / "project"

        assert root_names_project(
            str(linked), tmp_path / "real" / "project", logical_root=str(linked)
        )

    def test_a_logical_root_naming_another_tree_is_no_candidate(self, tmp_path: Path) -> None:
        """A logical root counts only as a spelling of the caller's own
        tree: it resolves to where the caller's root does."""
        (tmp_path / "project").mkdir()
        (tmp_path / "other").mkdir()
        other = str(tmp_path / "other")

        assert not root_names_project(other, tmp_path / "project", logical_root=other)

    @pytest.mark.parametrize("spelling", ["relative/project", "{root}/link/../link/project"])
    def test_a_logical_root_not_in_normal_form_is_no_candidate(
        self, tmp_path: Path, spelling: str
    ) -> None:
        (tmp_path / "real" / "project").mkdir(parents=True)
        (tmp_path / "link").symlink_to(tmp_path / "real")
        logical = spelling.format(root=tmp_path)

        assert not root_names_project(logical, tmp_path / "real" / "project", logical_root=logical)

    def test_the_proof_carries_the_daemons_own_text(self, tmp_path: Path) -> None:
        (tmp_path / "real" / "project").mkdir(parents=True)
        (tmp_path / "link").symlink_to(tmp_path / "real")
        linked = str(tmp_path / "link" / "project")
        process = MagicMock(spec=psutil.Process)
        process.cmdline.return_value = ["python", "-m", _MODULE, "--project-root", linked, "start"]

        with patch("psutil.Process", return_value=process):
            assert daemon_process_project_root(_UNREAL_PID).root == linked


class TestIsThisUsersProcess:
    """Plan 00466 round 6 (P5-1, Sh-G): ownership is the owner's uid, never
    permission to signal, which root holds over every process."""

    def test_a_process_this_user_owns_is(self) -> None:
        assert is_this_users_process(os.getpid())

    def test_another_uids_process_is_not(self) -> None:
        """Faked by changing the uid it is compared with: launching a process
        as another uid would need root."""
        with patch("os.geteuid", return_value=os.geteuid() + 4242):
            assert not is_this_users_process(os.getpid())

    def test_a_setuid_process_is_not(self) -> None:
        """Real and effective uid must both be this user's."""
        uids = SimpleNamespace(real=os.geteuid(), effective=os.geteuid() + 1, saved=0)
        process = MagicMock(spec=psutil.Process)
        process.uids.return_value = uids
        with patch("psutil.Process", return_value=process):
            assert not is_this_users_process(_UNREAL_PID)

    def test_a_process_that_cannot_be_read_is_not(self) -> None:
        for error in (psutil.NoSuchProcess(pid=_UNREAL_PID), psutil.AccessDenied(pid=_UNREAL_PID)):
            with patch("psutil.Process", side_effect=error):
                assert not is_this_users_process(_UNREAL_PID)

    def test_what_is_no_pid_is_never_read(self) -> None:
        with patch("psutil.Process") as process:
            for pid in (0, 1, -1, True, MagicMock()):
                assert not is_this_users_process(pid)
        process.assert_not_called()
