# Fix CI integration failures, PR #226 (plan-00636-stop-guard)

Fix sha: f3dc97875 (merge commit 2bbfd10ea of origin/main d59ec23d4, then the fix).

## Failing tests (CI shard: 2 failed)

- tests/integration/test_handler_scope_defaults.py::TestTheShippedDefaults::test_exactly_the_listed_handlers_are_scoped_to_main
- tests/integration/test_handler_scope_defaults.py::TestTheShippedDefaults::test_every_other_handler_is_all

## Cause

The new Stop handler owner-wait-stop-guard ships `HandlerScope.MAIN` (deliberate: it judges the
coordinator seat's own stop), but `_EXPECTED_MAIN` in the test did not list it.

## Fix

Added `"owner-wait-stop-guard"` to `_EXPECTED_MAIN`. The file now has 6 passing tests locally.

## Merge

Merge commit, no rebase. Conflicts resolved:

- config-changes/v3.77.0.yaml: kept both entries (owner_wait_stop_guard and human_approval_check). YAML parses.
- CONTRIBUTING.md and CLAUDE/HANDLER_DEVELOPMENT.md priority table: kept `owner_wait_stop_guard` in the 0-9 row and took main's `10-21` Safety range.
- Release notes need no renumbering: ours is 026, main's is 087, so there is no collision. #228 should take 088.

## Local full integration run (nice, excluding daemon_smoke)

6 failed, 6857 passed (stopped at maxfail=6). Besides the 2 above, 4 failed locally:

- test_client_owned_asset_lint::test_shell_assets_are_clean
- test_project_context_isolation (3 cases)

CI reported exactly 2 failures, so these 4 look local-environment related (shellcheck absent,
PYTHONPATH worktree workaround). I did not investigate them.
