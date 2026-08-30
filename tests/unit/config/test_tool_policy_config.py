"""Tests for the tool_policy config block (Plan 00293 Task 2.3).

Projects declare tools they never want (`tool_policy.never_want`) and tune the
report's low-use floor. Validated, ``extra="forbid"``, ships empty — the
daemon must never assert a never-want the project did not declare.
"""

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config, ToolPolicyConfig


class TestToolPolicyConfig:
    def test_ships_empty(self) -> None:
        config = Config()
        assert config.tool_policy.never_want == []
        assert config.tool_policy.low_use_max_calls == 2

    def test_never_want_entries_carry_tool_and_reason(self) -> None:
        config = Config.model_validate(
            {
                "tool_policy": {
                    "never_want": [
                        {"tool": "Artifact", "reason": "publishing leaves the repository"}
                    ]
                }
            }
        )
        entry = config.tool_policy.never_want[0]
        assert entry.tool == "Artifact"
        assert entry.reason == "publishing leaves the repository"

    def test_reason_is_optional(self) -> None:
        policy = ToolPolicyConfig.model_validate({"never_want": [{"tool": "NotebookEdit"}]})
        assert policy.never_want[0].reason == ""

    def test_unknown_keys_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ToolPolicyConfig.model_validate({"never_wants": []})

    def test_unknown_entry_keys_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ToolPolicyConfig.model_validate({"never_want": [{"tool": "Artifact", "enforce": True}]})

    def test_never_want_map_helper(self) -> None:
        policy = ToolPolicyConfig.model_validate(
            {"never_want": [{"tool": "Artifact", "reason": "no publishing"}]}
        )
        assert policy.never_want_map() == {"Artifact": "no publishing"}
