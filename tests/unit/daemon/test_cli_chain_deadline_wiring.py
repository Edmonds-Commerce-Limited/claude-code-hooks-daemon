"""Regression test: _build_initialised_controller threads the chain deadline problems.

Plan 00466 N40 review 2 mA4: a chain deadline that cannot beat the deployed
client timeout is reported in health rather than rejected at load. The report
only reaches health if daemon startup hands ``DaemonConfig.chain_deadline_problems``
to ``DaemonController.initialise()`` -- the same narrow-slice idiom as
``strict_mode`` (see test_cli_strict_mode_wiring.py).
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.daemon.cli import _build_initialised_controller
from claude_code_hooks_daemon.daemon.controller import DaemonController


def _build_and_capture(config: Config) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_initialise(self: DaemonController, *args: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    with patch(
        "claude_code_hooks_daemon.daemon.controller.DaemonController.initialise",
        new=fake_initialise,
    ):
        _build_initialised_controller(config, Path("/tmp/does-not-need-to-exist"))
    return captured


def test_a_deadline_past_the_relay_budget_reaches_initialise() -> None:
    config = Config.model_validate(
        {
            "daemon": {
                "transport": {"relay_enabled": True, "timeout_seconds": 10},
                "chain": {"deadline_seconds": 20},
            }
        }
    )

    captured = _build_and_capture(config)

    assert captured.get("chain_deadline_problems") == config.daemon.chain_deadline_problems
    assert len(captured["chain_deadline_problems"]) == 1


def test_the_default_config_passes_no_problems() -> None:
    captured = _build_and_capture(Config.model_validate({}))

    assert captured.get("chain_deadline_problems") == []
