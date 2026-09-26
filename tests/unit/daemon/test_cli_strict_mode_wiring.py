"""Regression test: _build_initialised_controller threads daemon.strict_mode (Plan 00466 N24).

Mirrors test_cli_verdict_log_wiring.py: DaemonController's ``config``
constructor parameter is never populated by the real daemon startup path
(``_build_initialised_controller`` constructs ``DaemonController()`` with no
config and threads individual config slices into ``initialise()`` instead).
``daemon.strict_mode`` read ``self._config.strict_mode`` — always ``False``,
because ``self._config`` is always ``None`` on this path — so every guard
treated its own crash as "no match" in every real install, regardless of
what ``hooks-daemon.yaml`` declared. ``strict_mode`` must follow the same
narrow-slice idiom as ``verdict_log``/``chain``/``project_layout``.
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


def test_build_initialised_controller_passes_strict_mode_true() -> None:
    """The loaded config's daemon.strict_mode: true reaches DaemonController.initialise()."""
    config = Config.model_validate({"daemon": {"strict_mode": True}})

    captured = _build_and_capture(config)

    assert captured.get("strict_mode") is True


def test_build_initialised_controller_passes_strict_mode_false() -> None:
    """The default (unset) daemon.strict_mode reaches initialise() as False, not dropped."""
    config = Config.model_validate({})

    captured = _build_and_capture(config)

    assert captured.get("strict_mode") is False
