"""Tests for the one-shot plan-close approval marker (Plan 00367).

A human who wants the ``plan_workflow.close_requires_human_approval`` gate
records an approval for ONE plan; the very next terminal status flip of that
plan consumes it. The marker lives under the daemon's untracked directory so
it can never be committed, and it is keyed by plan number so an approval for
plan 12 can never close plan 13.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.plan_qa.close_approval import (
    APPROVAL_SUBDIR,
    APPROVAL_SUFFIX,
    approval_marker_path,
    consume_approval,
    plan_number_from_plan_doc_path,
    record_approval,
)


def test_marker_path_is_under_untracked_and_zero_padded(tmp_path: Path) -> None:
    path = approval_marker_path(tmp_path, 42)
    assert path == tmp_path / APPROVAL_SUBDIR / f"00042{APPROVAL_SUFFIX}"


def test_record_creates_the_marker_and_its_directory(tmp_path: Path) -> None:
    path = record_approval(tmp_path, 367)
    assert path.is_file()
    assert "00367" in path.read_text(encoding="utf-8")


def test_consume_removes_the_marker_once(tmp_path: Path) -> None:
    record_approval(tmp_path, 367)
    assert consume_approval(tmp_path, 367) is True
    assert not approval_marker_path(tmp_path, 367).exists()
    assert consume_approval(tmp_path, 367) is False


def test_consume_is_keyed_by_plan_number(tmp_path: Path) -> None:
    record_approval(tmp_path, 12)
    assert consume_approval(tmp_path, 13) is False
    assert approval_marker_path(tmp_path, 12).exists()


def test_plan_number_from_active_plan_folder() -> None:
    path = Path("/repo/CLAUDE/Plan/00367-deployed-docs/PLAN.md")
    assert plan_number_from_plan_doc_path(path, "CLAUDE/Plan") == 367


def test_plan_number_from_archived_plan_folder() -> None:
    path = Path("/repo/CLAUDE/Plan/Completed/00042-widget/PLAN.md")
    assert plan_number_from_plan_doc_path(path, "CLAUDE/Plan") == 42


def test_plan_number_is_none_outside_the_plan_directory() -> None:
    assert plan_number_from_plan_doc_path(Path("/repo/docs/00042-x/PLAN.md"), "CLAUDE/Plan") is None


def test_plan_number_is_none_for_a_folder_without_a_number() -> None:
    path = Path("/repo/CLAUDE/Plan/widget/PLAN.md")
    assert plan_number_from_plan_doc_path(path, "CLAUDE/Plan") is None
