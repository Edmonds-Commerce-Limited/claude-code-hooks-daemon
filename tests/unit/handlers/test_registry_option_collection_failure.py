"""A handler whose options cannot be collected is loud, not silent.

Plan 00466 N19. ``register_all`` pass 1 caught every exception from option
collection and logged it at debug level. During N14 a shadowed local made
that path raise for EVERY handler, so every handler ran on its defaults with
nothing at a visible log level. A failure is now logged at error level with
the handler's name, recorded on the registry, and reported by ``health``.
"""

import argparse
import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.daemon.cli import cmd_health
from claude_code_hooks_daemon.daemon.controller import DaemonController
from claude_code_hooks_daemon.daemon.project_handler_health import ProjectHandlerHealthState
from claude_code_hooks_daemon.handlers import registry as registry_module
from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry
from claude_code_hooks_daemon.handlers.session_start.project_handler_load_checker import (
    ProjectHandlerLoadCheckerHandler,
)

_POISON = "zzqx_poison"
_POISONED_KEY = "PreToolUse.destructive_git"
_CONFIG: dict[str, Any] = {
    "pre_tool_use": {
        "destructive_git": {"enabled": True, "options": {_POISON: True}},
        "pipe_blocker": {"enabled": True, "options": {"extra_whitelist": ["zzqx-tool"]}},
    }
}
_real_handler_options = registry_module.handler_options


def _failing_for_the_poisoned_block(handler_config: object) -> dict[str, Any]:
    options = _real_handler_options(handler_config)
    if _POISON in options:
        raise RuntimeError("injected option-collection failure")
    return options


def _register(registry: HandlerRegistry, router: EventRouter) -> None:
    registry.discover()
    with patch.object(registry_module, "handler_options", _failing_for_the_poisoned_block):
        registry.register_all(router, config=_CONFIG)


def _handler(router: EventRouter, class_name: str) -> object:
    for handler in router.get_chain(EventType.PRE_TOOL_USE).handlers:
        if type(handler).__name__ == class_name:
            return handler
    raise AssertionError(f"{class_name} was not registered")


class TestRegistry:
    def test_the_failure_is_logged_at_error_level_naming_the_handler(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.ERROR, logger=registry_module.__name__):
            _register(HandlerRegistry(), EventRouter())
        errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
        assert any(_POISONED_KEY in message for message in errors), errors

    def test_the_failure_is_recorded_on_the_registry(self) -> None:
        registry = HandlerRegistry()
        _register(registry, EventRouter())
        assert registry.option_failures == {
            _POISONED_KEY: "RuntimeError: injected option-collection failure"
        }

    def test_the_other_handlers_still_get_their_options(self) -> None:
        router = EventRouter()
        _register(HandlerRegistry(), router)
        pipe_blocker = _handler(router, "PipeBlockerHandler")
        assert isinstance(pipe_blocker, PipeBlockerHandler)
        assert pipe_blocker._extra_whitelist == ["zzqx-tool"]

    def test_the_failed_handler_is_still_registered_on_its_defaults(self) -> None:
        router = EventRouter()
        _register(HandlerRegistry(), router)
        assert not hasattr(_handler(router, "DestructiveGitHandler"), f"_{_POISON}")

    def test_a_clean_registration_records_no_failures(self) -> None:
        registry = HandlerRegistry()
        registry.discover()
        registry.register_all(EventRouter(), config=_CONFIG)
        assert registry.option_failures == {}


class TestSessionStartAdvisory:
    """The registry hands the failures to the session-start checker it builds."""

    def _checker(self, router: EventRouter) -> ProjectHandlerLoadCheckerHandler:
        for handler in router.get_chain(EventType.SESSION_START).handlers:
            if isinstance(handler, ProjectHandlerLoadCheckerHandler):
                return handler
        raise AssertionError("ProjectHandlerLoadCheckerHandler was not registered")

    def test_the_checker_names_the_failed_handler_at_session_start(self) -> None:
        router = EventRouter()
        _register(HandlerRegistry(), router)
        checker = self._checker(router)
        with patch.object(checker, "_read_state", return_value=ProjectHandlerHealthState()):
            assert checker.matches({}) is True
            text = "\n".join(checker.handle({}).context)
        assert _POISONED_KEY in text

    def test_the_checker_is_silent_after_a_clean_registration(self) -> None:
        registry = HandlerRegistry()
        registry.discover()
        router = EventRouter()
        registry.register_all(router, config=_CONFIG)
        checker = self._checker(router)
        with patch.object(checker, "_read_state", return_value=ProjectHandlerHealthState()):
            assert checker.matches({}) is False


class TestControllerHealth:
    def test_health_reports_the_failed_handler(self) -> None:
        controller = DaemonController()
        _register(controller.get_registry(), controller.get_router())
        assert controller.get_health()["option_failures"] == {
            _POISONED_KEY: "RuntimeError: injected option-collection failure"
        }

    def test_health_omits_the_key_when_every_handler_has_its_options(self) -> None:
        assert "option_failures" not in DaemonController().get_health()


def _running_project(tmp_path: Path) -> tuple[argparse.Namespace, Path]:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "hooks-daemon.yaml").write_text("version: '1.0'\n", encoding="utf-8")
    socket_path = claude_dir / "hooks-daemon" / "untracked" / "venv" / "socket"
    socket_path.parent.mkdir(parents=True)
    socket_path.touch()
    return argparse.Namespace(project_root=tmp_path), socket_path


def _health_response(result_extra: dict[str, Any]) -> dict[str, Any]:
    return {
        "result": {
            "status": "healthy",
            "stats": {},
            "handlers": {"PreToolUse": 1},
            **result_extra,
        }
    }


class TestHealthCommand:
    def _run(self, tmp_path: Path, response: dict[str, Any]) -> int:
        args, socket_path = _running_project(tmp_path)
        cli = "claude_code_hooks_daemon.daemon.cli"
        with (
            patch(f"{cli}.read_pid_file", return_value=12345),
            patch(f"{cli}.get_project_path", return_value=tmp_path),
            patch(f"{cli}.get_socket_path", return_value=socket_path),
            patch(f"{cli}.send_daemon_request", return_value=response),
            patch(f"{cli}.check_hook_registration_warnings", return_value=[]),
            patch(
                f"{cli}._read_project_handler_health",
                return_value=ProjectHandlerHealthState(failures=[], loaded_count=0),
            ),
        ):
            return cmd_health(args)

    def test_a_failed_handler_is_named_and_fails_the_command(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        response = _health_response(
            {"option_failures": {_POISONED_KEY: "RuntimeError: injected option-collection failure"}}
        )
        assert self._run(tmp_path, response) == 1
        out = capsys.readouterr().out
        assert _POISONED_KEY in out
        assert "RuntimeError: injected option-collection failure" in out

    def test_no_failures_keeps_the_command_healthy(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert self._run(tmp_path, _health_response({})) == 0
        assert "Handler options:" in capsys.readouterr().out
