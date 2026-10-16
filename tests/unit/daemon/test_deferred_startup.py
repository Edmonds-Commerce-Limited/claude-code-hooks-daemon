"""The daemon binds its socket before the non-essential start-up work.

Plan 00495 Task 2.5. The CLAUDE.md regeneration, the two config-driven asset
syncs and the guard-index pre-warm change nothing a request is judged by, so
the serving daemon runs them after the socket is bound. A request that arrives
while they run is answered exactly as it would be afterwards.
"""

import asyncio
import json
import subprocess
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from tests.daemon._start_wait import wait_for_daemon_started

from claude_code_hooks_daemon.config.models import Config, DaemonConfig, LogLevel
from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.daemon.cli import _build_initialised_controller
from claude_code_hooks_daemon.daemon.controller import DaemonController
from claude_code_hooks_daemon.daemon.server import HooksDaemon

VALID_CONFIG = (
    "version: '2.0'\ndaemon:\n  idle_timeout_seconds: 600\n  log_level: INFO\nhandlers: {}\n"
)

DESTRUCTIVE_GIT_REQUEST = {
    "event": "PreToolUse",
    "hook_input": {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "git reset --hard HEAD~3"},
    },
}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A throwaway git project with a minimal valid daemon config."""
    config_dir = tmp_path / ".claude"
    config_dir.mkdir()
    (config_dir / "hooks-daemon.yaml").write_text(VALID_CONFIG, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:example/example.git"],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


@pytest.fixture
def short_dir() -> Iterator[Path]:
    """A short directory, so the socket path stays under the AF_UNIX limit."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def _initialise(project: Path, *, defer: bool) -> tuple[DaemonController, dict[str, MagicMock]]:
    """Initialise a controller with the three deferrable steps replaced by spies."""
    spies = {"inject": MagicMock(), "agents": MagicMock(), "rules": MagicMock()}
    injector = MagicMock()
    injector.return_value.inject = spies["inject"]
    controller = DaemonController()
    with (
        patch("claude_code_hooks_daemon.daemon.controller.ClaudeMdInjector", injector),
        patch.object(DaemonController, "prewarm_indexes"),
        patch.object(DaemonController, "_sync_agent_assets", spies["agents"]),
        patch.object(DaemonController, "_sync_directory_role_rules", spies["rules"]),
    ):
        controller.initialise(
            handler_config={},
            workspace_root=project,
            defer_nonessential_startup=defer,
        )
        if defer:
            for spy in spies.values():
                assert spy.call_count == 0, "a deferred step ran inside initialise"
            controller.run_deferred_startup()
    return controller, spies


