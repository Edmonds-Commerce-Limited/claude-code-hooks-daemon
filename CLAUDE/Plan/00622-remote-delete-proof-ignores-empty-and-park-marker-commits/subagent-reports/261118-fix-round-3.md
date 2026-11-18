# Plan 00622 fix round 3: R2-1 (forged commit-graph) and R2-2 (cache version)

Branch: `agent-a7abfb6e215f8a166-1ad7f937`. It was merged with `origin/main` first, at `385ad3b54`, which brought in main's ledger entries N650 to N659. The branch's N660 is unchanged.

Commits:

- RED: `0fff8d932`
- GREEN: `164ba4986`
- journal: `0098f2bb0`
- the stored-parent isolation test and this report's corrections: the commit after those

Not merged to main.

The import check printed `<worktree>/src/claude_code_hooks_daemon/__init__.py`. Every test and probe run used `PYTHONPATH=<worktree>/src`.

## R2-1: emptiness is decided from the stored commit objects

`core/branch_park._walk_shape` is the single range walk behind:

- `is_content_free`, which gives `empty-commits-only`;
- `walk_park_range` and `is_park_residue`, which give `park-carried`.

It now does three things:

1. **It runs with `-c core.commitGraph=false` and `GIT_TEST_COMMIT_GRAPH=0`.** These were verified against the reviewer's forged repository on git 2.47.3:
   - the pin alone defeats the forgery;
   - an inherited `GIT_CONFIG_COUNT` setting `core.commitGraph=true` does not override `-c`;
   - an inherited `GIT_TEST_COMMIT_GRAPH=1` DOES override it, hence the second pin.
   - The pins are passed per call. They are not added to the global `_REAL_OBJECTS_ENV`, because a global `GIT_CONFIG_COUNT` would clobber the inherited `-c`-style config of every daemon git call.
2. **It confirms the walk with one `cat-file --batch` read of the raw commit objects** (`read_blobs`). No commit-graph, replace ref or graft can change what that read returns.
   - Every walked commit, boundary commits included, must have a stored `tree` header equal to the walk's tree.
   - Each empty candidate's stored `parent` headers must be exactly its one walk parent.
   - Only the header block is parsed, up to the first blank line. A message line starting `parent` therefore never counts, and a signature continuation line starts with a space and matches neither header.
3. **It fails closed.** A failed read, a missing object or any disagreement returns None, which every caller reads as unproven. Nothing is cached on that path.

Why only the candidates' parents are compared: a shallow clone's cut commit is parentless in the walk while its stored header names a parent. Comparing every commit's parents turned the inventory's "history not fetched" diagnosis into a generic git failure. That was still fail-closed, but `test_branch_inventory_no_merge_base` caught the regression. A non-candidate already counts as content, so its parents decide nothing. A candidate must have exactly the stored single parent, so a forged parent that hides a commit beneath an empty-looking one is caught.

The comment at `utils/git_repo.py:59` now says the replace and graft pin does NOT cover the commit-graph, and names where that is handled.

**Limit of the guarantee.** Trees, and the parents of empty candidates, come from the stored objects. Which commits are in `target..tip` at all still rests on the walk, which is truthful because of the two pins and nothing more.

The ancestry reads behind the other tiers are not pinned against the commit-graph. These are `merge-base`, `--is-ancestor` and the net-change route. They are out of scope here, and the reviewer's `cg_parent_merged` probe shows git's generation-number check rejecting a forged parent there.

## R2-2: `PROOF_ALGORITHM_VERSION` v4 to v5

The comment beside it records what v5 changed: emptiness is now read from the stored objects only.

## Tests

All of these are in `tests/unit/core/test_empty_commit_proof.py`. All were RED before the fix, in two ways:

- The commit-graph and stale-cache tests failed on behaviour: all four paths allowed the delete, or the stale entry was honoured.
- The fail-closed and cached-proof tests failed on the missing `branch_park.read_blobs` attribute.

The RED commit was made with `--no-verify`, because its tests fail by design.

**`TestACommitGraphIsIgnored`.** Each test first asserts that plain git shows the forgery, then asserts that every path refuses.

- The tree below the tip is forged, with two messages: any message, and the park writer's (cgpark).
- An inherited `GIT_TEST_COMMIT_GRAPH=1`.
- A forged graph in an alternate object store.
- A forged first parent below the tip that drops a content commit out of the range.

**`TestTheStoredObjectReadFailsClosed`.** Each of these returns None:

- a failed read;
- a missing object;
- a stored tree the walk did not report;
- a stored parent the walk did not report. This one isolates the parent comparison, since with the graph off the walk is already truthful. It was added after GREEN, in the report commit.

A further test shows every proof refusing and then proving again once the read recovers.

**`TestAProofCachedUnderAnOlderRuleIsNotHonoured`.** A literal `v4:<tip>:<main>` `empty-commits-only` entry for a content branch: the remote proof and the guard both refuse.

**Other test changes:**

- The cached-proof test now also asserts that a cache hit makes no commit-object read.
- The walk matchers are now independent of argv shape. Matching on `args[:2]` would have passed vacuously once `-c` was prepended.

**`tests/unit/core/test_merge_proof_shapes.py`:**

- `_CALLS_PER_BRANCH` is now 6, up from 5, for the one batch read per cold walk. It measured 49 against the old budget of 47.
- The subcommand spy skips global `-c` options, so `"log" not in calls` still bites.

**Targeted run:** 13 file groups, 730 passed at GREEN. After the stored-parent test was added, `test_empty_commit_proof` was re-run alone: 41 passed. The groups:

