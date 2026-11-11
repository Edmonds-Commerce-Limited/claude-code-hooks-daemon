"""claude_md.ownership config (Plan 00599)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import ClaudeMdConfig, ClaudeMdOwnership


class TestOwnershipConfig:
    def test_defaults_to_own_without_text(self) -> None:
        config = ClaudeMdConfig()
        assert config.ownership == ClaudeMdOwnership.OWN
        assert config.ownership_text is None

    @pytest.mark.parametrize("mode", list(ClaudeMdOwnership))
    def test_accepts_each_mode(self, mode: ClaudeMdOwnership) -> None:
        text = "Mine, except vendor/." if mode == ClaudeMdOwnership.CUSTOM else None
        config = ClaudeMdConfig(ownership=mode, ownership_text=text)
        assert config.ownership == mode

    def test_yaml_style_strings_validate(self) -> None:
        config = ClaudeMdConfig.model_validate({"ownership": "off"})
        assert config.ownership == ClaudeMdOwnership.OFF

    def test_custom_requires_text(self) -> None:
        with pytest.raises(ValidationError, match="ownership_text"):
            ClaudeMdConfig(ownership=ClaudeMdOwnership.CUSTOM)

    def test_custom_rejects_blank_text(self) -> None:
        with pytest.raises(ValidationError, match="ownership_text"):
            ClaudeMdConfig(ownership=ClaudeMdOwnership.CUSTOM, ownership_text="   ")

    @pytest.mark.parametrize("mode", [ClaudeMdOwnership.OWN, ClaudeMdOwnership.OFF])
    def test_text_without_custom_is_rejected(self, mode: ClaudeMdOwnership) -> None:
        with pytest.raises(ValidationError, match="ownership_text"):
            ClaudeMdConfig(ownership=mode, ownership_text="x")

    def test_unknown_mode_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClaudeMdConfig.model_validate({"ownership": "maybe"})
