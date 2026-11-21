"""``scratch-sweep status`` names the checkout an evacuated archive came from (Plan 00627 Task 6.2).

Once ``worktree-reap --reap`` has evacuated a worktree's scratch and removed the
worktree, its archives sit in the main checkout's store beside the main
checkout's own and restore into the main checkout's scratch root. The status
listing is where a human sees that an archive came from somewhere else.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from tests.support.scratch_tree import ScratchTree
from tests.unit.daemon.test_worktree_evacuate import (
    _DAY,
    _all_due,
    _build,
    _due_clock,
    _git_identity,
    _main,
    _reap,
    _store_records,
    _worktree,
    _write,
    _yes,
)

from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_scratch_sweep

__all__ = ["_git_identity"]


@pytest.fixture
def tree(tmp_path: Path) -> ScratchTree:
    return _build(tmp_path)


def _status(tree: ScratchTree, now: float, *argv: str) -> None:
    args = build_parser().parse_args(["scratch-sweep", "status", *argv])
    args.project_root = _main(tree)
    assert cmd_scratch_sweep(args, wall_clock=lambda: now) == 0


def _archive_in_main(tree: ScratchTree, now: float) -> str:
    """Sweep one due entry of the main checkout's own scratch root into the store."""
    _write(_main(tree) / "untracked" / "scratch" / "mine.txt", b"main", time.time() - 5 * _DAY)
    args = build_parser().parse_args(["scratch-sweep", "--apply"])
    args.project_root = _main(tree)
    assert (
        cmd_scratch_sweep(
            args,
            wall_clock=lambda: now,
            process_cwds=lambda: {1: Path("/elsewhere")},
            confirm_apply=lambda _root, _notice: True,
        )
        == 0
    )
    return _store_records(tree)["untracked/scratch/mine.txt"].archive_id


class TestStatusNamesTheOriginCheckout:
    def test_an_evacuated_archive_names_its_worktree_and_a_main_one_does_not(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _all_due(tree)
        now = _due_clock()
        origin = str(_worktree(tree).resolve())
        assert _reap(tree, reap=True, now=now, confirm=_yes) == 0, capsys.readouterr().out
        evacuated = {record.archive_id for record in _store_records(tree).values()}
        mine = _archive_in_main(tree, now)
        capsys.readouterr()

        _status(tree, now)

        blocks: dict[str, str] = {}
        current = ""
        for line in capsys.readouterr().out.splitlines():
            if line.startswith("  ") and not line.startswith("      "):
                current = line.split()[0]
            if current:
                blocks[current] = blocks.get(current, "") + line + "\n"
        assert set(blocks) == evacuated | {mine}, blocks
        for archive_id in evacuated:
            assert f"from checkout: {origin}" in blocks[archive_id], blocks[archive_id]
        assert "from checkout" not in blocks[mine], blocks[mine]

    def test_the_json_lists_every_archive_s_checkout(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _all_due(tree)
        now = _due_clock()
        assert _reap(tree, reap=True, now=now, confirm=_yes) == 0, capsys.readouterr().out
        mine = _archive_in_main(tree, now)
        capsys.readouterr()

        _status(tree, now, "--json")

        archives = json.loads(capsys.readouterr().out)["archives"]
        checkouts = {row["archive_id"]: row["checkouts"] for row in archives}
        assert checkouts.pop(mine) == [str(_main(tree).resolve())]
        assert checkouts
        assert all(value == [str(_worktree(tree).resolve())] for value in checkouts.values())
