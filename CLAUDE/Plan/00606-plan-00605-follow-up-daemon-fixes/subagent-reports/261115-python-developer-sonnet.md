# Plan 00606 report: python-developer (sonnet)

Branch `worktree-plan-606-followups`. Tasks 1.1 to 1.4 implemented test-first.

## Task 1.1 work-queue done caches the finished issue

- Red: 3 of the 4 new tests in `tests/unit/daemon/test_work_queue_cli.py` failed before the fix
  (finished issue still cached; number taken from the entry name; stale cache entry not removed
  when the GitHub lookup fails). The fourth (entry without an issue number) passed, as intended.
- Fix: `issue_number_in_name` (new public helper over the existing `_ISSUE_IN_NAME` regex in
  `core/branch_inventory.py`, no new regex) is read from the entry's branch then name.
  `_next_issue_line` removes it from the existing cache first (so a failed lookup still drops it),
  and `refresh_workable_cache` gained `exclude`, so the refreshed cache omits it.
- Green: 45 passed (`test_work_queue_cli.py`, `test_workable_issues.py`).

## Task 1.2 acceptance socket discovery

- Red: `tests/unit/test_acceptance_socket_discovery.py` (3 tests) failed with AttributeError, the
  conftest having no resolver.
- Fix: `_discover_socket` keeps env first, then the `untracked/` glob, then the daemon's own
  `get_socket_path(REPO_ROOT)`, which returns the `/tmp` fallback when the natural path is too long.
- Green: 3 passed.

## Task 1.3 branch_creation_guard and setup_worktree.sh

- Red: 3 guard tests failed (no match; creation verdict on an empty list); the parser tests failed
  at import of `ROUTE_SETUP_WORKTREE`.
- Fix: `created_branches` (shared with `branch_touch_recorder`) now also reads
  `scripts/setup_worktree.sh <name>` run directly or via bash/sh/zsh/dash/ksh, with any path form.
  `bash -n`, `bash -c`, `cat`, `echo`, `grep`, a missing name, an option or a shell-expanded name
  match nothing. The script acts on the repository that holds it, so the synthetic invocation's
  directory chain ends in the script's repository root. Route name: `setup-worktree`.
- Green: 126 passed across the parser, guard and post_tool_use branch tests.
- Side effect: `branch_touch_recorder` now records the creator of a script-made branch too.

## Task 1.4

Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/077-work-queue-done-and-setup-worktree-guard.md`.
