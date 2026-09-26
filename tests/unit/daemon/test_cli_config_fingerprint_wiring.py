"""Regression test: _build_initialised_controller threads the config fingerprint.

Plan 00415: the daemon must report the fingerprint of the config it actually
bound, computed from the same loaded ``Config`` it hands to ``initialise()``,
so ``check-source-fresh`` can tell when the config on disk has moved on
without a restart.
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.daemon.cli import _build_initialised_controller
from claude_code_hooks_daemon.daemon.controller import DaemonController
from claude_code_hooks_daemon.daemon.source_fingerprint import compute_config_fingerprint


def test_build_initialised_controller_passes_config_fingerprint() -> None:
    """The fingerprint of the loaded config reaches DaemonController.initialise()."""
    config = Config.model_validate({"daemon": {"idle_timeout_seconds": 777}})

    captured: dict[str, Any] = {}

    def fake_initialise(self: DaemonController, *args: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    with patch(
        "claude_code_hooks_daemon.daemon.controller.DaemonController.initialise",
        new=fake_initialise,
    ):
        _build_initialised_controller(config, Path("/tmp/does-not-need-to-exist"))

    assert captured["config_fingerprint"] == compute_config_fingerprint(config)
