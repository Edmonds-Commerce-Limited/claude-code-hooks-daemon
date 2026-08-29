"""Tests for ``LayoutConfig`` (Plan 00288, Task 2.1)."""

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config, LayoutConfig


class TestDefaults:
    def test_all_dir_lists_default_empty(self) -> None:
        layout = LayoutConfig()
        assert layout.source_dirs == []
        assert layout.test_dirs == []
        assert layout.config_dirs == []
        assert layout.vendor_dirs == []

    def test_mode_defaults_to_additive(self) -> None:
        assert LayoutConfig().mode == "additive"


class TestConfigCarriesALayoutBlock:
    def test_absent_block_gets_defaults(self) -> None:
        config = Config()
        assert isinstance(config.layout, LayoutConfig)
        assert config.layout.source_dirs == []
        assert config.layout.mode == "additive"

    def test_parses_full_block(self) -> None:
        raw = {
            "layout": {
                "source_dirs": ["backend/src", "packages/*/src"],
                "test_dirs": ["backend/tests", "e2e"],
                "config_dirs": ["settings"],
                "vendor_dirs": ["deps"],
                "mode": "replace",
            }
        }
        config = Config.model_validate(raw)
        assert config.layout.source_dirs == ["backend/src", "packages/*/src"]
        assert config.layout.test_dirs == ["backend/tests", "e2e"]
        assert config.layout.config_dirs == ["settings"]
        assert config.layout.vendor_dirs == ["deps"]
        assert config.layout.mode == "replace"


class TestStrictValidation:
    def test_rejects_unknown_top_level_key(self) -> None:
        with pytest.raises(ValidationError):
            LayoutConfig.model_validate({"bogus": True})

    def test_rejects_invalid_mode(self) -> None:
        with pytest.raises(ValidationError):
            LayoutConfig.model_validate({"mode": "bogus"})
