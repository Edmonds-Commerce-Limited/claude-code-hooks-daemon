# Park marker over merged work: one classification (Plan 00594)

## Root cause (reproduced by test first)

A tip whose only commits beyond the default are empty `Parked-*` park markers was judged by three rules:

- Inventory (`_pair_facts`) subtracts park commits, so `ahead == 0` gave `MERGED_DEFAULT`, "proven by origin/main", though the tip is not an ancestor.
- Creation guard (`_ref_pool`) used strict ancestry, cached proofs and labels, then `ref.parked`: PARKED.
- Remote-delete proof: ancestry fails and an empty net change is "unproven": refused.

Remote-only is incidental; what matters is what sits under the markers. Red tests: `tests/unit/core/test_branch_park_carried.py` (commit 3b262c8e2).

## Decision

A park marker over work the default holds is a new inventory state `park-carried`, in NO pool. The creation guard does not count it, the sweep lists it under "Park-carried" with its park reason and a runnable `git push <remote> --delete <name>` line, and `branch-sweep --clean --remote` deletes it under a lease. It is verified by content, never by the reason text: `branch_inventory.is_park_residue(repo, tip, target)` (every commit in `default..tip` is an empty park commit). A park over unmerged work stays PARKED, and its remote delete stays refused.

Reconciling the `surviving-content` rule: "an empty net change proves nothing" stays for tips that are not park markers (cancelling changes, plain empty commits). The park case is decided first, before the cached net-change proof, so no cache-version bump is needed. New tier `park-carried` (`branch_safety.TIER_PARK_CARRIED`). It costs one batched `for-each-ref` trailer listing per proof, and a `log` walk only for trailered tips.

Why out of pools rather than merged: the merged pool counts unkept branches as stale from day 0, so moving the refs there would only swap the PARKED deny for a MERGED deny.

## Shared code

- `pool_for_ref(merged, park_carried, parked)` in `branch_inventory` is the rule table; the guard's `_ref_pool` calls it, `pool_of(state)` is pinned to it by a test.
- `branch_creation.work_pools()` exposes the guard's membership; `creation_report` uses the same `_pool_groups`. A parametrised test asserts guard pools == sweep pools over four repository shapes, each with and without a stale label, and requires a non-empty expectation.
- Inventory cache version 3 -> 4 (`_PairFacts.parks`).

## The other reported items

- "0d old, STALE": age was already the tip committer date (a pinned 3.2-day-old remote-only tip reads `3d old` in sweep; this passes on main too, so no age bug was invented). The staleness is the Plan 00571 rule: an unkept merged branch is stale from day 0. The quoted text "(unkept, past ... 30)" does not exist in `src` (`git log -S` finds nothing); the creation merged-pool head was ambiguous and now says stale-from-day-0 explicitly.
- Sweep vs delete-guard proof disagreement: now both accept a park-carried tip through the same rule.

## Known limits

- A park-carried name with a LOCAL copy is reported the same way, but `--clean` (local) does not delete it; its printed local line is `delete-branch <name>`, whose local proof was not changed or tested here.
- A park over a branch with no work at all (park commit straight on main) is now park-carried as well (it was already merged in the sweep); four existing tests that built such parks were given a real work commit under the park.
- Integration-line targets are unchanged: only the default decides park-carried.

## Verification

Targeted: 265 tests across the branch inventory, creation, park-carried, proof-shape and guard-handler files pass; 2268 branch-related tests in `tests/unit/core` and `tests/unit/handlers` ran green apart from the five that were then fixed (three expected-behaviour updates, two cost-bound failures cured by the batched listing). pyright: no findings on touched files except the venv missing `pytest` stubs. Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/079-park-marker-over-merged-work-is-in-no-pool.md`.
