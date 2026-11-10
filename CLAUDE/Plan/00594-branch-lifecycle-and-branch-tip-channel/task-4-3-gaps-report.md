# Task 4.3 gaps report: remote-only park record, group-pool PARKED, "park cleared" on an ended park

Branch: `plan-00594-task-4-3-gaps`. Release note 051. Built from a client report's findings; no client names appear.

## Changes

1. **Remote-only park keeps a refused push.** `_park_remote_only` (`core/branch_park.py`) no longer raises when the push fails. `_keep_refused_remote_park` creates a local branch at the park commit (`update-ref` with an empty old value, so it cannot clobber), writes the same git-config record through the new shared `_record_park`, and returns `ParkResult(pushed=False, retry_command="git push <remote> <name>")`. The CLI then prints "parked locally, not pushed" and exits 3 with no CLI change. A push that succeeds still leaves no local branch. A local branch (not just a config record) was chosen so the park commit is reachable and the pool logic below applies identically.
2. **Group-pool PARKED.** `_with_standing_parks` (`core/branch_creation.py`) marks a remote copy parked when the local park record's sha equals the local tip and the remote tip is an ancestor of it (`merge-base --is-ancestor`). The same-tip group then resolves PARKED through the existing `_group_pool`. A remote tip not behind the park keeps the group OPEN.
3. **"Park cleared" on an ended park.** New `announce_ended_parks` (`core/branch_park.py`): a record whose branch tip is no longer the recorded park commit, or whose ref is gone, yields `Park cleared: <name> (<reason>)` (the wording the merge path already uses) and the record is removed, so it prints once. Wired into `BranchSweepHandler.handle` (every SessionStart source, fail-silent on `BranchParkError`) and `cmd_branch_sweep` (text mode only, not `--json`). `branch-park --clear` still prints "Park record cleared".

Note: `git branch -D` removes the branch's config section itself, so a deleted branch loses its record without a line; only a bare ref deletion is announced.

## Files

- `src/claude_code_hooks_daemon/core/branch_park.py`, `core/branch_creation.py`, `handlers/session_start/branch_sweep.py`, `daemon/cli.py`
- Tests: new `tests/unit/core/test_branch_park_gaps.py` (10); `tests/unit/handlers/session_start/test_branch_sweep.py` (+1); `tests/unit/core/test_branch_park.py` (the old "remote-only push failure parks nothing" test replaced by "keeps the park locally")
- `docs/guides/CONFIGURATION.md`; release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/051-branch-park-gaps-remote-only-group-pool-and-park-cleared.md`

## Tests seen failing first

- Collection ImportError (`announce_ended_parks` absent); with a stub, 5 of 8 failed: remote-only refused push raised `BranchParkError ... nothing is parked`, the CLI exit-3 case, the group-pool allow case (verdict stayed deny), and the two ended-park cases (empty list).
- Handler test `test_an_ended_park_is_announced_once_at_session_start` failed with an empty context before the wiring.
- The group-pool test first still denied after the fix, because the parked pool inherited cap 1; that showed the group did resolve PARKED ("Parked branches: 1 (cap 1)"), and the test gives the parked pool its own cap.

## QA

- `./scripts/qa/run_autofix.sh`: clean.
- `./scripts/qa/llm_qa.py changed --base main --allow-unmapped`: 42/42 passed (changed_tests: 2641 passed, 0 failed, 5 skipped).
- `python -m pyright` on every changed source and test file: 0 errors.

## Open items

- Merge of the branch, PLAN.md checkboxes and the push are left to the coordinator.
- Release note 043 still says a remote-only branch parks nothing on a refused push; note 051 supersedes it (043 was left as written, since it describes what shipped then).
