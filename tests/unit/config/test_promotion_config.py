"""Tests for the claude_md.promotion config block (Plan 00116 Task 2b.2).

Records which BLOCKING handlers keep their full guidance resident in the
injected block (Decision I, DESIGN-HYBRID-PROMOTION.md). Ships empty —
pure progressive disclosure is the safe default for a fresh install with
no transcript history yet. ``bin/hooks-daemon block-report`` regenerates
the recommendation; the injector (owned by another Plan 00116 task) is the
only consumer that acts on the list.
"""

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import ClaudeMdConfig, Config, PromotionConfig


class TestPromotionConfig:
    def test_ships_empty(self) -> None:
        config = Config()
        assert config.claude_md.promotion.promoted_handlers == []
        assert config.claude_md.promotion.min_blocks == 5
        assert config.claude_md.promotion.min_sessions == 2

    def test_promoted_handlers_accepts_a_list_of_names(self) -> None:
        config = Config.model_validate(
            {
                "claude_md": {
                    "promotion": {
                        "promoted_handlers": ["sed_blocker", "pipe_blocker"],
                    }
                }
            }
        )
        assert config.claude_md.promotion.promoted_handlers == ["sed_blocker", "pipe_blocker"]

    def test_thresholds_are_overridable(self) -> None:
        promotion = PromotionConfig.model_validate({"min_blocks": 10, "min_sessions": 4})
        assert promotion.min_blocks == 10
        assert promotion.min_sessions == 4

    def test_min_blocks_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            PromotionConfig.model_validate({"min_blocks": -1})

    def test_min_sessions_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            PromotionConfig.model_validate({"min_sessions": -1})

    def test_unknown_keys_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PromotionConfig.model_validate({"promoted_handler": []})

    def test_claude_md_config_unknown_keys_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClaudeMdConfig.model_validate({"promotions": {}})

    def test_promoted_handlers_entries_must_be_strings(self) -> None:
        with pytest.raises(ValidationError):
            PromotionConfig.model_validate({"promoted_handlers": [1, 2]})
