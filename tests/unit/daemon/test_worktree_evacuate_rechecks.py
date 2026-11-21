"""Every keep predicate is read again after the typed question (Plan 00627, F-BYPS L1).

The question waits as long as the human takes. A live process, a running
work-queue hold or a git lock that appears meanwhile must keep the asked
worktree, and every later worktree in the same run, rather than being judged
against readings taken before the wait.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from tests.support.scratch_tree import ScratchTree, git
from tests.unit.daemon.test_worktree_evacuate import (
    _NAME,
    _all_due,
    _build,
    _git_identity,
    _keep_text,
    _main,
    _scratch,
    _store,
    _worktree,
)

from claude_code_hooks_daemon.core import agent_ownership, worktree_reaping
from claude_code_hooks_daemon.core.agent_ownership import RunningHolds
from claude_code_hooks_daemon.core.worktree_scratch_evacuation import EvacuationGate
from claude_code_hooks_daemon.daemon.cli import cmd_worktree_reap
from claude_code_hooks_daemon.daemon.worktree_evacuate import EvacuateSeams

__all__ = ["_git_identity"]

_DAY = 86400.0
_LATER = "agent-evac-2"


@pytest.fixture
def tree(tmp_path: Path) -> ScratchTree:
    built = _build(tmp_path)
    _all_due(built)
    return built


def _later(tree: ScratchTree) -> Path:
    return _main(tree) / ".claude" / "worktrees" / _LATER


def _add_later(tree: ScratchTree, monkeypatch: pytest.MonkeyPatch) -> None:
    """A second clean worktree, judged after the asked one whatever git's listing order."""
    git(_main(tree), "worktree", "add", "-q", "-b", _LATER, str(_later(tree)))
    real = worktree_reaping.collect_worktree_states

    def asked_first(*args: Any, **kwargs: Any) -> tuple[Any, ...]:
        return tuple(sorted(real(*args, **kwargs), key=lambda state: state.name != _NAME))

    monkeypatch.setattr(worktree_reaping, "collect_worktree_states", asked_first)


def _holds(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    """A mutable set of branches a running work-queue record holds."""
    branches: set[str] = set()

    def running(_untracked: Path, _root: Path | None = None) -> RunningHolds:
        return RunningHolds(branches=frozenset(branches), worktrees=frozenset())

    monkeypatch.setattr(agent_ownership, "running_holds", running)
    return branches


def _run(
    tree: ScratchTree,
    capsys: pytest.CaptureFixture[str],
    *,
    confirm: Callable[[str, EvacuationGate], bool],
    cwds: dict[int, Path],
    only: str | None = _NAME,
    after_step: Callable[[str, str], None] | None = None,
) -> tuple[int, str]:
    now = time.time() + _DAY + 60
    args = argparse.Namespace(
        project_root=str(_main(tree)),
        base_branch="main",
        reap=True,
        only=only,
        reap_branches=False,
    )
    rc = cmd_worktree_reap(
        args,
        age_fn=lambda _p: 999_999.0,
        process_cwds_fn=lambda: dict(cwds),
        evacuate_seams=EvacuateSeams(
            confirm=confirm,
            wall_clock=lambda: now,
            process_cwds=lambda: {1: Path("/elsewhere")},
            after_step=after_step,
        ),
    )
    return rc, capsys.readouterr().out


def _assert_asked_kept_unpacked(tree: ScratchTree, rc: int, out: str, reason: str) -> None:
    assert rc == 1, out
    assert _worktree(tree).is_dir(), out
    assert (_scratch(tree) / "two.txt").read_bytes() == b"second", out
    assert not _store(tree).exists(), out
    assert reason in _keep_text(out), out


class TestTheAskedWorktree:
    def test_a_process_started_while_asked_keeps_it_and_packs_nothing(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cwds: dict[int, Path] = {}

        def start_then_yes(_relative: str, _gate: EvacuationGate) -> bool:
            cwds[4242] = _worktree(tree).resolve()
            return True

        rc, out = _run(tree, capsys, confirm=start_then_yes, cwds=cwds)

        _assert_asked_kept_unpacked(tree, rc, out, "pid 4242")

    def test_a_hold_added_while_asked_keeps_it_and_packs_nothing(
        self,
        tree: ScratchTree,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        branches = _holds(monkeypatch)

        def hold_then_yes(_relative: str, _gate: EvacuationGate) -> bool:
            branches.add(_NAME)
            return True

        rc, out = _run(tree, capsys, confirm=hold_then_yes, cwds={})

        _assert_asked_kept_unpacked(tree, rc, out, "running work-queue agent")

    def test_a_lock_taken_while_asked_keeps_it_and_packs_nothing(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def lock_then_yes(_relative: str, _gate: EvacuationGate) -> bool:
            git(_main(tree), "worktree", "lock", str(_worktree(tree)))
            return True

        rc, out = _run(tree, capsys, confirm=lock_then_yes, cwds={})

        _assert_asked_kept_unpacked(tree, rc, out, "locked")

    def test_a_process_started_while_packing_keeps_it_before_removal(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The answer's own re-check has passed; the one before removal still runs."""
        cwds: dict[int, Path] = {}

        def start_during_pack(_step: str, _name: str) -> None:
            cwds[4343] = _worktree(tree).resolve()

        rc, out = _run(
            tree,
            capsys,
            confirm=lambda _r, _g: True,
            cwds=cwds,
            after_step=start_during_pack,
        )

        assert rc == 1, out
        assert _worktree(tree).is_dir(), out
        assert "ARCHIVED" in out, out
        assert "pid 4343" in _keep_text(out), out


class TestLaterWorktrees:
    def test_a_hold_added_while_asked_keeps_a_later_worktree(
        self,
        tree: ScratchTree,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _add_later(tree, monkeypatch)
        branches = _holds(monkeypatch)

        def hold_later_then_no(_relative: str, _gate: EvacuationGate) -> bool:
            branches.add(_LATER)
            return False

        rc, out = _run(tree, capsys, confirm=hold_later_then_no, cwds={}, only=None)

        assert rc == 1, out
        assert _later(tree).is_dir(), out
        line = next(line for line in out.splitlines() if _LATER in line)
        assert line.startswith("KEEP"), out
        assert "running work-queue agent" in line, out

    def test_a_process_started_while_asked_keeps_a_later_worktree(
        self,
        tree: ScratchTree,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _add_later(tree, monkeypatch)
        cwds: dict[int, Path] = {}

        def start_later_then_no(_relative: str, _gate: EvacuationGate) -> bool:
            cwds[4444] = _later(tree).resolve()
            return False

        rc, out = _run(tree, capsys, confirm=start_later_then_no, cwds=cwds, only=None)

        assert rc == 1, out
        assert _later(tree).is_dir(), out
        line = next(line for line in out.splitlines() if _LATER in line)
        assert line.startswith("KEEP"), out
        assert "pid 4444" in line, out

    def test_without_a_change_a_later_worktree_is_still_reaped(
        self,
        tree: ScratchTree,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _add_later(tree, monkeypatch)

        rc, out = _run(tree, capsys, confirm=lambda _r, _g: False, cwds={}, only=None)

        assert rc == 1, out
        assert not _later(tree).exists(), out
        assert _worktree(tree).is_dir(), out
