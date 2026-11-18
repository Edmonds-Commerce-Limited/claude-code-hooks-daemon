# Plan 00622 fix round 2: the loosening review's D1 and D2

Branch `agent-a7abfb6e215f8a166-1ad7f937`. Pushed; not merged to main.

- `a74dabe94` merges main into the branch. It carries no trailer and cannot be amended.
- `ca5ba5d35` is the RED commit.
- `43fb88b57` is the GREEN commit.

The import path was confirmed with `PYTHONPATH=<worktree>/src`, which resolves `claude_code_hooks_daemon` to the worktree's `src/`.

## D1: empty commits widened patch-equivalence

**Fix.** `patch_equivalent` (`daemon/branch_safety.py`) again drops only the park writer's markers (`walked.parks`), as it did before Plan 00622. It no longer drops every empty commit (`walked.empties`).

Empty commits are now excused only by the two lossless tiers:

- `empty-commits-only`: the tip's tree is in the default's history.
- the net-change proof: `content-preserved` locally, and the remote proofs.

**Deliberate consequence.** A byte-identical cherry-pick with an empty commit on top is refused on the hook path, which has only patch-ids. It still passes `delete-branch` and the remote proofs as `content-preserved`. The test `test_a_cherry_picked_branch_with_a_plain_empty_commit_passes_the_net_change_route` pins this split.

## D2: replace refs and grafts

**Fix.** `utils/git_repo._child_environment` now pins two variables on every daemon git call:

- `GIT_NO_REPLACE_OBJECTS=1`
- `GIT_GRAFT_FILE=/dev/null/no-grafts`

Both are applied after the caller's `env`, so no caller can undo them.

**Measured on git 2.47.3:** neither `GIT_NO_REPLACE_OBJECTS` nor `--no-replace-objects` disables `info/grafts`, so the graft file needs its own override.

- A path beneath `/dev/null` cannot exist, so git silently reads no grafts.
- `/dev/null` itself also works, but it prints the deprecation hint.
- Probe script: `untracked/scratch/00622-fix2/graft_probe.sh`.

**Why global rather than per-proof.** It is one place, and it covers every proof call site, `holder_of`, and the delete itself.

**Failure handling.** Every walk read already failed closed (shown in the reviewer's probes). The pin adds no new failure mode: a missing graft file is not an error.

## Tests

**RED (`ca5ba5d35`).** These failed against round 1:

- the whitespace-only pick plus an empty commit
- the orphan whitespace twin plus an empty commit
- a content commit replaced by an empty-looking one, with any message and with the park writer's message
- the default tip replaced so it descends from the branch
- a legacy `info/grafts` entry doing the same
- 4 `run_git` environment tests

All of them pass at GREEN.

**Correction to round 1.** Round 1 broke 12 tests in the `R-GIT-PUSH-DELETE-REMOTE` suites (`test_destructive_git_remote_delete_{merged,chained,lines}.py`). Its report did not list them.

- Their fixtures modelled unmerged work as `--allow-empty` commits, which `empty-commits-only` now correctly treats as lossless.
- Those fixtures now commit a file through the new `tests.support.git_fixtures.commit_content`. No assertion changed.
- Journalled as a `correction`.

**Targeted run.** 76 test files, every one that calls the proofs or `run_git`: 3290 passed and 12 failed (the fixtures above). After the fixture fix, the three files plus the new tests gave 169 passed.

**Targeted QA.** All 7 checks passed:

- format (auto-fixed 3 files, then 0 to reformat on a still tree)
- lint
- error_hiding
- type_check
- pyright (0 errors)
- magic_values
- british_english

## Corpus

Files are in `corpus/`: `p622-corpus-{before,after,compare}-r2.*`.

- The before side was re-recorded with `PYTHONPATH` at main's `src`.
- 9 shapes were added, all labelled N.
- That gives 57 shapes x 4 proofs = 228 decisions.

**Results:**

| Result                                    | Count                                                                                                               |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| DENY to ALLOW on a content-carrying shape | **0**                                                                                                               |
| DENY to ALLOW, total                      | 18, all lossless                                                                                                    |
| ALLOW to DENY                             | 12: `r2-replace-main-tip`, `r2-graft-main-tip` and `r2-replace-content-park-msg`, on all 4 proofs (tightened by D2) |
| ALLOW on N, before and after alike        | 6: `r2-ws-pick-bare`, `r2-orphan-ws-bare` and `r2-ws-pick-writer-park`, on the local and local-hook proofs          |

The 18 lossless flips:

- 13 on Y shapes: `s-many-empty`, `s-plain-empty-ff` and `s-plain-unpark-merged` on all 4 proofs, plus...
- ...5 on E shapes: `s-pure-empty` on all 4 proofs.
- `s-pure-empty-main-empty` on remote and guard.
- Round 1's `s-pick-empty` local-hook flip is gone.

The 6 ALLOW-on-N decisions are an older weakness of patch-ids, which ignore whitespace. Plan 00622 does not widen it. The writer-park case predates this plan (Plan 00617). The remote proofs refuse all three shapes. It is ledgered as **N660** in Plan 00474's `NIGGLES.md` rather than fixed here, because closing it changes the patch-equivalent tier itself.

## Reviewer probes re-run

Output is in `untracked/scratch/00622-fix2/`: `fix2.json`, `fix2*.log`. The reviewer's files were left untouched.

| Probe                                       | Result after round 2                                              |
| ------------------------------------------- | ----------------------------------------------------------------- |
| `ws-pick-empty`                             | DENY on every path                                                |
| `orphan-ws-empty`                           | DENY on every path                                                |
| `replace-hides-content`                     | DENY on every path                                                |
| `replace-park-msg`                          | DENY on every path (it was `park-carried` even before Plan 00622) |
| `root-same-tree` (E, lossless)              | back to DENY, as before Plan 00622                                |
| Every other probe                           | same as the reviewer's after-run                                  |
| Controls (`ws-pick-bare`, `orphan-ws-bare`) | still `patch-equivalent` locally (the N660 weakness)              |

## Docs, journal, ledger

- Release note `002-...` narrowed:
  - patch-ids never excuse an empty commit
  - the hook path refuses a pick plus an empty commit
  - replace refs and grafts are ignored daemon-wide
- Journal entries: `decision`, `finding` and `correction` (the correction is referenced to round 1's 16:28 decision).
- N660 has been added to `CLAUDE/Plan/00474-niggles-ledger-seventeen/NIGGLES.md`. A concurrent ledger write could collide on the number at merge.

## Notes

- **Commit trailer.** The brief asked for a Sonnet trailer. These commits carry `Co-Authored-By: Claude Opus 5.5`, because that model wrote them and the harness attribution names it.
- **Left open.** The independent re-review of round 2 has not been done. Neither has the coordinator's full QA gate.
