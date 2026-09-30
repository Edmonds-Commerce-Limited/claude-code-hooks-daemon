"""daemon.unprovisioned_mode (Plan 00477 Task 3.3): warn or block, default warn."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import DaemonConfig


class TestUnprovisionedMode:
    def test_defaults_to_warn(self) -> None:
        assert DaemonConfig().unprovisioned_mode == "warn"

    @pytest.mark.parametrize("mode", ["warn", "block"])
    def test_accepts_the_two_modes(self, mode: str) -> None:
        config = DaemonConfig.model_validate({"unprovisioned_mode": mode})

        assert config.unprovisioned_mode == mode

    @pytest.mark.parametrize("bad", ["blok", "BLOCK", "", "allow", "true"])
    def test_rejects_anything_else(self, bad: str) -> None:
        with pytest.raises(ValidationError):
            DaemonConfig.model_validate({"unprovisioned_mode": bad})