class TestControllerDefersNonessentialStartup:
    """``initialise(defer_nonessential_startup=True)`` holds three steps back."""

    def test_default_runs_every_step_inside_initialise(self, project: Path) -> None:
        """Without the flag, behaviour is unchanged: the steps run in initialise."""
        _controller, spies = _initialise(project, defer=False)
        assert [spy.call_count for spy in spies.values()] == [1, 1, 1]

    def test_deferred_steps_run_when_asked(self, project: Path) -> None:
        """Held back by initialise, each step runs exactly once afterwards."""
        _controller, spies = _initialise(project, defer=True)
        assert [spy.call_count for spy in spies.values()] == [1, 1, 1]

    def test_config_validation_is_not_deferred(self, project: Path) -> None:
        """Degraded mode changes how requests are answered, so it is set before serving."""
        (project / ".claude" / "hooks-daemon.yaml").write_text(
            "version: '2.0'\ndaemon:\n  idle_timeout_seconds: 600\n", encoding="utf-8"
        )
        controller = DaemonController()
        with patch("claude_code_hooks_daemon.daemon.controller.ClaudeMdInjector"):
            controller.initialise(
                handler_config={}, workspace_root=project, defer_nonessential_startup=True
            )
        assert controller.is_degraded is True

    def test_running_the_deferred_work_twice_does_it_once(self, project: Path) -> None:
        """A second call finds nothing left to do."""
        controller, spies = _initialise(project, defer=True)
        controller.run_deferred_startup()
        assert [spy.call_count for spy in spies.values()] == [1, 1, 1]

    def test_deferred_work_includes_the_index_prewarm(self, project: Path) -> None:
        """The pre-warm that used to run before binding runs with the deferred work."""
        controller = DaemonController()
        with (
            patch("claude_code_hooks_daemon.daemon.controller.ClaudeMdInjector"),
            patch.object(DaemonController, "prewarm_indexes") as prewarm,
        ):
            controller.initialise(
                handler_config={}, workspace_root=project, defer_nonessential_startup=True
            )
            prewarm.assert_not_called()
            controller.run_deferred_startup()
        prewarm.assert_called_once_with()

    def test_a_failing_step_does_not_stop_the_others(
        self, project: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """One deferred step raising is logged and the remaining steps still run."""
        controller = DaemonController()
        agents, rules = MagicMock(), MagicMock()
        injector = MagicMock()
        injector.return_value.inject.side_effect = RuntimeError("injector broke")
        with (
            patch("claude_code_hooks_daemon.daemon.controller.ClaudeMdInjector", injector),
            patch.object(DaemonController, "_sync_agent_assets", agents),
            patch.object(DaemonController, "_sync_directory_role_rules", rules),
            patch.object(DaemonController, "prewarm_indexes"),
            caplog.at_level("ERROR"),
        ):
            controller.initialise(
                handler_config={}, workspace_root=project, defer_nonessential_startup=True
            )
            controller.run_deferred_startup()
        assert agents.call_count == 1
        assert rules.call_count == 1
        assert "injector broke" in caplog.text


class TestBuilderPassesTheFlag:
    """``_build_initialised_controller`` threads the flag to ``initialise``."""

    @pytest.mark.parametrize("defer", [True, False])
    def test_flag_reaches_initialise(self, defer: bool) -> None:
        """The builder hands its argument on unchanged, defaulting to False."""
        captured: dict[str, Any] = {}

        def fake_initialise(self: DaemonController, *args: Any, **kwargs: Any) -> None:
            captured.update(kwargs)

        with patch.object(DaemonController, "initialise", fake_initialise):
            if defer:
                _build_initialised_controller(
                    Config(), Path("/tmp/not-needed"), defer_nonessential_startup=True
                )
            else:
                _build_initialised_controller(Config(), Path("/tmp/not-needed"))
        assert captured["defer_nonessential_startup"] is defer


async def _round_trip(socket_path: Path, request: dict[str, Any]) -> dict[str, Any]:
    """One newline-framed request on the daemon's socket, and its response."""
    reader, writer = await asyncio.open_unix_connection(str(socket_path))
    writer.write(json.dumps(request).encode() + b"\n")
    await writer.drain()
    line = await reader.readline()
    writer.close()
    await writer.wait_closed()
    return dict(json.loads(line.decode()))


def _daemon_config(directory: Path) -> DaemonConfig:
    return DaemonConfig(
        socket_path=directory / "d.sock",
        pid_file_path=directory / "d.pid",
        idle_timeout_seconds=600,
        log_level=LogLevel.DEBUG,
    )


class TestRequestsDuringDeferredStartup:
    """The socket answers before the deferred work finishes, and answers correctly."""

    @pytest.mark.anyio
    async def test_request_is_answered_correctly_while_deferred_work_is_blocked(
        self, project: Path, short_dir: Path
    ) -> None:
        """A destructive command is denied, as after start-up, with the deferred work still running."""
        controller = _build_initialised_controller(
            Config.find_and_load(project), project, defer_nonessential_startup=True
        )
        entered, release = threading.Event(), threading.Event()

        def blocked_deferred_work() -> None:
            entered.set()
            assert release.wait(timeout=30), "the test never released the deferred work"

        daemon = HooksDaemon(
            _daemon_config(short_dir), controller, deferred_startup=blocked_deferred_work
        )
        server_task = asyncio.create_task(daemon.start())
        try:
            await wait_for_daemon_started(daemon, server_task, timeout=Timeout.SOCKET_CONNECT)
            await asyncio.to_thread(entered.wait, 30)
            assert not daemon.deferred_startup_done.is_set()

            during = await _round_trip(short_dir / "d.sock", DESTRUCTIVE_GIT_REQUEST)

            assert not daemon.deferred_startup_done.is_set()
            release.set()
            await asyncio.wait_for(daemon.deferred_startup_done.wait(), timeout=30)
            after = await _round_trip(short_dir / "d.sock", DESTRUCTIVE_GIT_REQUEST)
        finally:
            release.set()
            await daemon.shutdown()
            await server_task

        decision = during["hookSpecificOutput"]["permissionDecision"]
        assert decision == "deny"
        assert during == after

    @pytest.mark.anyio
    async def test_deferred_work_starts_only_after_the_socket_is_bound(
        self, short_dir: Path
    ) -> None:
        """When the deferred work begins, the daemon is already published as serving."""
        observed: list[bool] = []
        done = threading.Event()

        def deferred_work() -> None:
            observed.append((short_dir / "d.sock").exists())
            done.set()

        daemon = HooksDaemon(_daemon_config(short_dir), MagicMock(), deferred_startup=deferred_work)
        server_task = asyncio.create_task(daemon.start())
        try:
            await wait_for_daemon_started(daemon, server_task, timeout=Timeout.SOCKET_CONNECT)
            await asyncio.wait_for(daemon.deferred_startup_done.wait(), timeout=30)
        finally:
            await daemon.shutdown()
            await server_task
        assert observed == [True]

    @pytest.mark.anyio
    async def test_failing_deferred_work_leaves_the_daemon_serving(self, short_dir: Path) -> None:
        """An exception in the deferred work is logged; the daemon keeps serving."""
        failure = RuntimeError("deferred work failed")

        def failing_work() -> None:
            raise failure

        daemon = HooksDaemon(_daemon_config(short_dir), MagicMock(), deferred_startup=failing_work)
        server_task = asyncio.create_task(daemon.start())
        try:
            with patch("claude_code_hooks_daemon.daemon.server.log_and_continue") as logged:
                await wait_for_daemon_started(daemon, server_task, timeout=Timeout.SOCKET_CONNECT)
                await asyncio.wait_for(daemon.deferred_startup_done.wait(), timeout=30)
            assert not server_task.done()
        finally:
            await daemon.shutdown()
            await server_task
        assert logged.call_args.args[1] is failure

    @pytest.mark.anyio
    async def test_no_deferred_work_still_sets_the_done_event(self, short_dir: Path) -> None:
        """A daemon given nothing to defer reports the deferred stage as finished."""
        daemon = HooksDaemon(_daemon_config(short_dir), MagicMock())
        server_task = asyncio.create_task(daemon.start())
        try:
            await wait_for_daemon_started(daemon, server_task, timeout=Timeout.SOCKET_CONNECT)
            await asyncio.wait_for(daemon.deferred_startup_done.wait(), timeout=30)
        finally:
            await daemon.shutdown()
            await server_task
