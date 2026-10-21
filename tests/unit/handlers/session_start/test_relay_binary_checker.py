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
from claude_code_hooks_daemon.handlers.session_start.relay_binary_checker import (
    RelayBinaryCheckerHandler,
)
from claude_code_hooks_daemon.install.relay_deploy import resolve_relay_binary_path


def _project(root: Path, transport_yaml: str) -> Path:
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "hooks-daemon.yaml").write_text(
        'version: "1.0"\ndaemon:\n  transport:\n' + transport_yaml
    )
    return root


def _handler(root: Path) -> RelayBinaryCheckerHandler:
    handler = RelayBinaryCheckerHandler()
    handler.workspace_root = root
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
        assert "missing or not executable" in text
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

    def test_acceptance_test_is_a_context_case(self) -> None:
        (case,) = RelayBinaryCheckerHandler().get_acceptance_tests()

        assert case.expected_decision == Decision.ALLOW
        assert case.expected_message_patterns
