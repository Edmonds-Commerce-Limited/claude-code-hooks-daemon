"""A broken config falls back to ONE shared default ``Config`` (ledger 00466 N54).

Each Stop used to rebuild ``Config()`` (about 50 ms) in every handler whose
config read failed. The fallback is now built once and reused.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.post_tool_use.recovery_cron_advisor import (
    RecoveryCronAdvisorHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.plan_status_snapshot import (
    PlanStatusSnapshotHandler,
)
from claude_code_hooks_daemon.utils.config_cache import default_config

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RECOVERY = "claude_code_hooks_daemon.handlers.post_tool_use.recovery_cron_advisor"
_SNAPSHOT = "claude_code_hooks_daemon.handlers.pre_tool_use.plan_status_snapshot"


@pytest.fixture
def _project_context() -> Iterator[None]:
    ProjectContext.initialize(_REPO_ROOT / ".claude" / "hooks-daemon.yaml")
    yield
    ProjectContext.reset()


def test_default_config_is_built_once() -> None:
    assert default_config() is default_config()
    assert isinstance(default_config(), Config)


def test_recovery_cron_advisor_reuses_one_default_on_a_broken_config(
    _project_context: None,
) -> None:
    handler = RecoveryCronAdvisorHandler()
    with patch(f"{_RECOVERY}.load_config_cached", side_effect=ValueError("broken")):
        first = handler._load_config()
        second = handler._load_config()
    assert first is second
    assert first is default_config()


def test_plan_status_snapshot_reuses_one_default_on_a_broken_config(
    _project_context: None,
) -> None:
    handler = PlanStatusSnapshotHandler()
    with patch(f"{_SNAPSHOT}.load_config_cached", side_effect=ValueError("broken")):
        first = handler._load_config()
        second = handler._load_config()
    assert first is second
    assert first is default_config()
