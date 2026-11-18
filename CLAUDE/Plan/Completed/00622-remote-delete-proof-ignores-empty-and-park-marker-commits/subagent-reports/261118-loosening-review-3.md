# Plan 00622 loosening review, round 3 (adversarial, read-only)

Branch `agent-a7abfb6e215f8a166-1ad7f937` at `e1c121abe`. Round-3 change reviewed: `0fff8d932..e1c121abe` (stored-object confirmation in `branch_park._walk_shape`, commit-graph pinned off, `PROOF_ALGORITHM_VERSION` v5). git 2.47.3. The branch was not edited.

**Source trees.** Each run's `import.txt` or `-c` check printed the file it imported:

- **branch:** `<worktree>/src`.
- **main:** `/workspace/src`, the clean main checkout at `0bbc9f23d`.
- **round 2:** `<worktree>/untracked/scratch/r3/r2src/src` (`git archive 43fb88b57`). This is the live-attack control.

**Where the material is.** Everything is under `/workspace/untracked/scratch/00622-review3/`:

- new probes `probes6.py` and `probes7.py`, with logs `p6-*.log`, `p6-catfile-branch.log` and `p7-*.log`;
- `run_old_probes.bash`, which re-runs every earlier probe into `old-branch/` and `old-main/`;
- `probes2_fixed.py`, the argv-independent walk matchers;
- `flipplugin.py` and `pytest-flip.txt` for the test check;
- `pytest-remote-delete.txt`.

## Verdict

**FAIL: 2 defects, both Low.** In this series a Low counts as a defect, as in round 2.

- **D1.** A forged loose commit object, in the repository's own store or in an alternate, still deletes a content-bearing branch on all three paths. The round-3 claim that "no commit-graph, replace ref or graft can change what that read returns" is true. The claim that `cat-file` returns the commit that was stored under that sha is not: git does not rehash on read.
- **D2.** A walk that exits 0 but omits the tip line deletes a content tip on the local paths. This was already present in round 2.

Neither defect can be reached with ordinary git commands. Both need deliberately forged bytes or a lying git, the same footing as R2-1.

Everything else asked about held:

- every graph, chain, alternate, environment, config, replace, graft, shallow, promisor, header, mode, gitlink and tag probe;
- every `cat-file` fault;
- the cache versioning;
- the caller coverage;
- the 12 tests.

## Defects (severity-ranked)

### D1 (Low): a forged loose commit object passes the stored-object check

**Shape.** `probes7.loose_forged_own_store` and `loose_forged_alternate` start from the content-then-revert shape:

1. C adds `secret.txt` and R removes it. Both are pushed, so the remote's C carries the content.
2. C's loose object file is overwritten with a zlib-deflated commit body. The body is identical to C's except that its `tree` is C's parent's tree.
3. In the alternate variant, the repository's own copy is deleted and the forged object lives only in an `objects/info/alternates` store.

**What git does.**

- Plain `git log` and `git cat-file` return the forged body without complaint. Only `git fsck` notices (rc 3).
- The walk with the graph pinned off agrees with the batch read, so `_stored_objects_agree` passes.
- C reads as empty and R reads as empty.

**Results.**

| Shape                     | main | round 2              | branch                                               |
| ------------------------- | ---- | -------------------- | ---------------------------------------------------- |
| forged loose C, own store | DENY | `empty-commits-only` | `empty-commits-only` on remote, local and local-hook |
| forged loose C, alternate | DENY | `empty-commits-only` | `empty-commits-only` on remote, local and local-hook |

**Impact.** The remote copy of C still holds `secret.txt`, so the remote delete loses real content. The access needed is the same as R2-1's forged graph: write access to the object store or to an alternate.

**Fix.** The stored bytes are already in hand, so close it in `_stored_objects_agree`:

- require `hashlib.new(<repo hash algorithm>, b"commit %d\0" % len(body) + body).hexdigest() == sha` for every body read;
- confirm the `cat-file` header type is `commit`;
- refuse on any mismatch.

One check covers the own store and every alternate, packed or loose. It costs one hash per walked commit. The repository's hash algorithm comes from `extensions.objectFormat`, which defaults to sha1.

