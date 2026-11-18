# Plan 00622 fix report: empty and marker commits in the delete proofs

Branch `agent-a7abfb6e215f8a166-1ad7f937` (pushed, not merged to main).

## Reproduction (Phase 1)

Synthetic repositories with a bare remote, `tests/unit/core/test_empty_commit_proof.py`.

- The park writer's exact park and unpark markers over merged work already passed every delete proof (Plan 00617). Shape (b), and shape (a) with the writer's verbatim message, did not reproduce.
- Shape (c) is a modified merge where `git cherry` marks the content commits unmerged. Each path was established by test (`test_a_modified_merge_then_an_unpark_passes_the_net_change_route`). That test needs the default to hold the branch's final content; the one-byte-different twin stays refused on every path. The outcome is the same with the writer's unpark and with a plain one, before and after the fix:
  - The REMOTE proof allows it as `content-preserved`. It is decided by `holds_net_change` alone, and cherry only names the tier.
  - The local `classify_branch` with the content tier allows it. File survival and net change both hold.
  - The hook path (`content_tier=False`) refuses it. Neither patch-id nor the empty-commit rule can prove it there. That is by design and unchanged.
- What does reproduce: an empty commit whose message is not the writer's exact text, for example a hand-made `Unpark branch` with no trailer, or a note, over merged work. It was refused by the remote proof, the remote-delete guard, and `classify_branch` with and without the content tier. Locally, a cherry-picked branch with such an empty commit on top was also not patch-equivalent, so the hook path refused it. The 3.75.0 report most likely carried such commits.
- RED commit `f93284763`: 4 failing tests, plus pins for the shapes that already passed and for the content-bearing twins.

## Fix (Phase 2)

- **The rule.** A commit is empty when it has exactly one parent and that parent's tree. Its message plays no part.
  - A merge always counts as content, including an `-s ours` merge that has its first parent's tree.
  - A root commit and any commit that changes a file always count.
- **New tier `empty-commits-only`.** Every commit the default branch lacks is empty. It is threaded through `is_safe`, `_TIER_DETAIL` and the remote evidence. `delete_argv_for_tier` uses `--force`, the same as every non-`merged` tier.
- **`core/branch_park.py`.**
  - The structural walk is now shared (`_walk_shape`).
  - New `is_content_free(...) -> bool | None`.
  - `ParkWalk` gains `empties` and the `is_residue` / `is_content_free` properties.
  - `is_park_residue` and the inventory's park-carried state are unchanged.
- **`core/remote_branch_proof.py`.**
  - `_net_change_state` tells an EMPTY net change apart from one that is not held.
  - The empty-commit walk runs only for an empty net change, inside the cached judgement. Any branch with a non-empty net change pays for no extra git call, and the per-branch call bound test still holds.
  - A failed walk raises `ProofUnavailableError` and is not cached.
  - `holds_net_change` still never treats an empty net change as proof.
- **`daemon/branch_safety.py`.**
  - `classify_branch` decides both park-carried and empty-commits-only from ONE range walk.
  - `patch_equivalent` drops every empty commit from `git cherry`'s unique list, not only park commits.
  - A failed walk proves nothing.
- **`core/branch_inventory.py`.** `PROOF_ALGORITHM_VERSION` goes from v3 to v4, so cached "unproven" answers from before the fix are recomputed.

## Corpus check

The harness and its results are in `corpus/`: `p622_corpus.py`, `p622-corpus-before.json` (recorded against the pre-fix source and committed before the fix), `p622-corpus-after.json` and `p622-corpus-compare.txt`.

- **Coverage.** 48 shapes x 4 proofs (remote, guard, local, local-hook) = 192 decisions. Each shape is labelled by hand from what it builds: Y means the content is in the default, N means content the default lacks, E means no content at all.

- **Adversarial shapes included:**

  - content commits named like markers (writer park, writer unpark, plain unpark)
  - a change plus its revert under an empty commit
  - an empty commit over unmerged work
  - `-s ours` merges, one with the writer's message
  - a one-byte difference, with plain and writer markers
  - a root commit named like an unpark
  - an empty commit over another branch's work
  - a revert of main under an empty commit
  - a forged-tree "unpark"
  - mode-only and rename-only branches with an empty commit on top

- **Results:**

  | Result                                      | Count                              |
  | ------------------------------------------- | ---------------------------------- |
  | DENY to ALLOW, total                        | 19 (13 on Y shapes, 6 on E shapes) |
  | DENY to ALLOW on N shapes (content-bearing) | **0**                              |
  | ALLOW to DENY                               | 0                                  |
  | ALLOW on any N shape, before or after       | 0                                  |

- **Non-content flips.** These are deliberate, follow from the plan's rule, and the tests were changed in the fix commit:

  - `test_merge_proof_shapes.py::test_a_branch_of_only_empty_commits_is_proven_empty_commits_only`
  - `test_merge_proof_shapes.py::test_an_empty_commit_on_main_never_proves_a_branch_by_net_change`
  - `test_park_commit_classifier.py::test_empty_trailer_commit_not_written_by_the_park_writer`. This commit is still not a park for the inventory, but it is now deletable.

  What such a delete loses is the empty commits' messages. The release note says so.

## Verification

- **Targeted tests: 597 passed.** The run covered every test file that calls `classify_branch`, `prove_remote_merged`, `patch_equivalent`, `read_merge_proofs`, `walk_park_range` or `_proven_refnames`. That includes branch cleanup (hook, no-network and remote), inventory, pools, creation, the remote archive proof, the CLI branch defaults and `test_branch_safety.py`, plus the new and changed files.
  - Outside the three deliberate flips above, no existing assertion changed.
  - `test_branch_safety.py` shapes are not in the corpus harness. That suite passes unchanged, and it is the evidence for those shapes.
- **Added after the advisor's review:**
  - A failed walk is not cached: the same tip is proven once git answers.
  - A cached `empty-commits-only` proof is read back with no range walk.
  - An integration line (`release/*`) with an empty commit over merged work stays refused on the remote path and the local path.
- **Creation guard.** `branch_creation._proven_refnames` treats any cached tier other than `unproven` as proven. A remote branch cached as `empty-commits-only` therefore stops counting as open work, the same as a squash-merged one.
- **Targeted QA:** results are in the commit that follows this report.
- **A missing trailer.** The merge of `origin/main` into this branch (`ba77416d6`) was made with `-m` and carries no Co-Authored-By trailer. Amending is not allowed, so it is recorded here instead.

## Release note and journal

- `CLAUDE/UPGRADES/UNRELEASED/release-notes/002-empty-commits-no-longer-block-branch-deletes.md`
- Journal entries: a `finding` (the reproduction) and a `decision` (the rule and the flips).

## Left open

- Task 2.3 needs an independent Opus review of whether the change loosens any proof. Nothing here substitutes for it.
- The handler guidance text for `R-GIT-PUSH-DELETE-REMOTE` was not changed. It does not enumerate tiers.
