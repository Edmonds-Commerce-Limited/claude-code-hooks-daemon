# Plan 00622 loosening review, round 2: adversarial, read-only

Branch reviewed: `agent-a7abfb6e215f8a166-1ad7f937` (`git diff main...HEAD`, round-2 fix `43fb88b57`).

**Method.** Probes were run with `PYTHONPATH` pointed at three source trees:

- the branch worktree's `src`;
- main's `src`, exported with `git archive main`;
- round 1's `src`, exported from `a9bb1177d`.

An import check confirmed that the branch run loaded the worktree's package. All repositories are synthetic and live under `untracked/scratch/00622-review2/`.

The worktree was not edited; `git status --porcelain` is empty.

**Targeted tests.** These 7 files were run on the branch: `test_empty_commit_proof`, `test_merge_proof_shapes`, `test_park_commit_classifier`, the three `test_destructive_git_remote_delete_*` files and `test_git_repo`. Result: 238 passed, with `PYTHONPATH=<worktree>/src` so that the source-tree guard accepts the run.

**Probe scripts:**

- `probes4.py`: replace and graft variants, shallow, commit-graph at the tip, lines, merge shapes and cache seeding.
- `probes5.py`: commit-graph below the tip, alternates, object-directory environment variables and a moved live tip.
- `cgpark.py`: commit-graph forgery combined with the park writer's message.
- `p660.py`: the whitespace shapes.

## Verdict

**FAIL: 2 defects, both Low.**

- Round 1's D1 and D2 are closed. Every one of the first reviewer's probes now gives the expected result.
- D2's fix rests on the claim that "every daemon git call sees the stored objects". That claim is not true of git's commit-graph, which leads to **R2-1** below.
- Separately, round 2 changed what a cached v4 proof means without bumping the cache version (**R2-2**).

Neither defect is reachable through an ordinary git command.

## Defects (severity-ranked)

### R2-1 (Low): a forged commit-graph entry below the tip makes a content commit read as empty

**Where:**

- `core/branch_park.py:302`, the `git log --boundary %m %H %T %P` walk in `_walk_shape`.
- It is reached from `branch_safety.py:804` (`classify_branch`) and `remote_branch_proof.py:424` (`_judge_offline`).
- The comment that does not hold is at `utils/git_repo.py:59-64`.

**Probe:** `probes5.py::cg_tree_below_tip`.

1. Commit C adds `secret.txt`, and the tip R removes it again, so R's tree equals main's.
2. `git commit-graph write --reachable` is run.
3. C's tree OID in the graph's CDAT chunk is rewritten to its parent's tree, and the trailing checksum is recomputed.

**Variant:** `alternates_with_forged_graph`. The repository has no graph of its own. `objects/info/alternates` points at a store whose commit-graph carries the same forgery.

**Observed:**

| Shape                                                             | main           | round 1              | branch               |
| ----------------------------------------------------------------- | -------------- | -------------------- | -------------------- |
| `cg_tree_below_tip`                                               | DENY           | `empty-commits-only` | `empty-commits-only` |
| `alternates_with_forged_graph`                                    | DENY           | `empty-commits-only` | `empty-commits-only` |
| `cgpark.py` (same forgery + park msg)                             | `park-carried` | `park-carried`       | `park-carried`       |
| `cg_tree_below_tip` with the forged commit at the TIP (`probes4`) | DENY           | DENY                 | DENY                 |
| parent forged so main descends from C (`cg_parent_merged`)        | DENY           | DENY                 | DENY                 |

Every path gives the same result: remote, local and local-hook.

**Why the probes behave this way** (observed on git 2.47.3):

- **Forged commit at the tip.** A commit named on the command line is parsed from the object store. That is why `log -1 <sha>` shows the forged tree while the range walk shows the real tip tree, and why the tip-only forgery is DENY.
- **Forged commit below the tip.** A commit reached through a parent is filled in from the commit-graph, so the walk reads the forged tree.
- **Forged parent.** The parent forgery fools neither plain git nor the proofs. Its stored generation numbers no longer match, and plain `merge-base --is-ancestor` also says no.
- **What `GIT_NO_REPLACE_OBJECTS` does here.** Setting it actually re-enables the commit-graph, because git turns the graph off while replace refs are active.

**Class and widening.** This is the same class as round 1's D2, and the change widens it in the same way:

- On main, the forgery already passes as `park-carried` when the hidden commits carry the park writer's message (Plan 00617).
- On the branch, a commit with any message passes.

**Severity.** Low. It needs a deliberately hand-forged binary cache file in the repository or in an alternate store. No ordinary git operation produces a commit-graph that lies about a commit's tree.

