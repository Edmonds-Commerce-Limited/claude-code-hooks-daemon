# Plan 00618 Task 1.2 rework: B-2 after review F1/F2, and the B-1 timeout nit

Branch: `worktree-plan-00618-b1-b2` (pushed, not merged). Follows `261116-fix-b1-b2.md`; answers the independent review in `untracked/scratch/review-618-b1b2.md` (F1 high, F2 medium, B-1 LOW timeout nit). B-1's tier logic and N-16 are untouched.

## Commits

| Commit      | What                                                                                          |
| ----------- | --------------------------------------------------------------------------------------------- |
| `9111cee6c` | B-2 rework red tests (34 failing on the previous tip `4bd23dca7`)                             |
| `d4aa70de7` | B-2 rework fix, `StopJudgement.own` comment, release note 089                                 |
| `53a60290f` | B-1 nit red test (net-change proof saw a 5 s budget, not the scaled one)                      |
| `09f149d7c` | B-1 nit fix: `holds_net_change(..., timeout=)`; `delete-branch` passes the load-scaled budget |

The red commit message says "39 combinations"; the differential actually has 54 (3 touch kinds x 18 place/lock/queue/dirty cases).

## B-2: the behaviour now

`core/branch_stop_gate.py::_owned_branches` is origin/main's formula with one change: `ownership_refusal(..., harness_directory=name not in own)`.

- **Branch the stopping thread did not touch:** handed over exactly as on origin/main, on a running queue record, a git lock, or a worktree under `.claude/worktrees/`. Live sub-agents no longer draw denials, so they cannot spend `MAX_STOP_BLOCKS` (F1 closed).
- **Branch the stopping thread touched (`judgement.own`):** handed over only on a running queue record (branch or worktree) or a git lock. The harness directory alone does not hand it over. The original B-2 reproduction (main-thread touch, worktree at `.claude/worktrees/x`, dirty and unpushed) is judged. An own branch with a lock or queue record is handed over as on origin/main (F2 closed).
- **Worktrees cannot be listed:** returns `holds.branches` as origin/main did. The previous tip subtracted `own` here; that is gone.

## Tests (`tests/unit/core/test_branch_stop_gate.py`)

- `TestHandedOverToHarnessWorktrees`: the unlocked harness hand-over test is restored, and survives `MAX_STOP_BLOCKS + 1` stops with no abandonment. The sub-agent's own stop is still judged, with an unlocked worktree.
- `TestTheSessionsOwnBranchIsHandedOverOnlyOnAHold`:
  - The reproduction is judged with both findings.
  - Lock -> handed over. Queue record -> handed over, including when the worktrees cannot be listed.
  - A branch both threads touched is judged when it is only under the harness directory, and handed over when it has a queue record.
- `TestDifferentialAgainstOriginMain` (54 cases: touch sub / main / both x place harness / plain / none x lock x queue x dirty). The baseline is origin/main's `_owned_branches`, reproduced in the test (`_origin_main_owned`) and monkeypatched into the real `decide_stop`. Each case asserts two things:
  - (a) if origin/main refuses the stop, this tree refuses it;
  - (b) `handed(now) == handed(origin/main) - {branch if own-touched and not queued and not locked}`.
- `TestReviewScenarioOne` replays probe_stop.py scenario 1 against this tree and the origin/main baseline, each with its own state, interleaved:
  - the refusal sequences are equal, `[allow, allow, allow, BLOCK, BLOCK]`;
  - stops 4 and 5 deny on `own-b: dirty worktree` as Block 1 and Block 2 of 3, and do not name `agent-x`;
  - `agent-x` is handed over on every stop.
- The reviewer's `probe_stop.py`, re-run on this tree's `src`, matches the origin/main column on all 5 scenarios: s1 ALLOW x3 then BLOCK 1/3 and 2/3; s2, s3 and s4 ALLOW (handed over); s5, the sub-agent's own stop, BLOCKs.

## Residual risk (by design, for the coordinator)

The only extra denials are on branches the stopping thread touched that have no queue record and no lock. Example: the coordinator wrote into a live harness sub-agent's worktree (a brief, a `git -C <wt> commit`) and did not lock it. Such a stop is denied where origin/main allowed it. Those denials share the session's never-reset `MAX_STOP_BLOCKS` budget, so if that branch stays outstanding, a later genuinely abandoned own branch can still be waved through after 3 blocks. The brief accepts this: requirement (2) asks for it, and those are branches the coordinator worked on itself.

To remove even that residue, a follow-up could choose either option the review listed:

- do not count stops whose blocking findings are all on harness-only branches;
- reset the counter when a stop is allowed.

Neither is done here, because both change the give-way rule, which this brief did not ask for. The pre-existing fail-open paths the review lists are also unchanged: unreadable touch records, inventory failure, `judgement.incomplete` ignored, and an exception in `decide_stop`.

## B-1 LOW nit: net-change proof budget

`remote_branch_proof.holds_net_change` and its helpers (`_net_change`, `_tree_entries`, `_tree_holds`, `_touching_commits`) now take a `timeout`. The public function defaults to `Timeout.GIT_CONTEXT`, so the remote-delete hook path is unchanged. `branch_safety._net_change_held` passes `scaled_timeout(Timeout.GIT_BRANCH_SAFETY, Timeout.GIT_BRANCH_SAFETY_MAX)`, the same budget as `branch_safety._git`. A timeout is still a non-zero rc -> `ProofUnavailableError` -> `unproven` (fail closed).

Test: `TestTheContentTierNeedsTheNetChange::test_the_net_change_proof_runs_on_the_load_scaled_git_budget` records every `remote_branch_proof.run_git` timeout under a patched `scaled_timeout`. It was red before the fix (it saw `{5}`).

## Release note

`089-delete-branch-and-stop-guard-no-longer-lose-work.md`: the stop-guard paragraph now describes the final rule. The harness-directory signal no longer hands over a branch the stopping thread touched. Such a branch is handed over only on a queue record or a lock. Other branches are handed over as before, so sub-agents do not spend the coordinator's blocks.

## QA

- `./scripts/qa/run_autofix.sh`: clean, no changes.
- `llm_qa.py magic_values format lint type_check error_hiding fail_open_inventory docs_qa`: 7/7 passed.
- Tests by path with the worktree venv (835 passed):
  - stop gate and stop guard (core and both handlers);
  - `agent_ownership`, `branch_safety`, `cli_delete_branch`, `cli_session_state`, `cli_worktree_reap_branches`;
  - `remote_branch_proof`, `remote_archive_proof`, `merge_proof_shapes`, `branch_cleanup`, `branch_cleanup_bulk`;
  - `tests/integration/test_claude_md_guidance_coverage.py`.
- The `destructive_git` remote-delete, branch-delete and remote-ref handler tests also pass (159).
- Not run: the full suite and `llm_qa.py all`.
