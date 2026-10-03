"""The one ``git worktree list --porcelain`` parser (Plan 00470 Task 4.5).

Both ``core.worktree_reaping`` and ``utils.stale_checkouts`` read the listing
through it, so the two cannot disagree about what git said.
"""

from pathlib import Path

from claude_code_hooks_daemon.utils.git_repo import WorktreeRecord, parse_worktree_porcelain

_LISTING = (
    "worktree /repo\nHEAD aaa\nbranch refs/heads/main\n\n"
    "worktree /repo/untracked/worktrees/a\nHEAD bbb\nbranch refs/heads/feat/a\nlocked reason\n\n"
    "worktree /gone\nHEAD ccc\nbranch refs/heads/old\nprunable gitdir file points to missing\n\n"
    "worktree /repo/detached\nHEAD ddd\ndetached\n"
)


def test_every_record_carries_path_branch_and_markers() -> None:
    assert parse_worktree_porcelain(_LISTING) == (
        WorktreeRecord(Path("/repo"), "main", locked=False, prunable=False),
        WorktreeRecord(Path("/repo/untracked/worktrees/a"), "feat/a", locked=True, prunable=False),
        WorktreeRecord(Path("/gone"), "old", locked=False, prunable=True),
        WorktreeRecord(Path("/repo/detached"), None, locked=False, prunable=False),
    )


def test_records_without_blank_separators_are_still_split_on_the_worktree_line() -> None:
    listing = "worktree /a\nbranch refs/heads/x\nworktree /b\nbranch refs/heads/y\n"

    records = parse_worktree_porcelain(listing)

    assert [(r.path, r.branch) for r in records] == [(Path("/a"), "x"), (Path("/b"), "y")]


def test_empty_listing_has_no_records() -> None:
    assert parse_worktree_porcelain("") == ()
