# Plan 00622 loosening review: adversarial, read-only

Branch reviewed: `agent-a7abfb6e215f8a166-1ad7f937` (`git diff main...HEAD`, fix commit `a9bb1177d`).
Before/after was compared by running the same probes with `PYTHONPATH` at the main checkout's `src` (pre-fix) and at the branch worktree's `src` (post-fix).
The implementer's report was read only after these findings were formed.

Probe scripts and their raw output are in `untracked/scratch/00622-review/`:

- `probes.py`: structural shapes. The outputs are `before.log` and `after.log`.
- `probes2.py`: fail-closed checks, the cache, shallow clones, orphans and unpushed main.
- `probes3.py`: a whitespace-equivalent cherry-pick.

Every repository is synthetic.

## Verdict

**FAIL: 2 defects.** Both let a branch that holds content the default branch lacks go from DENY to ALLOW. In both, the root cause is older than this change: `git cherry` patch-id equivalence, and replace refs being honoured. The change makes each one reachable for many more branches.

The core rule is sound: an empty commit is a single-parent commit whose tree equals its parent's tree. The walk in `_walk_shape` is correct for merges, octopus merges, `-s ours` merges, root commits, mode changes, gitlink changes, revert pairs and shallow cuts. No git read failure now passes; every one I injected fails closed.

## Findings (severity-ranked)

### D1 (Medium): `patch_equivalent` now ignores every empty commit, so a whitespace-only difference that patch-id cannot see becomes deletable

- **Where:** `src/claude_code_hooks_daemon/daemon/branch_safety.py:634`. The line is `unique = [sha for sha in unique if sha not in walked.empties]`. `classify_branch` reaches it at `:816-825`, before the content tier runs.

- **Probe:** `probes3.py`.

  - The branch commits `f.py` containing `return  1  ` and adds one empty `Unpark branch` commit.
  - `main` commits the same change with the whitespace cleaned up, as a formatter does during a cherry-pick.
  - The branch's blob is not in main's history (verified with `rev-list --objects main`).

- **Observed:**

  | Shape                                       | Before                     | After              |
  | ------------------------------------------- | -------------------------- | ------------------ |
  | `ws-pick-empty`                             | local DENY, hook DENY      | `patch-equivalent` |
  | `orphan-ws-empty`                           | DENY                       | `patch-equivalent` |
  | `ws-pick-bare` (control, no empty commit)   | already `patch-equivalent` | `patch-equivalent` |
  | `orphan-ws-bare` (control, no empty commit) | already `patch-equivalent` | `patch-equivalent` |

  - `ws-pick-empty` ends in `git branch --delete --force`, and the whitespace content is lost.
  - `orphan-ws-empty` is an orphan root with no merge base. Its `base.txt` differs from main's only by trailing whitespace, and an empty commit sits on top.
  - The remote proof stays DENY in all four shapes, because there `patch_equivalent` only names the tier after `holds_net_change` has proven the content.