- `test_empty_commit_proof`, `test_merge_proof_shapes` and `test_park_commit_classifier`;
- `test_branch_inventory` and `test_branch_inventory_no_merge_base`;
- the `test_branch_park*` files;
- `test_remote_branch_proof`;
- the `test_branch_cleanup*` files;
- the `test_destructive_git_remote_delete_*` files;
- `test_branch_safety` and `test_git_repo`.

**Targeted QA:** all pass after one mypy annotation fix.

- format, lint, `type_check`, pyright and `error_hiding`;
- `magic_values`, `british_english` and `inline_suppressions`.

## Old-versus-new decisions against main

`corpus/p622_corpus.py` gained four shapes:

- `r3-cg-tree-below-tip`
- `r3-cg-tree-below-tip-park-msg`
- `r3-cg-alternate-store`
- `r3-cg-parent-below-tip`

It was run with main's `src`, exported fresh by `git archive origin/main` at `0bbc9f23d`, and with the branch's `src`. The files are `corpus/p622-corpus-{before,after,compare}-r3.*`.

Totals:

- **61 shapes, 244 decisions.**
- **0 DENY-to-ALLOW on content-bearing (N) shapes.**
- **18 DENY-to-ALLOW in all**, every one on shapes labelled Y or E: the reported empty-commit shapes.
- **16 ALLOW-to-DENY**, all on N shapes:
  - the round-2 replace and graft shapes;
  - `r3-cg-tree-below-tip-park-msg`, which main passes as `park-carried`.
- **6 ALLOWs remain on N after the change.** They are the N660 whitespace patch-equivalent shapes, local and local-hook, identical on main. That is why `compare` exits 1. They are already ledgered as older than this plan.

Three of the four r3 shapes are DENY on main too, so the comparison against main alone does not show that the forgery was live. To show it, the corpus was also run with round 2's `src` (`git archive 43fb88b57`, output `untracked/scratch/r3/corpus-r2src.json`), where all four r3 shapes ALLOW on every path:

- `r3-cg-tree-below-tip`, `r3-cg-alternate-store` and `r3-cg-parent-below-tip` gave `empty-commits-only` and the guard ALLOW.
- `r3-cg-tree-below-tip-park-msg` gave `park-carried`.

A forged parent below the tip was therefore a further live variant of R2-1 on round 2's code. The review had probed a parent forgery only at main's tip. All four are DENY on the final code.

## Reviewer probes, re-run

All runs used fresh work directories under `untracked/scratch/r3/`, with branch and main side by side.

| Probe                                                                   | main                  | branch                                                                   |
| ----------------------------------------------------------------------- | --------------------- | ------------------------------------------------------------------------ |
| `probes5` `cg_tree_below_tip`                                           | DENY                  | DENY                                                                     |
| `probes5` `alternates_with_forged_graph`                                | DENY                  | DENY                                                                     |
| `probes5` `cg_parent_merged`                                            | DENY                  | DENY                                                                     |
| `probes5` `live_tip_moved`                                              | DENY                  | DENY (remote tip check)                                                  |
| `probes5` inherited `GIT_ALTERNATE_OBJECT_DIRECTORIES` on pure-empty    | DENY                  | `empty-commits-only` (lossless, as the reviewer found)                   |
| `cgpark` (forgery + park message)                                       | `park-carried`        | DENY                                                                     |
| `probes4 all` (12 replace, graft, shallow, graph, line and mode shapes) | graft shapes `merged` | all DENY                                                                 |
| `probes4 seed-r1` (round-1 src) then `read-r2` (branch src)             | n/a                   | seeded `v4:…` `empty-commits-only`, read DENY on all three paths         |
| `probes.py` (17 shapes)                                                 |                       | 0 N shapes flip to ALLOW; `replace-park-msg` main `park-carried` to DENY |
| `probes3`                                                               | identical             | identical                                                                |
| `p660`                                                                  | identical             | identical (N660, older)                                                  |

This round re-ran every branch row against the final code:

- `probes5`, `cgpark` and `probes4 all` went into `out-branch-v2/`.
- `probes.py`, `probes3`, `p660`, the argv-independent `probes2`, and the seed and read pair went into `out-final/`. Each of these is identical to the first pass.

On round 2's code the reviewer had observed `empty-commits-only` on the branch for the first two R2-1 rows, and `park-carried` for `cgpark`.

**Caveat on `probes2.py`.** Its fail-injection matches the walk by `args[:1] == ("log",)`, which no longer sees the walk now that `-c` precedes `log`. Its log-failure rows therefore injected nothing and read `empty-commits-only` on the remote path; the probe broke, not the code.

An argv-independent copy (`untracked/scratch/r3/probes2_argv_agnostic.py`) gives the round-2 results:

- `log` rc 1, 124 and 128, and dropped boundary lines: DENY on every path, with nothing cached;
- after git recovers: proven again;
- the forged v4 cache entry, now DENY;
- `merge-base` failure: remote DENY, local `empty-commits-only`.

The unit tests' own matchers were already made shape-independent.

## Not changed (informational, unchanged from the review)

- `_load_cache` still accepts any tier string from a forged CURRENT-version entry. Anyone able to write the cache file can already forge a v5 entry.
- The `_judge_offline` name-versus-sha race.
- N660, the whitespace patch-equivalent hole on the local paths, is older than this plan and already ledgered.

## Release note

`CLAUDE/UPGRADES/UNRELEASED/release-notes/002-empty-commits-no-longer-block-branch-deletes.md` now says:

- emptiness is read from the stored commit objects;
- the commit-graph, including one in an alternate store, is never trusted;
- a failed object read refuses the delete.