### D2 (Low, present since round 1/2): the walk is never checked to contain the tip

**What the code checks.** `_walk_shape` confirms the tree and parents of every commit the walk listed. Nothing asserts that the listed range contains `tip`.

**Probe.** `probes6.walk_drops_tip` injects a `log` result with exit code 0 that omits the tip line. The shape is a content tip over an empty commit over main.

| Path       | branch               | round 2              | main |
| ---------- | -------------------- | -------------------- | ---- |
| local      | `empty-commits-only` | `empty-commits-only` | DENY |
| local-hook | `empty-commits-only` | `empty-commits-only` | DENY |
| remote     | DENY                 | DENY                 | DENY |

The remote path denies because the net-change check runs first.

**Why it counts.** Dropping a lower line is caught, because the dropped commit is some candidate's parent. Dropping the newest line is not caught. The earlier rounds already treated injected `log` output faults as in scope: `log-no-boundary` in probes2.

**Reachability.** I found no repository state, config or environment that makes git do this.

**Fix.** Require that `rev-parse --verify <tip>^{commit}` is among the in-range shas. Alternatively, require that every in-range commit except one, the tip, is a walk parent of another in-range commit.

## (1) Can a content-bearing branch still be deleted? Every other probe

All shapes labelled N were DENY on all three paths on the branch.

The "round 2" column is the live-attack control: on round-2 code, the new graph probes ALLOW, so they exercise a real hole.

