# Plan 00617 implementation report

Branch: `worktree-plan-00617-park-commit-merged` (worktree
`untracked/worktrees/worktree-plan-00617-park-commit-merged`), from origin/main
d9df3271c. Not merged.

Commits:

- `44aa49d2b` adds the RED tests. The file fails at import on main, because it
  imports `is_park_residue` from its new home `branch_park`. With the import
  pointed at the old location, 7 tests fail and 8 pass.
- `3fc5060e5` is one fix commit bundling four fixes: unpark pre-filter,
  local-copy tier and `--clean`, park-aware patch equivalence, and the
  writer-only rule.
- `3a6370d5e` reverts an unrelated file swept into `3fc5060e5`. Autofix had
  reformatted the Plan 00609 report script
  `Completed/00609-.../prove-two-root-two-host.py`, so that script still fails
  black on main.
- A follow-up commit adds:
  - a `delete_branches` test;
  - the reproduction scripts with before/after output, in this folder;
  - release note 083 corrections;
  - the Success Criteria ticks.

Before/after reproduction output is in this folder:

- before: `repro_00617.before.txt`, `repro2_00617.before.txt`;
- after: `repro_00617.after.txt`, `repro2_00617.after.txt`.

On the fixed tree, every shape is deletable by the guards with no human step.

Other checks:

- **Writer history.** `branch-park` was introduced in `52ac28797` with today's
  exact `_message`. v3.72.0 and v3.74.0 carry the same text. No doc or template
  tells anyone to park by hand.
- **`branch-keep`.** `CLEAN_STATES` is shared with `branch-keep`, which now
  also accepts a `park-carried` branch. A keep then spares it from `--clean`.

## Read this first: two mismatches with the brief

1. **The headline failure is already fixed on main, but not in a release.** Plan
   00594's park-carried rule (6f9ca3545..e0b8bf035) is not in v3.74.0 and is in
   rc/3.75.0. On main, a merged branch parked once by `branch-park` is already
   `park-carried` in the inventory. The remote-delete proof and
   `R-GIT-PUSH-DELETE-REMOTE` accept it, and `branch-sweep --clean --remote --apply` deletes the remote copy. The peer team's nine branches are the
   v3.74.0 behaviour; 3.75 clears them. This plan closes the gaps that rule
   left (below).
2. **The recovery bundle no longer exists.** Plan 00594 Task 3.7 removed it
   (release note 075). It has not been added back. A remote delete still runs
   under `--force-with-lease` on the proven tip and prints a
   `git push <remote> <sha>:refs/heads/<name>` restore line. A local delete
   prints `git branch <name> <sha>`. A test asserts both lines.

## Task 1.1 reproduction (synthetic repositories)

The scripts are `untracked/scratch/repro_00617.py` and `repro2_00617.py` in the
worktree. They use the real `park_branch` writer and a bare remote. The
worktree has no `.venv`; tests ran with the worktree's `untracked/venv-*` Python.

| Shape (merged, then parked)         | inventory        | remote proof / guard  | creation guard | `--clean` local        |
| ----------------------------------- | ---------------- | --------------------- | -------------- | ---------------------- |
| park once, remote-only              | park-carried     | ALLOW                 | no pool        | n/a                    |
| park once, local copy kept          | park-carried     | ALLOW                 | no pool        | **left behind**        |
| park then unpark                    | park-carried     | **DENY**              | **open**       | n/a                    |
| squash-merged then parked, local    | patch-equivalent | ALLOW (content)       | merged         | **refused (unproven)** |
| empty `Parked-*` commit, not writer | park-carried     | ALLOW (**too broad**) | no pool        | n/a                    |

## Task 1.2 decision

**Decision:** park-only branches are classified as merged-equivalent, and the
park record stays on the branch. The trade-offs are in the JOURNAL decision
entry:

- Existing parks already carry commits, so the classifier is needed either way.
- The commit is what lets other clones and the remote see a park. The
  `commit=False` record is clone-local.
- Moving the record to a note or ref needs its own sync and pool plumbing.

Task 2.3 is not applicable, so there is no migration. Moving the record off the
branch is left to the owner as a separate design question.

## Implementation (one classifier, four consumers)

`src/claude_code_hooks_daemon/core/branch_park.py` now holds the one rule,
beside the writer:

- `is_park_message(message)`: rebuilds `_message` from the reason and user read
  back out of the message. Any other wording fails.
- `walk_park_range(repo, target, tip, *, timeout) -> ParkWalk | None`: a
  structural `log --boundary` with no free text. A park candidate has a single
  parent and the same tree as that parent. The candidates' messages are read in
  one `log --no-walk=unsorted -z` call. Each record must name the sha asked for,
  in order, with the exact count. Any failure returns None (fail closed).
