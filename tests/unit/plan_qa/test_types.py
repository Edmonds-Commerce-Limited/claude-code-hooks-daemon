"""Tests for plan_qa.types — core check-system types (Plan 00144, Task 1.5)."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)


class TestEnums:
    def test_stages(self) -> None:
        assert {stage.value for stage in Stage} == {"edit", "commit", "sweep"}

    def test_levels(self) -> None:
        assert {level.value for level in Level} == {"block", "advise"}


class TestFinding:
    def test_is_frozen(self) -> None:
        finding = Finding(
            check_id="x",
            level=Level.ADVISE,
            message="m",
            remediation="r",
        )
        assert finding.path is None
        with pytest.raises(FrozenInstanceError):
            finding.message = "other"


class TestCheckContext:
    def test_plan_dir_property(self) -> None:
        context = CheckContext(project_root=Path("/repo"), plan_dir_rel="CLAUDE/Plan")
        assert context.plan_dir == Path("/repo/CLAUDE/Plan")

    def test_policy_defaults(self) -> None:
        context = CheckContext(project_root=Path("/repo"), plan_dir_rel="CLAUDE/Plan")
        assert context.completed_dir == "Completed"
        assert context.cancelled_dir == "Cancelled"
        assert context.require_terminal_date is False
        assert context.legacy_plan_allowlist == frozenset()
        assert context.collision_allowlist == frozenset()
        assert context.file_content is None
        assert context.gitfacts is None
        assert context.tree is None

    def test_is_frozen(self) -> None:
        context = CheckContext(project_root=Path("/repo"), plan_dir_rel="CLAUDE/Plan")
        with pytest.raises(FrozenInstanceError):
            context.plan_dir_rel = "elsewhere"


class TestCheckSpec:
    def test_holds_declarative_metadata(self) -> None:
        spec = CheckSpec(
            check_id="example",
            stage=Stage.SWEEP,
            level=Level.ADVISE,
            sins=("A1", "B2"),
            run=lambda context: [],
        )
        assert spec.check_id == "example"
        assert spec.stage == Stage.SWEEP
        assert spec.sins == ("A1", "B2")
        assert spec.run(CheckContext(project_root=Path("/r"), plan_dir_rel="P")) == []