| Probe                                                                                                                                                  | round 2              | branch                                                        |
| ------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------- | ------------------------------------------------------------- |
| Forged commit-graph **chain** layer (`--split`, renamed to its new checksum)                                                                           | `empty-commits-only` | DENY                                                          |
| Alternate store with a forged chain                                                                                                                    | `empty-commits-only` | DENY                                                          |
| Inherited `GIT_ALTERNATE_OBJECT_DIRECTORIES` naming a store with a forged graph                                                                        | `empty-commits-only` | DENY                                                          |
| Forged graph plus inherited `GIT_CONFIG_PARAMETERS`, `GIT_CONFIG_COUNT`, `GIT_TEST_COMMIT_GRAPH=1` or a `GIT_CONFIG_GLOBAL` turning the graph on       | `empty-commits-only` | DENY on all four                                              |
| probes4 and probes5: forged graph file, alternate graph, forged parent, replace (config, env, `GIT_REPLACE_REF_BASE`), `info/grafts`, `GIT_GRAFT_FILE` | as reported earlier  | DENY                                                          |
| `.git/shallow` at the empty commit over content, at the content commit, and an inherited `GIT_SHALLOW_FILE`                                            | DENY                 | DENY                                                          |
| Partial clone with the content commit's object missing (dead promisor)                                                                                 |                      | DENY. The lossless variant is also DENY: fails closed.        |
| Commit with a 210 KB `gpgsig` that holds ` parent <content>`, a `mergetag`, an `encoding` header, and `parent <content>` in the message                |                      | `empty-commits-only`. Correct: the commit is genuinely empty. |
| `parent <content>` header after `committer` (git's `%P` shows main only)                                                                               |                      | DENY. Fails closed: the stored parents disagree.              |
| CRLF headers                                                                                                                                           |                      | git refuses the ref (`bogus commit object`)                   |
| An empty commit with a 10 MB message over a content commit                                                                                             |                      | DENY                                                          |
| Mode-bit-only change and gitlink-only change, each under an empty commit                                                                               |                      | DENY. A tree hash covers mode and gitlink.                    |
| Annotated-tag tip (remote and local refs written directly), content-bearing: tag to content, tag of a tag to content, tag to tree                      |                      | DENY on all three paths                                       |

**`cat-file --batch` faults.** These were injected by wrapping `subprocess.run` in `git_repo`, with the cache removed before each case:

- exit code 128;
- empty output with exit code 0;
- output truncated in the middle of a body;
- the last object dropped;
- the first object answered `missing`;
- trailing garbage.

Every fault was DENY on all three paths. Each case made 5 batch reads, no entry was cached, and the branch was proven again once the read recovered. A first pass that left the control run's cache in place produced remote results that meant nothing, and it was discarded.

## (2) Does every route to the emptiness decision go through the hardened read?

The callers were found with `git grep`. Every empty or park decision goes through `branch_park._walk_shape`:

- `remote_branch_proof._judge_offline` calls `is_content_free`. It raises `ProofUnavailableError` on None.
- The `remote_branch_proof` park pass calls `is_park_residue`.
- `branch_safety.classify_branch` calls `walk_park_range`, for both `is_residue` and `is_content_free`.
- `branch_safety.patch_equivalent` calls `walk_park_range`. It excuses parks only.
- `branch_inventory._pair_facts` calls `walk_park_range`.
- `branch_creation` calls `is_park_residue`, but that is not a delete.

**Other reads that touch commits.**

- `_park_bodies_match` reads only the messages of candidates already confirmed.
- `branch_inventory._park_count` uses an unpinned `%T` log. It feeds only the "re-parked N times" sweep text (`branch_sweep.py:425`).

So every route uses the hardened read, and D1 affects all of them equally.

## (3) Cache

- A v4 `empty-commits-only` entry under the exact current key, for a content branch: DENY on every path.
- The probes2 `cache-v4-forged` and `cache-v3` entries: DENY.
- A v5 entry written while the branch held only empty commits, followed by the branch gaining content: DENY.
- A v5 entry keyed to an older main sha: DENY.
- A v5 cache copied from another repository: DENY.
- **Informational:** a forged v5 entry under the exact key still ALLOWs the remote delete. This is the known, unchanged trust in whoever can write the cache file.

## (4) The 12 remote-delete tests

`flipplugin.py` turns `commit_content` back into `commit --allow-empty`. With it in place, exactly 12 tests fail (`pytest-flip.txt`):

- `chained`: `test_an_unmerged_remote_delete_chained_after_cleanup_names_its_reason` [0 to 3] and `test_a_denied_push_delete_chained_with_a_destructive_rule_names_its_reason`;
- `lines`: `test_without_the_line_configured_the_same_branch_is_unmerged`;
- `merged`:
  - `test_deleting_an_unmerged_remote_branch_is_denied_and_says_so` (two commands);
  - `test_every_ref_must_be_merged` (two);
  - `test_a_merged_delete_chained_with_an_unmerged_one_is_denied`;
  - `test_a_fetched_tracking_ref_that_is_now_unmerged_is_denied`.

With `commit_content`, all 56 tests in the three files pass. The assertions were not touched, and they still pin the original reasons, for example "`unmerged` is not merged into `main`" and "not merged".

So each of the 12 still denies for its original reason. The swap was required, because an empty "unmerged" commit is now lossless, and it is not cosmetic.

## Re-run of the earlier probes (branch compared with main)

Everything matched the round-3 fix report:

- `probes.py`: 0 N shapes ALLOW. `replace-park-msg` went from main `park-carried` to DENY.
- `probes2_fixed`:
  - log rc 1, 124 and 128, and the dropped boundary, are DENY with nothing cached;
  - the branch is proven again after recovery;
  - `cache-v3` and `cache-v4-forged` are DENY;
  - `merge-base-fail` is remote DENY and local `empty-commits-only`, which is lossless.
- `probes3` and `p660`: identical to main.
- `probes4`: all DENY. The graft shapes, which are `merged` on main, are now DENY.
- `probes5`: as in the report. Inherited `GIT_ALTERNATE_OBJECT_DIRECTORIES` on a pure-empty branch reads `empty-commits-only`, which is lossless.
- `cgpark`: main `park-carried`, branch DENY.

## Informational

- **I1.** When a local `refs/heads/<x>` is written directly to an annotated tag of an empty commit, both local paths return `empty-commits-only`. Only the tag object's message is lost. The remote path denies it.
- **I2.** A commit with two `tree` headers is local `patch-equivalent` on both main and the branch. git reads the first header only, so the commit is lossless in git's terms, and this change does not affect it.
- **I3.** The ancestry reads (`merge-base`, `--is-ancestor`, net change) still do not pin the graph, as the fix report states. `cg_parent_merged` stays DENY.
