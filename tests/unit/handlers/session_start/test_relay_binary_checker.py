"""Plan 00529 Task 2a (Plan 00474 N523): a configured relay whose binary is unusable.

With ``daemon.transport.relay_enabled: true`` and the relay binary missing or not
executable, relay-eligible hooks run on the fallback transport and nothing said
so outside ``transport on``. This SessionStart advisory says it, naming the path
and the fix, and says nothing when the relay is disabled or the binary is usable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.daemon.paths import get_untracked_dir
from claude_code_hooks_daemon.handlers.session_start.relay_binary_checker import (
    RelayBinaryCheckerHandler,
)
from claude_code_hooks_daemon.install.relay_deploy import resolve_relay_binary_path
from claude_code_hooks_daemon.install.relay_repair import REPAIR_MODULE, REPAIR_STATE_DIR_NAME


def _project(root: Path, transport_yaml: str) -> Path:
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "hooks-daemon.yaml").write_text(
        'version: "1.0"\ndaemon:\n  transport:\n' + transport_yaml
    )
    return root


class _Spawner:
    """Records each detached repair spawn instead of starting a build."""

    def __init__(self, error: OSError | None = None) -> None:
        self.calls: list[list[str]] = []
        self.error = error

    def __call__(self, argv: list[str], log: Path) -> int:
        self.calls.append(argv)
        if self.error is not None:
            raise self.error
        return 4242


def _handler(root: Path, spawner: _Spawner | None = None) -> RelayBinaryCheckerHandler:
    handler = RelayBinaryCheckerHandler()
    handler.workspace_root = root
    handler.spawn_repair = spawner if spawner is not None else _Spawner()
    return handler


def _session(**overrides: Any) -> dict[str, Any]:
    return {"hook_event_name": "SessionStart", "source": "startup", **overrides}


def _binary(path: Path, mode: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x7fELF")
    path.chmod(mode)
    return path


class TestRelayBinaryChecker:
    def test_matches_every_session_start_including_resume(self, tmp_path: Path) -> None:
        handler = _handler(tmp_path)

        assert handler.matches(_session()) is True
        assert handler.matches(_session(source="resume")) is True

    def test_silent_when_the_relay_is_disabled(self, tmp_path: Path) -> None:
        root = _project(tmp_path, "    relay_enabled: false\n")

        result = _handler(root).handle(_session())

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_silent_when_there_is_no_config_file(self, tmp_path: Path) -> None:
        assert _handler(tmp_path).handle(_session()).context == []

    def test_reports_a_missing_binary_with_the_path_and_the_fix(self, tmp_path: Path) -> None:
        root = _project(tmp_path, "    relay_enabled: true\n")
        transport = Config.load_or_default(root / ".claude" / "hooks-daemon.yaml").daemon.transport
        expected = resolve_relay_binary_path(root, transport)

        result = _handler(root).handle(_session())

        text = "\n".join(result.context)
        assert result.decision == Decision.ALLOW
        assert str(expected) in text
        assert "missing or cannot run" in text
        assert "fallback transport" in text
        assert "transport on" in text

    def test_reports_a_binary_that_is_not_executable(self, tmp_path: Path) -> None:
        binary = _binary(tmp_path / "relay" / "hooks-relay", 0o644)
        root = _project(tmp_path, f"    relay_enabled: true\n    relay_binary: {binary}\n")

        text = "\n".join(_handler(root).handle(_session()).context)

        assert str(binary) in text
        assert "transport on" in text

    def test_silent_when_the_binary_is_present_and_executable(self, tmp_path: Path) -> None:
        binary = _binary(tmp_path / "relay" / "hooks-relay", 0o755)
        root = _project(tmp_path, f"    relay_enabled: true\n    relay_binary: {binary}\n")

        assert _handler(root).handle(_session()).context == []

    def test_an_unloadable_config_is_reported_not_swallowed(self, tmp_path: Path) -> None:
        root = _project(tmp_path, "    relay_enabled: [not, a, bool]\n")

        text = "\n".join(_handler(root).handle(_session()).context)

        assert "could not read daemon.transport" in text
        assert str(root / ".claude" / "hooks-daemon.yaml") in text

    def test_silent_when_the_project_root_is_unknown(self) -> None:
        handler = RelayBinaryCheckerHandler()

        with patch(
            "claude_code_hooks_daemon.handlers.session_start.relay_binary_checker."
            "ProjectContext.is_initialized",
            return_value=False,
        ):
            assert handler.handle(_session()).context == []

    def test_is_a_non_terminal_advisory(self) -> None:
        handler = RelayBinaryCheckerHandler()

        assert handler.terminal is False
        assert handler.get_claude_md() is None

    def test_acceptance_description_names_the_background_repair(self) -> None:
        (case,) = RelayBinaryCheckerHandler().get_acceptance_tests()

        assert "background" in case.description

    def test_acceptance_test_is_a_context_case(self) -> None:
        (case,) = RelayBinaryCheckerHandler().get_acceptance_tests()

        assert case.expected_decision == Decision.ALLOW
        assert case.expected_message_patterns


class TestBackgroundRepair:
    """Ruling task 4: an unusable binary starts a detached repair, once per cause."""

    def _enabled(self, tmp_path: Path) -> Path:
        return _project(tmp_path, "    relay_enabled: true\n")

    def test_an_unusable_binary_starts_the_repair_module_detached(self, tmp_path: Path) -> None:
        spawner = _Spawner()

        text = "\n".join(_handler(self._enabled(tmp_path), spawner).handle(_session()).context)

        ((argv,),) = [spawner.calls]
        assert argv[1:3] == ["-m", REPAIR_MODULE]
        assert "repair started in the background" in text
        assert "if the next session still warns" in text
        assert "transport on" in text

    def test_the_same_cause_is_not_started_twice(self, tmp_path: Path) -> None:
        root = self._enabled(tmp_path)
        spawner = _Spawner()
        _handler(root, spawner).handle(_session())

        text = "\n".join(_handler(root, spawner).handle(_session()).context)

        assert len(spawner.calls) == 1
        assert "repair is running in the background" in text

    def test_a_usable_binary_starts_nothing(self, tmp_path: Path) -> None:
        binary = _binary(tmp_path / "relay" / "hooks-relay", 0o755)
        root = _project(tmp_path, f"    relay_enabled: true\n    relay_binary: {binary}\n")
        spawner = _Spawner()

        _handler(root, spawner).handle(_session())

        assert spawner.calls == []

    def test_a_disabled_relay_starts_nothing(self, tmp_path: Path) -> None:
        root = _project(tmp_path, "    relay_enabled: false\n")
        spawner = _Spawner()

        _handler(root, spawner).handle(_session())

        assert spawner.calls == []

    def test_a_spawn_failure_is_reported_loudly(self, tmp_path: Path) -> None:
        spawner = _Spawner(error=OSError(13, "Permission denied"))

        result = _handler(self._enabled(tmp_path), spawner).handle(_session())

        text = "\n".join(result.context)
        assert result.decision == Decision.ALLOW
        assert "could not be started" in text
        assert "Permission denied" in text
        assert "transport on" in text

    def test_a_failed_repair_is_reported_at_every_session_start(self, tmp_path: Path) -> None:
        root = self._enabled(tmp_path)
        handler = _handler(root)
        handler.handle(_session())
        (state,) = (get_untracked_dir(root) / REPAIR_STATE_DIR_NAME).glob("*.state")
        state.write_text("status=failed\ndetail=relay-binary: no rustc on PATH\n")

        for _ in range(2):
            text = "\n".join(handler.handle(_session()).context)
            assert "repair FAILED" in text
            assert "no rustc on PATH" in text
            assert str(state.with_suffix(".log")) in text
            assert "transport on" in text

    def test_a_repair_that_recorded_success_yet_the_binary_is_unusable_says_so(
        self, tmp_path: Path
    ) -> None:
        root = self._enabled(tmp_path)
        handler = _handler(root)
        handler.handle(_session())
        (state,) = (get_untracked_dir(root) / REPAIR_STATE_DIR_NAME).glob("*.state")
        state.write_text("status=synced\ndetail=provisioned\n")

        text = "\n".join(handler.handle(_session()).context)

        assert "recorded success" in text
        assert "transport on" in text