**Why the tests miss it:** no fixture writes a commit-graph or an alternates file. `TestReplaceRefsAndGraftsAreIgnored` only covers refs and `info/grafts`.

**Fix direction** (either of these):

- Confirm each empty candidate from the stored object. A `git cat-file --batch` read of the candidate commits, checking their `tree` and `parent` header lines, costs one process and parses no free text.
- Pin `core.commitGraph=false` for the proof walks.

In either case, correct the `git_repo.py:59-64` comment to name the commit-graph.

### R2-2 (Low): round 2 changed the v4 rule without bumping the version, so round-1 v4 entries are trusted

**Where:** `core/branch_inventory.py:771` (`PROOF_ALGORITHM_VERSION = "v4"`, the same value in both rounds), read at `remote_branch_proof.py:455`.

**Probe:** `probes4.py seed-r1` / `read-r2`.

1. In a repository where C (adds `secret.txt`) is replaced by an empty-looking C', run round 1's code. It caches `v4:<tip>:<main>` = `empty-commits-only`.
2. Re-run the same repository with the branch's code.

**Observed:**

- With the cached entry, the branch's code gives remote `empty-commits-only` (ALLOW), while local and local-hook give DENY because they use no cache.
- A control repository with the same shape and no cache gives DENY on every path.

**Exposure:**

- Only a checkout that ran the unmerged round-1 commit can hold such an entry.
- The project's own `untracked/branch-inventory/cache.json` holds 0 proofs, and the worktree has no cache.
- The rule beside the constant is "Bump when the rule that decides a cached proof changes". D2's fix changed it.

**Why the tests miss it:** `test_a_cached_empty_commits_only_proof_runs_no_walk_the_second_time` checks reuse, not invalidation across rule changes.

**Fix:** bump to `v5`.

## Round-1 findings, re-run

All three of the first reviewer's scripts were re-run against the branch: `probes.py`, `probes2.py` and `probes3.py`.

| Probe                                                                                                               | Branch result                                                                   |
| ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| D1 `ws-pick-empty`, `orphan-ws-empty`                                                                               | DENY on every path                                                              |
| D2 `replace-hides-content`, `-plain`, `replace-park-msg`                                                            | DENY on every path                                                              |
| Octopus, `-s ours` + empty, root + content, mode, gitlink, revert pair, change-and-back, marker-named and lookalike | DENY                                                                            |
| `pure-empty`, `skip-worktree-dirty`, `empty-over-unpushed-main`                                                     | `empty-commits-only` (lossless, or existing policy for an unpushed main)        |
| `git log` rc 1/124/128, dropped boundary lines, `log.showSignature`                                                 | DENY; nothing cached; proves again after git recovers                           |
| merge-base failure                                                                                                  | remote DENY, local `empty-commits-only` (the walk needs no merge base; correct) |
| v3 `merged` entry                                                                                                   | DENY (key never read)                                                           |
| Shallow content + empty                                                                                             | DENY                                                                            |

## New probes that held (no defect)

