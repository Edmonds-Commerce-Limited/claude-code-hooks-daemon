"""Regression test: _build_initialised_controller threads verdict_log config.

Plan 00209: DaemonController's ``config`` constructor parameter is never
populated by the real daemon startup path (``_build_initialised_controller``
constructs ``DaemonController()`` with no config and threads individual
config slices — ``plugins_config``, ``project_handlers_config``,
``plan_workflow``, etc. — into ``initialise()`` instead). ``verdict_log``
must follow the same idiom, or ``handlers.daemon.verdict_log.enabled: false``
in a project's ``hooks-daemon.yaml`` would be silently ignored — exactly the
kind of dead config path this plan exists to prevent.
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

from claude_code_hooks_daemon.config.models import Config, VerdictLogConfig
from claude_code_hooks_daemon.daemon.cli import _build_initialised_controller
from claude_code_hooks_daemon.daemon.controller import DaemonController


def test_build_initialised_controller_passes_verdict_log_config() -> None:
    """The loaded config's daemon.verdict_log reaches DaemonController.initialise()."""
    config = Config.model_validate({"daemon": {"verdict_log": {"enabled": False}}})

    captured: dict[str, Any] = {}

    def fake_initialise(self: DaemonController, *args: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    with patch(
        "claude_code_hooks_daemon.daemon.controller.DaemonController.initialise",
        new=fake_initialise,
    ):
        _build_initialised_controller(config, Path("/tmp/does-not-need-to-exist"))

    assert "verdict_log" in captured
    verdict_log = captured["verdict_log"]
    assert isinstance(verdict_log, VerdictLogConfig)
    assert verdict_log.enabled is False
