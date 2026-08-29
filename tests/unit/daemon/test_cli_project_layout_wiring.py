"""Regression test: _build_initialised_controller threads project_layout (Plan 00288).

Mirrors test_cli_verdict_log_wiring.py: DaemonController's ``config``
constructor parameter is never populated by the real daemon startup path,
so ``project_layout`` must be built from the loaded ``Config`` and threaded
into ``initialise()`` the same way every other narrow config slice is.
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.core.project_layout import ProjectLayout
from claude_code_hooks_daemon.daemon.cli import _build_initialised_controller
from claude_code_hooks_daemon.daemon.controller import DaemonController


def test_build_initialised_controller_passes_project_layout() -> None:
    """The loaded config's layout: block reaches DaemonController.initialise()."""
    config = Config.model_validate({"layout": {"config_dirs": ["settings"]}})

    captured: dict[str, Any] = {}

    def fake_initialise(self: DaemonController, *args: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    with patch(
        "claude_code_hooks_daemon.daemon.controller.DaemonController.initialise",
        new=fake_initialise,
    ):
        _build_initialised_controller(config, Path("/tmp/does-not-need-to-exist"))

    assert "project_layout" in captured
    project_layout = captured["project_layout"]
    assert isinstance(project_layout, ProjectLayout)
    assert project_layout.config_dirs == ("config", "settings")
