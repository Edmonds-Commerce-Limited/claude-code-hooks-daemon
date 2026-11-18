## 16:28 · decision · —

The fix ignores commits that carry no content structurally: exactly one parent and that parent's tree, any message. A merge (even `-s ours`, first parent's tree), a root commit and any commit that changes a file always count.

- New tier `empty-commits-only`: every commit beyond the default is empty. Remote proof asks it only when the net change is empty (so non-empty branches pay no extra git call; the per-branch call bound holds), inside the cached judgement; `PROOF_ALGORITHM_VERSION` v3 -> v4 so cached unproven answers are recomputed. Local `classify_branch` answers park-carried and empty-commits-only from ONE range walk.
- `patch_equivalent` now drops every empty commit from `git cherry`'s unique list, not only exact park commits.
- `is_park_residue` and the inventory's park-carried state are unchanged (still the writer's exact markers).
- "Empty net change proves nothing" stays in `holds_net_change`.
- A failed or malformed walk is None: unproven locally, ProofUnavailableError (not cached) remotely.
- Deliberate non-content flips (tests updated in the fix commit): a branch made only of empty commits off main is now deletable (`test_a_branch_of_only_empty_commits_is_proven_empty_commits_only`, `test_an_empty_commit_on_main_never_proves_a_branch_by_net_change`), and a non-writer empty commit with Parked-\* trailers over merged work is deletable though still not a park (`test_empty_trailer_commit_not_written_by_the_park_writer`). What such a delete loses is the empty commits' messages; the release note says so.
- Corpus (48 shapes x 4 proofs = 192 decisions): 19 DENY->ALLOW (13 on content-in-default shapes, 6 on no-content shapes), 0 on content-not-in-default shapes, 0 ALLOW->DENY, 0 ALLOW on any N shape. Files under the plan's `corpus/`.