- **Why:**

  - `git cherry` compares patch-ids, and a patch-id ignores whitespace. With no merge base, `git cherry` compares against the whole history (the inventory's `_pair_facts` already guards that case; `patch_equivalent` does not).
  - Before this change, any empty commit that was not a park commit stayed in the unique list. That accidentally refused these branches.
  - After this change, any empty commit, of any message, opens the hole. Before, only the park writer's markers did.

- **Why the tests miss it:**

  - `test_a_file_one_byte_different_from_mains_with_an_empty_commit` uses a non-whitespace byte, which patch-id does see.
  - No test pairs an empty commit with a whitespace-normalised or orphan cherry-pick.
  - The corpus has no whitespace shape and no orphan shape.

- **Fix direction:**

  - Do not let `patch-equivalent` stand alone in `classify_branch`. Also require `holds_net_change`, as the remote path does, or the blob/net-change check.
  - At minimum, refuse it when there is no merge base.

### D2 (Low-Medium): replace refs fool the walk; a content commit replaced by an empty-looking object is now deletable with any message

- **Where:** `src/claude_code_hooks_daemon/core/branch_park.py:302`, the `git log --boundary` call in `_walk_shape`. `run_git` (`utils/git_repo.py:175-193`) neither sets `GIT_NO_REPLACE_OBJECTS` nor passes `--no-replace-objects`.
- **Probe:** `probes.py::p_replace_hides_content`.
  - Commit C adds `secret.txt`.
  - `git replace C C'` swaps in C', which has C's parent's tree and the message `note`.
- **Observed:**
  - Before: DENY on all paths.
  - After: `empty-commits-only` on the remote, local and local-hook paths.
  - `git --no-replace-objects show` confirms that the real tip still adds `secret.txt`, on both the clone and the bare remote, and that main never holds it.
  - Deleting the branch leaves C unreachable, because the replace ref keeps only C' alive.
- **Pre-existing:** `p_replace_park_msg` is already `park-carried` on main when the replacement carries the park writer's trailers. Replacing main's tip so that it appears to descend from C would likewise fool the `merged` tier.
- **What this change adds:** before, the replacement had to forge the writer's trailers. Now any message works.
- **Why the tests miss it:** no test uses `git replace` or a graft.
- **Fix direction:** run every proof git call with `GIT_NO_REPLACE_OBJECTS=1`, once, in `run_git`'s proof callers, or globally.
- **Grafts:** `replace --graft` can only change parents. My probe `p_graft_parent` stays DENY, as expected, because the chain must still end on a boundary whose tree equals the tip's.

## Probes that held (no defect)

| Probe                                                                         | After              | Note                                                                                                                             |
| ----------------------------------------------------------------------------- | ------------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| Change + revert + empty; change, empty, change back                           | DENY               | non-empty commits break the all-empty walk                                                                                       |
| Octopus merge with first parent's tree; `-s ours` merge + empty               | DENY               | `len(parents) == 1` required                                                                                                     |
| Root commit with new content + empty                                          | DENY               | a root has no parent tree                                                                                                        |
| Mode change + empty; gitlink (submodule pointer) change + empty               | DENY               | tree ids include mode and gitlink sha                                                                                            |
| Content commit named with the park message; Unicode-lookalike trailer message | DENY               | the empties rule never reads messages; the residue rule is unchanged                                                             |
| Shallow clone (depth 1) of content + empty                                    | DENY               | the shallow commit shows no parents, so it is not empty                                                                          |
| skip-worktree / sparse                                                        | n/a                | index flags never reach a commit tree; branches in worktrees are refused earlier                                                 |
| `git log` rc 1/124/128 (injected)                                             | DENY on all paths  | remote raises `ProofUnavailableError`, which is not cached; proves after git recovers                                            |
| `git log` rc 0 with the boundary lines dropped                                | DENY               | parent not in `trees`, so not empty                                                                                              |
| `log.showSignature=true`                                                      | DENY (fail closed) | extra lines break the 4-field parse. This is a false DENY, not a loosening                                                       |
| merge-base failure (injected)                                                 | remote DENY        | local still proves via the walk, which needs no merge base; correct                                                              |
| Stale v3 cache entry `merged` for a content branch                            | DENY               | the v4 key never matches v3, and v3 keys are pruned                                                                              |
| TOCTOU                                                                        | unchanged          | the local tier carries the tip sha and `_tip_moved_reason` re-checks it; the remote delete uses `--force-with-lease=<ref>:<tip>` |

Two of these are worth noting even though they are not defects.

**Improvement.** Before the change, an injected `git log` failure caused `unproven` to be cached (`log-rc-*-cache-after`). After, nothing is cached.

**Informational, older than this change:**

- **Cache.** A forged v4 cache entry with any tier string, even `anything-at-all`, ALLOWs the remote delete. `_load_cache` validates the type but not the tier value. On main, a forged v3 `merged` entry does the same.
  - This is not new: the cache is a trusted local file.
  - Cheap hardening: accept only known tier names.
- **Unpushed local main.** `empty-over-unpushed-main` is now `empty-commits-only` on the remote path. Here the branch is L + empty, where L is a content commit that exists only in the unpushed local `main`.
  - This is consistent with existing policy. The control `unpushed-main-ancestor-control` (the branch at L) is `merged` before and after, because local `main` is a default proof target.
  - The content survives locally.

## The implementer's 19 DENY-to-ALLOW flips

I checked each corpus shape in `corpus/p622_corpus.py`. All 19 are genuinely lossless: only empty commits' messages are lost.

| Shapes                                                      | Flips  | Why lossless                                                                                                                                                  |
| ----------------------------------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `s-many-empty`, `s-plain-empty-ff`, `s-plain-unpark-merged` | 4 each | the content is merged or fast-forwarded into main, then only empty commits follow                                                                             |
| `s-pick-empty` (local-hook)                                 | 1      | both content commits are cherry-picked byte-identical, and one empty commit follows. The full local and remote paths already allowed it via content-preserved |
| `s-pure-empty`                                              | 4      | a single empty commit off main; its tree is in main's history                                                                                                 |
| `s-pure-empty-main-empty`                                   | 2      | remote and guard only. The local paths already allowed it, because `git cherry` matched the empty patch against main's own empty commit                       |

The corpus's claim of 0 flips on N shapes holds for its own shapes. It misses D1 and D2 because it has no whitespace-normalised pick, no orphan pick and no replace refs.

## Compared with the implementer's report

The report's description of the rule, the fail-closed paths, the cache bump and the 19 flips matches what I observed.

It states that `patch_equivalent` "drops every empty commit from git cherry's unique list". It does not consider that this widens the reach of `patch-equivalent`'s existing whitespace and no-merge-base weakness (D1). It also does not consider replace refs (D2).
