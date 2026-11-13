"""The controller configures the ownership hints from ``claude_md`` (Plan 00599).

Without this wiring every hint stays inactive in production: the unconfigured
state is silent, so the unit tests that configure by hand cannot notice.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from claude_code_hooks_daemon.config.models import ClaudeMdConfig, ClaudeMdOwnership
from claude_code_hooks_daemon.core import ownership
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.controller import DaemonController

_BASE_YAML = "version: '1.0'\nhandlers:\n  pre_tool_use: {}\n"


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    ownership.reset()
    yield
    ownership.reset()
    ProjectContext.reset()


def _initialise(tmp_path: Path, claude_md: ClaudeMdConfig | None) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".claude").mkdir(parents=True)
    (workspace / ".claude" / "hooks-daemon.yaml").write_text(_BASE_YAML)

    def _fake_run(*_args: Any, **_kwargs: Any) -> Mock:
        return Mock(returncode=0, stdout=f"{workspace}\n")

    with patch("subprocess.run", side_effect=_fake_run):
        DaemonController().initialise(workspace_root=workspace, claude_md=claude_md)


def test_default_config_turns_the_hints_on(tmp_path: Path) -> None:
    assert ownership.hints_enabled() is False
    _initialise(tmp_path, ClaudeMdConfig())
    assert ownership.hints_enabled() is True


def test_off_keeps_the_hints_silent(tmp_path: Path) -> None:
    _initialise(tmp_path, ClaudeMdConfig(ownership=ClaudeMdOwnership.OFF))
    assert ownership.hints_enabled() is False


def test_custom_keeps_the_hints_silent(tmp_path: Path) -> None:
    _initialise(
        tmp_path,
        ClaudeMdConfig(ownership=ClaudeMdOwnership.CUSTOM, ownership_text="Mine except vendor/."),
    )
    assert ownership.hints_enabled() is False