- `is_park_residue(repo, tip, target)`: every commit in `target..tip` is a park
  commit, and there is at least one.
- `park_marked_refs(repo, refnames, *, timeout)`: the tip pre-filter, which now
  reads `Parked-Reason` **or** `Unparked`.

The four consumers:

- **Inventory** (`branch_inventory._pair_facts`) uses the shared walker.
  `_park_shas`, `_lines_of` and the trailer key list are removed. The inventory
  cache version is bumped from 4 to 5 so old park counts are not read.
  `PROOF_ALGORITHM_VERSION` is unchanged: its cached net-change verdicts do not
  depend on park classification, and park-carried is decided before that cache.
- **Creation guard** (`branch_creation._carried_refnames`): an unparked tip is
  now a candidate, found by one batched listing.
- **Remote proof / `R-GIT-PUSH-DELETE-REMOTE`** (`remote_branch_proof`) uses
  `park_marked_refs` and `is_park_residue` from `branch_park`.
- **Delete-branch guard** (`daemon/branch_safety.classify_branch`) has a new
  `park-carried` tier. It is judged against the default refs only, never an
  integration line (the inventory's rule), and is a forced delete because git's
  own `-d` counts the park commit. `patch_equivalent` leaves verified park
  commits out of the cherry-unique set; every other commit still needs its patch
  upstream.
- **`branch-sweep --clean`**: `CLEAN_STATES` now includes `PARK_CARRIED`, so
  the local copy is deleted too, with its restore line.

## Tests

`tests/unit/core/test_park_commit_classifier.py` holds the RED and pin tests,
committed in 44aa49d2b before the fix.

**RED on main (7):**

- unparked tip: proof, creation pool and `--clean --remote`;
- local copy: `classify_branch` tier, and `--clean` deleting local and remote
  with restore lines;
- local squash then park: patch-equivalent;
- an empty trailer commit not written by the park writer must be refused.

**Pins (already held, 8):**

- a writer park over merged work is deletable;
- refused twins:
  - a park-looking commit that changes a file;
  - a real commit under two park commits;
  - a forged writer message on a non-empty commit;
  - a park whose parent is another branch's unmerged commit;
  - a parentless park;
  - a two-parent park.

Each refused twin is checked against `is_park_residue`, the remote proof, the
guard, the inventory state and, where a local copy exists, `classify_branch`.

**Added after the fix:** writer-message accept/reject cases, and fail-closed
walk tests (git failure, malformed line, failed message read, a message record
for another sha, an extra record, a failed tip listing).

**Existing tests updated:** the 00594 helpers in `test_branch_park_carried.py`
and `test_branch_inventory.py` made empty commits by hand with
non-writer wording. They now write the writer's exact message, which the
narrowed rule requires. The inventory's malformed-log test now patches
`walk_park_range`.

## QA

- `./scripts/qa/run_autofix.sh`: clean.
- `llm_qa.py type_check magic_values error_hiding lint format`: all pass.
- pytest, by path:
  - `tests/unit/core/test_branch_*.py`
  - `tests/unit/core/test_remote_branch_proof.py`
  - `tests/unit/core/test_park_commit_classifier.py`
  - `tests/unit/daemon/test_branch_safety.py`
  - `tests/unit/daemon/test_cli_delete_branch*.py`
  - `tests/unit/handlers/pre_tool_use/test_destructive_git_*.py`
  - `tests/unit/handlers/pre_tool_use/test_branch_creation_guard.py`
  - `tests/unit/handlers/session_start`
  - `tests/integration/test_branch_park_signed_commits_e2e.py`
- The whole suite was not run.

Result on the final tree: 2609 passed, 0 failed.

## Other

- Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/089-park-only-branch-stays-deletable.md`
  (**Plan**: 00617, **Audience**: client projects).
- Plan ticks: Tasks 1.1 to 2.3 are done. Task 3.1 is in progress: the note is
  added, and the peer team is told after the merge. Status is In Progress, in
  both PLAN.md and the README row.
- Swept from `/workspace` to clear `R-BRANCH-MERGED-POOL` before the branch
  could be created: `bin/hooks-daemon branch-sweep --clean --remote --apply`
  deleted `origin/agent-a06b94b562f54175e-c76ed9e2`, proven merged into main.
  Restore line: `git push origin 3cec4d7fc3d050f9808be49ce5684e65e05cc7bc:refs/heads/agent-a06b94b562f54175e-c76ed9e2`.
- **Behaviour change to flag:** an empty commit with `Parked-*` trailers made by
  hand, not by `branch-park`, no longer counts as a park commit. A branch that
  rested only on such commits returns to the merged or parked pool.
