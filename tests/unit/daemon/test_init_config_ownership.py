"""The init-config templates document claude_md.ownership (Plan 00599)."""

from __future__ import annotations

from typing import Literal

import pytest
import yaml

from claude_code_hooks_daemon.config.models import ClaudeMdOwnership, Config
from claude_code_hooks_daemon.daemon.init_config import generate_config


@pytest.mark.parametrize("mode", ["minimal", "full"])
def test_template_ships_ownership_own_and_still_validates(
    mode: Literal["minimal", "full"],
) -> None:
    text = generate_config(mode)
    assert "claude_md:" in text
    assert "ownership: own" in text
    assert "ownership_text" in text  # documented, commented out
    data = yaml.safe_load(text)
    assert data["claude_md"] == {"ownership": "own"}
    config = Config.model_validate(data)
    assert config.claude_md.ownership == ClaudeMdOwnership.OWN
