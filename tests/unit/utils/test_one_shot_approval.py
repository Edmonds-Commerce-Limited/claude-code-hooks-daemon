"""Tests for the one-shot human approval store (Plan 00367).

One store, two gates: the plan-closing gate keys its markers by plan number,
the merge-to-main gate by branch name. A marker lives under the daemon's
untracked directory, is consumed by the first use, and a key that is not a
safe filename is normalised rather than allowed to escape the directory.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.utils.one_shot_approval import (
    MARKER_SUFFIX,
    OneShotApprovalStore,
)


def test_marker_path_lives_under_the_named_subdir(tmp_path: Path) -> None:
    store = OneShotApprovalStore("merge-approvals")
    assert (
        store.path(tmp_path, "feature") == tmp_path / "merge-approvals" / f"feature{MARKER_SUFFIX}"
    )


def test_record_then_consume_once(tmp_path: Path) -> None:
    store = OneShotApprovalStore("merge-approvals")
    marker = store.record(tmp_path, "feature")
    assert marker.is_file()
    assert "feature" in marker.read_text(encoding="utf-8")
    assert store.consume(tmp_path, "feature") is True
    assert not marker.exists()
    assert store.consume(tmp_path, "feature") is False


def test_keys_do_not_collide_and_do_not_escape(tmp_path: Path) -> None:
    store = OneShotApprovalStore("merge-approvals")
    slashed = store.path(tmp_path, "worktree/plan-1")
    dotted = store.path(tmp_path, "../../etc")
    assert slashed.parent == tmp_path / "merge-approvals"
    assert dotted.parent == tmp_path / "merge-approvals"
    assert slashed != store.path(tmp_path, "worktree-plan-1")


def test_stores_with_different_subdirs_are_independent(tmp_path: Path) -> None:
    OneShotApprovalStore("a").record(tmp_path, "k")
    assert OneShotApprovalStore("b").consume(tmp_path, "k") is False
