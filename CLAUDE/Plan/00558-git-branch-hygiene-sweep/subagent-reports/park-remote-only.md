# park-remote-only report

Fix: `park_branch` now parks a branch that exists only as `refs/remotes/<remote>/<name>`.

- `core/branch_park.py`: when `refs/heads/<name>` is missing but the remote-tracking ref exists, `_park_remote_only` builds the trailer commit on the remote tip (`commit-tree`, `-p` that tip) and pushes `<new>:refs/heads/<name>` as a plain fast-forward. A failed push raises `BranchParkError` and nothing is parked. On success the tracking ref is set to the new sha (idempotent: `git push` usually advances it already, so a guarded old-to-new update-ref fails). The local-branch path is unchanged, apart from sharing the new `_write_park_commit` helper.
- Inventory: already keys one record per name and reads the park trailer from the remote row, so no change was needed. A test confirms it reports PARKED with the reason.
- CLI: `clear_label_stage` is keyed by name, so it already marks a remote-only branch parked. Only the `name` help text changed to "Branch to park (local, or remote-only)".

Tests added in `tests/unit/core/test_branch_park.py`: remote-only park (parent is the old tip, bare remote ref moved, no local branch created, tracking ref follows), inventory sees it parked, push failure parks nothing, remote-only clear. The file's git subprocesses now use `git_setup_timeout()`.

QA: ruff, black and mypy are clean on the touched files. test_branch_park.py and test_branch_creation\*.py pass (57 passed). `test_fixtures_never_use_the_hook_path_git_budget.py` FAILS, and not because of this change: it flags `tests/unit/core/test_branch_inventory.py` lines 625, 647, 664, 718 and 766, a file this change does not touch.
