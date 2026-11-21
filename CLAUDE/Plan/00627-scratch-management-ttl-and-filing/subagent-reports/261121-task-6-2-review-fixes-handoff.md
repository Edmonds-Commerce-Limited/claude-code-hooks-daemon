# Task 6.2 review fixes: handoff

Branch `agent-acff915e4bf3b86e6-0a26f829`, all commits pushed. The details are in the JOURNAL entry `JOURNAL/2026-11-21/152949Z-action-0db516.md`.

## What was done (red test first for each item)

1. **F-BYPS L1** (`44c377289`, `bd31c5231`): `cmd_worktree_reap` reads every keep predicate again in four places:

   - after a yes and before packing, through `evacuate_scratch(recheck=...)`;
   - after packing, with the blockers, before `reap_worktree`;
   - for every later worktree once a question has been asked;
   - for the holds, before `--reap-branches` prunes an orphan. This one was not in the review.

   The predicates are a fresh worktree state (new `/proc` scan), the running holds and the git locks. A failed `git worktree list` for the lock read now keeps the worktree.

   Background records of both checkouts are re-read per entry by `entry_live`, and a test pins that. The tests are in `tests/unit/daemon/test_worktree_evacuate_rechecks.py`.

2. **D-EXEC L1** (`7b3050388`): `shlex.quote` is applied to the worktree name in two places, `worktree_evacuate.human_command` and the same defect in `core/agent_ownership.py`'s harness-directory hint. The restore line's archive id is now quoted too. `cleanup_after_merge` prints only a literal `<name>`, so it needed no change.

3. **F-BYPS L2** (final commit): recorded as two `UNCOVERED-accepted` rows in `scripts/qa/dangerous-invocation-corpus.yaml`, with verdicts measured through the real chain:

   - `pty-answers-worktree-evacuation`
   - `pty-answers-scratch-apply`

   It is accepted under the threat model, not by owner ruling. DESIGN.md section 11 references both rows, and so do the section 13 F-BYPS F2 and Task 6.2 rows.

## For the coordinator to decide

- **CLAUDE/Security/README.md got no row, on purpose.** That file holds categories only ("a single finding is an instance recorded under its category, never a row of its own"). For an accepted instance, its convention is an `UNCOVERED-accepted` corpus row under the unenumerated-spelling category. You can overrule this.
- **Counts were already stale before this change, and I left them.** `CLAUDE/Security/UnenumeratedSpelling.md` says "29 rows" and README.md says "14 of its 20 rows"; the corpus has 79 rows.

## Targeted QA run

- black, ruff and pyright on every touched file: clean.
- `error_hiding`, `semgrep`, `dangerous_invocation_corpus`, `docs_qa`: clean.
- `plan_qa`: 0 block, 1 advise.
- Touched tests: `test_worktree_evacuate*.py`, `test_cli_worktree_reap*.py`, `test_agent_ownership.py`, `test_branch_cleanup_agent_owned.py`, `test_branch_stop_gate.py`, `test_cleanup_after_merge*.py`, all passing.
- The full gate was not run.
