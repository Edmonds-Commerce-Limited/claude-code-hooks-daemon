"""Tests for the shared branch stop guard base (Plan 00558 Task 4.4).

The behaviour of the concrete guards is covered in
``tests/unit/handlers/stop/test_branch_stop_guard.py`` and
``tests/unit/handlers/subagent_stop/test_branch_subagent_stop_guard.py``; this
file pins what lives in the shared module itself.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.handlers.stop.branch_stop_guard import BranchStopGuardHandler
from claude_code_hooks_daemon.handlers.subagent_stop.branch_subagent_stop_guard import (
    BranchSubagentStopGuardHandler,
)
from claude_code_hooks_daemon.handlers.utils.branch_stop_guard_base import (
    BranchStopGuardBase,
    stop_guard_rule,
)


class TestStopGuardRule:
    """The rule names the stopping identity."""

    @pytest.mark.parametrize("who", ["session", "sub-agent"])
    def test_rule_names_the_stopping_identity(self, who: str) -> None:
        rule = stop_guard_rule(RuleID.BRANCH_STOP_GUARD, who)

        assert rule.rule_id == RuleID.BRANCH_STOP_GUARD
        assert who in rule.why
        assert who in rule.verbose


class TestSharedBase:
    """Both concrete guards derive from the one base."""

    def test_both_guards_share_the_base(self) -> None:
        assert issubclass(BranchStopGuardHandler, BranchStopGuardBase)
        assert issubclass(BranchSubagentStopGuardHandler, BranchStopGuardBase)

    def test_base_is_not_a_discoverable_handler_module(self) -> None:
        assert BranchStopGuardBase.__module__.endswith("handlers.utils.branch_stop_guard_base")
