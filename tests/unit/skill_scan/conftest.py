"""Shared fixtures for the skill-scan tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _hermetic_claude_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan 00468: the inventory and transcript lookups default to the Claude
    config dir, so a test that passes none must still never read the real one."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "hermetic-claude-config"))
