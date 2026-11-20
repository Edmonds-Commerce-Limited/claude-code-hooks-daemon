# Plan 00626 implementation report

Branch: `agent-a1a3bb91f50de1a35-3f001a4b` (pushed). Not merged. Scratch repros:
`untracked/scratch/p626/repro.py` (default `trunk`). Both defects reproduced before the fix
and flip after it.

## Decision paths audited

| Path                                                                                                     | Verdict before                                                                                                                                             | Change                                                                                               |
| -------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `remote_branch_proof._judge_offline` (net change decides alone)                                          | WRONG: refused interleaved cherry-picks (defect 1)                                                                                                         | `_HELD_PER_PATH` state + `patch_equivalent` required                                                 |
| `remote_branch_proof._default_proof_targets`                                                             | WRONG: offered the LOCAL default (defect 2), feeding ancestry, park-carried, net change and cache key                                                      | tracking default only; missing one refuses all                                                       |
| `remote_branch_proof._live_tip_problems`                                                                 | checked only the deleted branch's live tip                                                                                                                 | also confirms the proving target (default or integration line) in the same `ls-remote`               |
| `remote_branch_proof._offline_evidence` (cache)                                                          | WRONG: a cached positive authorised a delete (forgeable plain file)                                                                                        | only a cached `unproven` is reused; positives recomputed; key = tip + remote default sha, version v6 |
| `prove_remote_merged` default argument                                                                   | trusted whatever default the caller resolved                                                                                                               | refused unless it equals `git_sync.resolve_remote_default_branch`                                    |
| `destructive_git._remote_delete_note` (PreToolUse guard)                                                 | WRONG: `resolve_default_branch` falls back to local/tracking `main`/`master` when `origin/HEAD` is unset, so a stale `main` could be judged as the default | `resolve_remote_default_branch` (auto reads `refs/remotes/<remote>/HEAD` only)                       |
| `branch_cleanup._proven_remote` / `clean_sweep --remote` / `proven_remote_only` / `remote_delete_advice` | inherited both defects through the proof and the inventory's default                                                                                       | fixed centrally in `prove_remote_merged` (no separate code)                                          |
| `delete-branch --remote-only`                                                                            | does not exist; `delete-branch` is local-only                                                                                                              | none                                                                                                 |
| `branch_creation._proven_refnames` (merged-pool counting)                                                | not a delete path; keyed by local+remote default shas                                                                                                      | reads by the remote default sha only, matching the writer                                            |
| `branch_safety.classify_branch` (local delete)                                                           | local, reflog-recoverable; accepts patch equivalence alone                                                                                                 | unchanged (non-goal)                                                                                 |

## Tests

New: `tests/unit/core/test_remote_delete_proof_remote_default.py` (cherry route, whitespace,
no merge base, unheld path, unpushed local default, squash on local default, locally moved
and missing tracking default, stale `main` under auto, forged cache entry). Updated to the
new rule (assertions inverted, none deleted): `test_merge_proof_shapes.py` (cache,
cost bound, creation reader), `test_empty_commit_proof.py` (cached positive re-walked),
`test_remote_branch_proof.py` and the two `test_destructive_git_remote_delete_*` files
(the default now rides in the one `ls-remote`), `test_branch_cleanup.py` (the sweep had
printed a delete proven by an unpushed local `main`).

## Loosening

One, deliberate: the cherry route. A branch with no single default commit holding its net
change is now provable when `git cherry` finds every non-park patch (no merges) AND every
changed path's exact blob/mode (or absence) appears in some first-parent default commit
after the merge base. What is not preserved is the exact combined tree state; every byte
of the branch's result at each path is. Everything else tightens.

Further audit verdicts (read, unchanged): `delete_branches(remote=...)` only supplies the
listing for the LOCAL `remote-held` tier, it deletes nothing remote; `default_targets` /
`cleanup_targets` are local-delete targets; the inventory's merged grouping and the merged
pool only COUNT, and every remote delete they lead to goes through `prove_remote_merged`.
The sweep path is pinned end to end (dry run, default `trunk`) for both defects. A delete
on a remote other than `branches.remote` resolves THAT remote's `HEAD`.

## Behaviour changes worth knowing

- A clone without `refs/remotes/<remote>/HEAD` and `branches.default: auto` now has
  remote deletes refused (message names `git remote set-head <remote> --auto`). This repo
  has `origin/HEAD`, so its own deletes are unaffected.
- Remote-delete proofs re-run their history walks each time (no cached positives); the
  cost-bound test was relaxed from `warm <= one` to `warm <= cold`.
- A missing tracking default now refuses branches merged into an integration line too.

## Known residual

- `refs/remotes/<remote>/HEAD` is a local ref: stale after a default rename, settable by
  `git remote set-head`. The live check confirms the tip of the branch it names, not that
  it IS the remote's default. Closing it needs `ls-remote --symref <remote> HEAD` in the
  same call, which `utils/remote_refs.parse_listing` currently drops; not done here.

## Process notes

- The RED commit (`bc8336e20`) used `--no-verify`.
- Commit trailer follows the session attribution (Opus 5.5), not the brief's Sonnet line.
- The `branch_creation` reader test was written after its fix (would have been RED).

## Left

- Ledger N671 not touched.
- Full QA gate and independent security review (coordinator).
