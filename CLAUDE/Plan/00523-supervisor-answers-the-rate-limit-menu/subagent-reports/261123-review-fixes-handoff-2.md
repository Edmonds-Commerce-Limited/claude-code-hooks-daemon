# Plan 00523 review fixes: handoff 2 (context budget reached)

Worktree: /workspace/.claude/worktrees/agent-a64e490e6608e0f0a-c310ef8b
Branch: plan-00523-rate-limit-dialog, pushed at 67942b4fd. The working tree is clean.
Review: /workspace/untracked/agent-reports/261123-00523-independent-review.md
Handoff 1 (still valid for the remaining items): `261123-review-fixes-handoff-1.md` in this folder.

## Done since handoff 1 (each test-first, one commit, pushed)

- c0fd7f7f4, the re-parse bug. While `occurrence_open` is set, the stored window holds. Line ≈8985 no
  longer opens a new window on a re-parsed reset. `_load_rate_limit_state` no longer TTL-expires an
  open occurrence. Tests: `TestTakenOverDialogStaysTaken`.

- 36013aba6, I2. The module dict `_RATE_LIMIT_KEYS_SINCE_DUMP` (keyed by the state file name) is fed by
  `_note_human_keys`:

  - it is set by any key;
  - it is cleared by a chunk ending in `\r`, or by a dialog-free dump in a key-free tick;
  - a missing key means True (a fresh worker).

  A dialog first seen with keys pending, or in a typing tick, opens as `abandoned`. The autouse fixture
  seeds the latch False for the fake children. Tests: `TestKeysBeforeTheFirstDump`.

- 27f53c86a, I3/L4. The host helper `_rate_limit_apply_veto(outcome, *, stdin_pending, child_output_pending, shipped_dump)` is passed to `_apply_worker_outcome(..., apply_veto=...)`, a new optional parameter.

  - In the host loop, the dump is computed once as `shipped_dump`.
  - Stdin pending vetoes any rate-limit send.
  - An Enter is also vetoed if child output is pending, or unless the shipped dump shows selected == target.
  - Fails closed: the worker has already saved the state, and a vetoed send is not retried. This is host
    code, so it needs a ccy relaunch.
  - Note: an EOF stdin reads as readable, so it vetoes, which also fails closed.

  Tests: `TestApplyVeto`.

- 67942b4fd, I4. `_RATE_LIMIT_CONTEXT_ROW` requires the "You've hit your ... limit" row in the window
  above the title. Tests: `TestLimitRowRequired`.

- NOT done: the "changing dialog" option and pointer check from handoff 1. It is not on the task list,
  and it would break `test_arrow_never_enter_when_pointer_is_off_target`, which swaps option lists.
  Leave it out.

- Known edge, not fixed: `_sweep_rate_limit_states` deletes by mtime > 48 h, and the abandoned-hold path
  does not re-save the state. A dialog left on screen for more than 48 h could therefore be swept and
  answered when some other child's window opens. This is low; mention it in the docs or leave it.

## Left (per handoff 1, test-first, one commit each)

1. I5: placeholder `Try "…"` (straight or curly quotes) counts as empty, in `_rate_limit_resume_step`
   only, not in `rate_limit_composer_text`. First check how hooks-screen and `quiet_prompt` treat it.
2. L1: remove `_save_unrecognised_screen` and `_RATE_LIMIT_UNRECOGNISED_FILE`, and log a sha256 prefix plus
   the row count. Update `test_near_miss_screen_is_saved`, the test module docstring and the docs.
3. L2: clamp in `parse_rate_limit_reset`: `now-300 <= reset <= now+8d`, else None.
   - Adjust `test_date_with_year` to a nearer `now`.
   - Add tests for Feb 31, year 0000, year 9999 (with and without a zone; watch for `OverflowError`,
     which is not caught today) and a past year.
4. L3: an awaiting-human test in `TestResumeGates`. Find the real writer (`git grep -n AWAITING_HUMAN src`).
5. Run mypy on the touched files (copy the supervisor invocation from scripts/qa). Update
   `CLAUDE/development/CcySupervisor.md`, the release note
   (`git diff --stat main...HEAD`, `025-supervisor-answers-the-rate-limit-dialog.md`) and PLAN.md. Use
   journal entries only via `mkplan.bash --journal`.
6. Open a PR with `gh pr create`, titled 'Plan 00523: supervisor answers the rate-limit menu'. Keep the body
   short: what it does, the independent review and the fixes, and the relaunch caveat (the host-side dump
   and the apply veto). Use no closing keywords and no private paths. End with the attribution line.
   Do NOT merge.

## Commands

Run the targeted tests with
`PYTHONPATH=$PWD/src:$PWD timeout 300 nice -n 19 /workspace/.venv/bin/python -m pytest tests/unit/supervise/test_rate_limit_dialog.py -q -p no:cacheprovider --no-cov --color=no > untracked/scratch/rl.txt 2>&1`,
then grep for `passed|failed`.

The lint hook rejects a literal U+2019 in source; write `chr(0x2019)` instead.