| Probe                                                                                          | Branch                                        | Control (main or round 1)                               |
| ---------------------------------------------------------------------------------------------- | --------------------------------------------- | ------------------------------------------------------- |
| Replace with repo config `core.useReplaceRefs=true`                                            | DENY                                          | round 1: `empty-commits-only` (the probe discriminates) |
| Replace with inherited `GIT_CONFIG_COUNT` setting `core.useReplaceRefs=true`                   | DENY                                          | round 1: `empty-commits-only`                           |
| Inherited `GIT_REPLACE_REF_BASE` plus a replacement under that namespace                       | DENY                                          | round 1: `empty-commits-only`                           |
| Legacy `info/grafts`: main's tip grafted onto the content tip                                  | DENY                                          | main and round 1: `merged`                              |
| Inherited `GIT_GRAFT_FILE` pointing at a forged graft file                                     | DENY                                          | main and round 1: `merged`                              |
| Hand-written `.git/shallow` entry making the content commit parentless                         | DENY                                          | DENY (a shallow cut only removes ancestry)              |
| C1 content, E empty, C2 content                                                                | DENY                                          | DENY                                                    |
| Empty commit, then a `-s ours` merge of a content side branch (tree equals the first parent's) | DENY                                          | DENY                                                    |
| Gitlink-only change; mode-only change                                                          | DENY                                          | DENY                                                    |
| Integration line holding only an empty commit                                                  | DENY                                          | DENY                                                    |
| Inherited `GIT_OBJECT_DIRECTORY` (empty store)                                                 | DENY                                          | same on main                                            |
| Inherited `GIT_ALTERNATE_OBJECT_DIRECTORIES` (missing dir) on a pure-empty branch              | `empty-commits-only` (lossless)               | main DENY                                               |
| Live remote tip moved (tracking ref at an empty-only tip; the remote has content on top)       | DENY: "remote tip ... could not be confirmed" | main DENY ("not merged")                                |

Notes on three rows:

- **Inherited `GIT_OBJECT_DIRECTORY`.** On both main and the branch, local `classify_branch` raises `CalledProcessError` from `ls-tree` instead of returning unproven. This is older than the change, and it is fail-closed provided the caller treats an exception as a refusal.
- **Inherited `GIT_ALTERNATE_OBJECT_DIRECTORIES`.** Objects are content-addressed, so an alternate can only add objects or leave them missing, never change what a sha means. The single exception is its commit-graph (R2-1).
- **Local tip moving between proof and delete.** The new tier records `tip=` (`branch_safety.py:815-821`). The delete re-checks it in `tip_moved_since_proof` (`branch_safety.py:176`, called at `:984`). The remote cleanup leases each tip (`core/branch_cleanup.py:1199`).

## Environment coverage of every git call

Every git spawn in the proof path goes through `run_git` or `read_blobs`. Both use `_child_environment`, which applies the pin after the inherited environment and after the caller's `env`.

The callers checked:

- `branch_park`
- `branch_inventory`
- `branch_creation`
- `remote_branch_proof`
- `branch_safety._git`
- `utils/remote_refs`
- the `delete-branch` CLI

No other library or exec route spawns git.

The direct `subprocess` callers that build their own environment are not proof inputs:

- `utils/scan_scope.py:90` runs `ls-files --others --ignored`, a file listing for scans.
- `daemon/hook_probe.py:282` runs `bash <entry point>`, not git.
- `install/upgrade_tasks.py:357` runs `ls-files` under a restricted environment, for upgrade content listing.

**Test gap (informational).** No test covers repo-config or `GIT_CONFIG_*` re-enabling replace refs, or an inherited `GIT_GRAFT_FILE` or `GIT_REPLACE_REF_BASE`. All of them hold by construction, as the probes above show.

## The 12 changed guard-test fixtures

The three `test_destructive_git_remote_delete_{merged,chained,lines}.py` files replace `--allow-empty` commits with `commit_content`. `commit_content` writes a new file with unique bytes. No assertion changed.

Each test still exercises what it meant to:

- "unmerged" is now real work;
- the live-tip tests still diverge by one commit, and still assert "remote tip";
- the line tests still need ancestry.

The behaviour the old fixtures exercised by accident was that "an integration line of only empty commits is refused". It is now pinned explicitly by `test_empty_commit_proof.py:507` (`test_an_integration_line_with_an_empty_commit_stays_refused`), and my `probe_empty_only_line` agrees.

## N660 (whitespace-only difference passes the local proofs): agree it is older

I verified this with main's code (`p660.py`):

| Shape                 | main                                           | branch    |
| --------------------- | ---------------------------------------------- | --------- |
| `ws-pick-bare`        | local and hook `patch-equivalent`, remote DENY | identical |
| `ws-pick-writer-park` | local and hook `patch-equivalent`, remote DENY | identical |
| `ws-pick-plain-empty` | DENY                                           | DENY      |
| `orphan-ws-bare`      | local and hook `patch-equivalent`, remote DENY | identical |
| `orphan-ws-empty`     | DENY                                           | DENY      |

In each allowed shape the branch's blob is absent from main's history.

The writer-park variant dates from `3fc5060e5` (Plan 00617). The branch's decisions are identical to main's on all five shapes, so Plan 00622 no longer widens the hole. Ledgering it as N660 is correct.

`patch_equivalent` still has no no-merge-base guard. The inventory's `_pair_facts` has one, at `branch_inventory.py:586`, and could be reused in the N660 fix.

## Informational (not counted)

- **Forged cache entries are still accepted.** A forged v4 entry with any tier string (`anything-at-all`) still ALLOWs the remote delete. `_load_cache` does not validate tier values. This is unchanged from main.
- **Race in `_judge_offline`.** It judges by tracking ref NAME (`remote_branch_proof.py:422-424`) but caches under the listed tip sha (`:455`). A fetch landing between the listing and the judgement can therefore store one tip's verdict under another's key. This is older than the change (`holds_net_change` did the same on main), and the live-tip check bounds it.
- **Messages are lost.** A deleted empty commit's message and extra headers (for example `gpgsig`) are lost by design. The tier detail says so.
