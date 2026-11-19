# Plan 00626 adversarial security review

Reviewed: branch `agent-a1a3bb91f50de1a35-3f001a4b` at `ae0aa114b` against `main` at
`ece88274e`. Verdict: **PASS**. No defect was found, so no code changed. I formed my own
view of the diff before reading the implementation report.

## Method

- Baseline: a detached worktree of `ece88274e`. Each side ran with its own `src` on
  `PYTHONPATH`.
- Corpus: `untracked/scratch/r626/corpus.py` (not committed) builds 31 scratch repositories.
  Each has a default named `trunk`, a bare remote and `origin/HEAD` set, unless a scenario
  needs otherwise. The proof cache is deleted before each side runs.
- Verdicts compared on each side, from `judge.py`:
  - `prove_remote_merged`, with `branches.default` set to `auto` and to `trunk`. Under
    `auto` the default comes from `resolve_default_branch`, which is what the sweep and
    `delete-branch` pass.
  - The PreToolUse handler's `_remote_delete_note`, for a batched `git push origin --delete a b`
    and for each `git push origin :name`.
  - For 9 of the scenarios, a dry run of `clean_sweep(..., remote=True)`.
- Cherry-picks use a different committer name. A pick made in the same second as its
  original would otherwise be the SAME commit, and the scenario would test nothing. That
  happened in the first pass; those scenarios were rebuilt and run again.
- No real remote was contacted, and nothing was deleted anywhere.

## Loosenings: main refused, the branch allows

All six come from the intended cherry route (`_HELD_PER_PATH` plus `git cherry`). Every one
is **justified**:

| Scenario                                                                                                         | Why nothing is lost                                                                           |
| ---------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| s01: interleaved cherry-picks, `trunk` edits the same file between picks, park and unpark markers on top         | Every patch is in `trunk`, and each file's final bytes exist in a first-parent `trunk` commit |
| s07b: as s01, but `trunk`'s copy of one INTERMEDIATE commit differs only in whitespace, including inside a token | Final bytes exact; see caveat 1                                                               |
| s10: a mode-only change (chmod) picked, then the file edited on `trunk`                                          | Mode and blob both checked                                                                    |
| s11: a rename picked, then the renamed file edited                                                               | Renames are off: the old path is absent and the new blob is held                              |
| s12: a binary file picked, then changed on `trunk`                                                               | Exact blob held                                                                               |
| s18: a submodule pointer (gitlink) picked, then bumped on `trunk`                                                | Mode `160000` and the exact sha are held                                                      |

The sweep dry run lists s01, s07b and s12 as provable remote deletes on the branch, and as
owner-only on main. That matches the handler.

**Caveat 1, already true on main and not new here.** A patch-id ignores whitespace. So an
intermediate branch commit whose content differs from the default's copy only in whitespace
(in s07b, `secret = abc` against `sec ret=a b c`) passes, and that intermediate version
survives only in the deleted branch's history. Main's single-commit `patch-equivalent` tier
accepts the same thing (s07: main allows it). The cherry route extends this to the per-path
case and adds no new class. The release note's phrase "closes the hole … a patch-id ignores
whitespace" is accurate for the branch's FINAL content only. I did not change it; a
one-clause clarification is optional.

## The same on both sides: refusals that hold

- s05: the branch restores bytes that the default held only BEFORE the merge base.
- s06: whitespace-only patch-id collision.
- s08: a revert on the branch (an empty net change).
- s09: a merge commit on the branch.
- s10b: a mode change that is not on the default.
- s13: a binary file that differs.
- s15: a non-park empty commit together with cherry-picks.
- s16: bytes held only on another remote branch.
- s17: bytes held only by a non-first-parent commit (a conservative refusal).
- s26: a deleted path that the default re-adds.
- s30: one branch commit split across two default commits.
- s20: `ls-remote` fails.
- s21: the remote branch is already gone.
- s29: a forged `unproven` cache entry (it can only refuse).
- s31: the ssh transport replaced by a hang, which in fact failed fast.

Two allows that are correct on both sides:

- s14: same content, different history (`content-preserved`).
- s27: the local default diverged, but the remote holds the merge.

## Tightenings: main allowed, the branch refuses

Each of these is a real defect on main, now closed:

| Scenario                                                                     | Main allowed it, losing                                  |
| ---------------------------------------------------------------------------- | -------------------------------------------------------- |
| s02: merged only into an UNPUSHED local `trunk`                              | the work; the sweep also listed it                       |
| s28: squash-merged only into the unpushed local `trunk`                      | the work                                                 |
| s04: remote `trunk` force-pushed back, `origin/trunk` stale                  | the work; the sweep also listed it                       |
| s23: integration line force-pushed back on the remote, tracking ref stale    | the work                                                 |
| s19: forged positive cache entry (`patch-equivalent`) for an unmerged branch | the work. Main TRUSTED the forged cache                  |
| s24: delete on `upstream`, whose default `dev` lacks the work                | the work. Main judged it against `origin/HEAD`'s default |

## Usability regression, intended and documented

- s22: default named `main` with no `refs/remotes/origin/HEAD` (a `git remote add` clone).
  Main allowed a genuinely merged branch. The branch refuses it, in the handler and in the
  sweep, with `git remote set-head origin --auto` named in the message. This is what the
  release note says.
- s24: the same message for a remote with no `HEAD` ref.

## Residual risk, the same on both sides and not a loosening

- s03 and s03b: a STALE `origin/HEAD` after the remote renamed its default (`master` to
  `trunk`).
  - s03: work merged only into the old `master` is provable on both sides. The remote
    still holds that work on `master`, so nothing is lost at once.
  - s03b: a delete of the real default `trunk` is denied by the handler on both sides. The
    raw proof would accept it, because it judges against `master`.
  - The implementation report already names this residual. Closing it needs a
    `git ls-remote --symref <remote> HEAD` check in the same listing.
  - Recommendation: a follow-up plan, not a blocker.
- Positive cache entries are still read by `branch_creation._proven_refnames`, the
  merged-pool count. A forged entry can move a branch between the WIP and merged pools, but
  it authorises no delete. This was already true on main.

## Fail-closed checks

- `ls-remote` failure (s20, s31) refuses.
- A missing remote branch (s21) refuses.
- A missing tracking default or missing `origin/HEAD` refuses.
- `ProofUnavailableError` is never cached.
- A tracking ref moved locally is refused by the live anchor check (s04, s23).
- I did not reproduce a true `ls-remote` timeout: the hanging ssh command failed fast. That
  path shares the failure branch of `list_remote_refs`.

## QA and process

- `ruff check`, `black --check` and `mypy` on every changed Python file: clean.
- The RED commit `bc8336e20` used `--no-verify`. The final tree is clean.
- Release note `003-remote-delete-proof-remote-default-and-cherry-route.md`: it matches the
  observed behaviour. One wording point: "Local deletes (`delete-branch`, …) are unchanged"
  is true of the local delete. `delete-branch`'s printed remote-delete advice
  (`remote_delete_advice`) does follow the new proof.

## Left

- A follow-up for the live `HEAD` symref check (stale `origin/HEAD`).
- Optional: tighten the release-note wording on whitespace and on `delete-branch` advice.
