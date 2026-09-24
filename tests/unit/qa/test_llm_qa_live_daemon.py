"""A QA tool that probes the live daemon gets one, however long the run (00422 N27).

The daemon stops itself after ``idle_timeout_seconds`` with no hook traffic,
and every real hook starts it again on demand. A worktree's daemon receives no
traffic at all while its session's hooks go to the main checkout's daemon, so
it idled out part-way through an ~18-minute ``llm_qa.py all`` and
``smoke_test`` failed "Daemon not running". The cure is the one the hooks
already use: start the daemon when a consumer needs it, instead of assuming a
restart made at the start of the run is still alive at the end of it.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load_llm_qa() -> Any:
    """Import `scripts/qa/llm_qa.py`, which is a script rather than a module."""
    module_path = PROJECT_ROOT / "scripts" / "qa" / "llm_qa.py"
    spec = importlib.util.spec_from_file_location("llm_qa_live_daemon_under_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


llm_qa = _load_llm_qa()

# Text in a tool's script that means it talks to the running daemon: the hook
# forwarders, the socket, or the freshness query against the live process.
_LIVE_DAEMON_MARKERS = (".claude/hooks/", "daemon-*.sock", "check-source-fresh")


class _FakeDaemonCli:
    """Stands in for ``bin/hooks-daemon``, recording each subcommand asked of it."""

    def __init__(self, *, running: bool, start_returncode: int = 0) -> None:
        self.running = running
        self.start_returncode = start_returncode
        self.calls: list[str] = []

    def __call__(self, subcommand: str) -> subprocess.CompletedProcess[str]:
        self.calls.append(subcommand)
        if subcommand == "status":
            return subprocess.CompletedProcess([subcommand], 0 if self.running else 1, "", "")
        if subcommand == "start":
            return subprocess.CompletedProcess(
                [subcommand], self.start_returncode, "", "ERROR: fork failed"
            )
        raise AssertionError(f"unexpected daemon subcommand: {subcommand}")


class TestTheRegistryDeclaresEveryLiveDaemonConsumer:
    def test_smoke_test_and_tests_are_the_live_daemon_consumers(self) -> None:
        """``tests`` runs tests/acceptance, whose daemon fixtures skip without a
        socket, and a skip in a declared release gate is a failure."""
        consumers = {name for name, cfg in llm_qa.TOOL_REGISTRY.items() if cfg.live_daemon}

        assert consumers == {"smoke_test", "tests"}

    @pytest.mark.parametrize("name", sorted(llm_qa.TOOL_REGISTRY))
    def test_a_script_that_reaches_the_daemon_is_declared(self, name: str) -> None:
        config = llm_qa.TOOL_REGISTRY[name]
        if name == "tests":
            pytest.skip("tests reaches the daemon through tests/acceptance, not its script")
        script = next(Path(part) for part in config.command if part.endswith((".sh", ".py")))
        text = script.read_text(encoding="utf-8")

        reaches_daemon = any(marker in text for marker in _LIVE_DAEMON_MARKERS)

        assert config.live_daemon is reaches_daemon, (
            f"{script.name} {'reaches' if reaches_daemon else 'does not reach'} the live "
            f"daemon, so TOOL_REGISTRY[{name!r}].live_daemon must be {reaches_daemon}"
        )


class TestEnsureLiveDaemon:
    def test_a_running_daemon_is_left_alone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cli = _FakeDaemonCli(running=True)
        monkeypatch.setattr(llm_qa, "_daemon_cli", cli)

        note = llm_qa.ensure_live_daemon("smoke_test")

        assert note is None
        assert cli.calls == ["status"]

    def test_an_idled_out_daemon_is_started_and_the_run_says_so(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cli = _FakeDaemonCli(running=False)
        monkeypatch.setattr(llm_qa, "_daemon_cli", cli)

        note = llm_qa.ensure_live_daemon("smoke_test")

        assert cli.calls == ["status", "start"]
        assert note is not None
        assert "smoke_test" in note
        assert "idle_timeout_seconds" in note

    def test_a_failed_start_is_reported_with_its_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cli = _FakeDaemonCli(running=False, start_returncode=1)
        monkeypatch.setattr(llm_qa, "_daemon_cli", cli)

        note = llm_qa.ensure_live_daemon("smoke_test")

        assert note is not None
        assert "ERROR: fork failed" in note
        assert "exit 1" in note

    def test_a_hung_cli_is_reported_not_raised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _hangs(subcommand: str) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired([subcommand], llm_qa.DAEMON_CLI_TIMEOUT_SECONDS)

        monkeypatch.setattr(llm_qa, "_daemon_cli", _hangs)

        note = llm_qa.ensure_live_daemon("tests")

        assert note is not None
        assert "did not answer" in note

    def test_the_cli_is_this_checkouts_own_wrapper(self) -> None:
        """A worktree must start ITS daemon, never the main checkout's."""
        assert llm_qa.DAEMON_CLI == PROJECT_ROOT / "bin" / "hooks-daemon"
        assert os.access(llm_qa.DAEMON_CLI, os.X_OK)


class TestTheRunEnsuresTheDaemonBeforeEachConsumer:
    @pytest.fixture
    def ensured(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        calls: list[str] = []

        def _record(tool: str) -> str:
            calls.append(tool)
            return f"   note for {tool}"

        monkeypatch.setattr(llm_qa, "ensure_live_daemon", _record)
        monkeypatch.setattr(llm_qa, "run_tool", lambda name: 0)
        monkeypatch.setattr(llm_qa, "summarize_tool", lambda name, exit_code=None: (True, ""))
        return calls

    def test_only_consumers_are_preceded_by_the_ensure(
        self, ensured: list[str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        llm_qa._run_tools(["format", "tests", "lint", "smoke_test"], read_only=False)

        assert ensured == ["tests", "smoke_test"]
        assert "note for smoke_test" in capsys.readouterr().out

    def test_a_read_only_run_starts_nothing(self, ensured: list[str]) -> None:
        llm_qa._run_tools(["tests", "smoke_test"], read_only=True)

        assert ensured == []
