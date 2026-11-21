# Task 4.4 report: pools are counted per owner

Branch `plan-00594-task-4-4-owner` (from main after Task 4.2). DESIGN section 2.2.

## What changed

- `core/branch_inventory.py`
  - New `BranchState.FOREIGN`, in no pool (`pool_of` is None) and in `_UNGROUPED` (no same-tip grouping).
  - New `OwnerRule` (lazy, one git read per pass, only for remote-only branches): (1) a `hooksDaemonCreator` record in this clone (one `git config --get-regexp`, dotted branch names handled); (2) a local ref, or a remote tip whose author email equals `git config user.email` (case-insensitive); (3) otherwise foreign. No `user.email` means an unrecorded remote-only branch is foreign.
  - `_record` wraps the old classifier (`_classify`) and turns a non-mine branch into FOREIGN. The ref listing now reads `%(authorname)` and `%(authoremail)`. `BranchRecord` gains `author`, `author_email`, `proof_state` (the done state it was proven in) and a `cleanup_state` property.
  - `bot_owned` and the never-work names are untouched and take precedence.
- `core/branch_creation.py`: the guard reads refs itself, so it now reads the author email and drops foreign refs (`_owned_refs`, same `OwnerRule`) before pooling. Foreign branches no longer fill the cap, dormant, parked or merged pools, and so never appear in a fix command.
- `core/branch_sweep.py`: new `Foreign` group (age, author, proven state), `group: "foreign"` in `--json`, new JSON keys `author` and `author_email`.
- `core/branch_cleanup.py`: the remote-delete candidate filter uses `cleanup_state`, so `--clean --remote` still deletes a PROVEN-merged foreign branch; unproven foreign branches are never touched. Local cleanup needs a local ref, which a foreign branch never has.
- Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/050-branch-pools-are-counted-per-owner.md`; `docs/guides/CONFIGURATION.md` paragraph.

## Tests (seen failing first)

New `tests/unit/core/test_branch_owner.py` (17 tests): 12 failed before the implementation (no `FOREIGN` state, no `foreign` group, foreign branches counted in the open and merged pools, `branch-park theirs` offered), 17 pass after.

Existing fixtures that fabricate remote-only branches now declare the clone's `user.email` to match the commit author (park, keeps, creation, inventory, remote-delete-lines tests); `test_event_budgets` fake ref rows gained the new author field. No assertion was weakened.

## QA

`run_autofix.sh`, then `llm_qa.py changed --base main --allow-unmapped`: 41/42, the one failure being the event-budget fake rows (fixed, rerun 43 passed). `pyright` on the changed files: 0 errors. The four core branch modules are "too-broad" unmapped (allowed); the coordinator's full gate must cover them.

## Open items

- The email rule is weak evidence for seats sharing one identity (DESIGN review note); the explicit `branches.unowned` pool with a configured owner is NOT implemented, only the base rule.
- Foreign branches get no stop or session-start pressure at all; the review's "pressure to a configured owner" is future work.
- `branch-keep` on a proven-merged foreign branch is refused (state is foreign).
- Author identity from `GIT_AUTHOR_EMAIL` in the environment is not consulted, only `git config user.email`.
