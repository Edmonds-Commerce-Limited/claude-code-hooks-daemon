# Phase 3 implementation report and handoff (slice a done; b-e remain)

Branch `agent-aa87210ca7838e9c4-79b323ad`. The design is still
[phase-3-pools-handoff.md](phase-3-pools-handoff.md); read it first. This file
records what is DONE, what was decided, and where the next agent starts.
This agent stopped after slice (a) at its context budget.

## Open question answered

Repeated `--merged` in one `for-each-ref` ORs (git 2.47.3, scratch repo: a ref
merged into only A and a ref merged into only B are both listed with
`--merged=A --merged=B`; git's documentation says the same). One call is used.

## Slice (a): DONE (commit d6b19f4ef)

- `config/models.py`: `BranchPoolConfig` (+ `BranchParkedConfig`,
  `BranchMergedConfig`), `BranchesConfig.parked`/`merged`/`bot_owned`
  (default `["dependabot/*"]`), `effective_pool_cap(pool)` and
  `effective_pool_max_age(pool)`. They take the pool as a string (`Pool` is a
  `StrEnum`, so `Pool.PARKED` works) because `core.branch_inventory` imports
  the config module.
- `core/branch_inventory.py`: `BranchState.BOT_OWNED` (checked right after
  EXEMPT in `_never_work`, so `is_work_branch` excludes it), `Pool`,
  `pool_of(state)`, BOT_OWNED in `_UNGROUPED`, and a bot branch never vouches
  in `containment_of`.
- `core/branch_stop_guard.py`: BOT_OWNED added to `_NEVER_JUDGED`.
- `core/branch_sweep.py`: `pool_count(inventory, pool)`, `open_work_count` =
  OPEN pool, `SweepGroups.bot_owned` printed always, `pool_caps`,
  `pool_count_lines` (three footer lines naming each key), JSON `pool` per
  record and top-level `pools`.
- `core/branch_creation.py`: `_FORMAT` carries the Parked-Reason trailer,
  `_Ref.refname`/`parked`, `_merged_refnames` (one call, fails to the empty
  set = over-count open work), `_ref_pool`/`_group_pool`, `_Work.pool`. The
  WIP cap counts OPEN groups only; duplicates still judge ALL groups. The
  merged-branch `sweep_clean_line` was REMOVED from the WIP deny (import too);
  slice (c) must put it in the merged-pool deny.
- Tests: new `tests/unit/core/test_branch_pools.py` (37 tests: config, pool_of,
  bot-owned, pool split, footer, JSON). Rewritten to the new semantics:
  `test_branch_sweep.py` open-work counts 5 -> 3,
  `test_branch_creation.py` (`test_labels_order_contained_nowhere_first_with_action`,
  `TestWipCapLeavesMergedToItsOwnPool`), and
  `test_branch_creation_guard.py::test_labels_snapshot_orders_the_list`.

## Remaining: slices b-e (unchanged from the handoff design)

- (b) parked cap + stale: `BranchRecord.stale`/`park_count`, `_with_pools`
  pass in `build_inventory`; creation: `_Work` of pool PARKED, count vs
  `effective_pool_cap(Pool.PARKED)`, stale = `(now - committed)/DAY >= effective_pool_max_age`, `mode` block/warn/off; `RuleID.BRANCH_PARKED_POOL`
  (`R-BRANCH-PARKED-POOL`); deny lines name `branch-park <n> --clear` then
  merge, or `delete-branch`; stale adds re-park with a NEW reason;
  `park_branch` refuses a same-reason re-park (exit 2).
- (c) merged cap + stale + `core/branch_keep.py` + `branch-keep` CLI
  (`daemon/cli.py` beside branch-park) + `RuleID.BRANCH_MERGED_POOL`; deny
  lines carry `sweep_clean_line(remote=any on_remote)`; labels gain `stale`.
  Unkept merged = stale unless a worktree holds it.
- (d) `clean_sweep`: `fetch_keeps` before the inventory when `remote`
  (failure refuses the remote half), skip `kept and not stale` and any
  `bot_owned` name, report the skips.
- (e) docs (CONFIGURATION.md branches section ~line 346 statement becomes
  false), handler `get_claude_md` text, release note 007, config-changes
  (seven keys added, `breaking: false`), three truth-changes. Note: the
  bot_owned truth change and the "parked/merged no longer count toward
  wip.cap" truth change are ALREADY true in code after slice (a).
- `daemon/init_config.py` template blocks for `parked:`/`merged:`/`bot_owned:`
  are not yet added.

## Fixes after merging origin/main (166a28103)

- `Timeout.GIT_BRANCH_CREATION_CALLS` 2 -> 3 (the `--merged` call), so the
  WorktreeCreate budget grows by one `GIT_CONTEXT` and `init.sh`'s
  WorktreeCreate client wait is now 90 seconds, not 85. **The release note
  (slice e) must say so**, as v3.72.0's note 030 did for 85.
- `tests/unit/daemon/test_cli_branch_sweep.py` and
  `tests/unit/constants/test_event_budgets.py` updated to the pool counts and the
  five-field listing.
- `tests/unit/supervise/test_walk_opens_regular_files_only.py` came from main
  unformatted; the QA format step reformatted it and that is committed here.
- Main's early allow for a non-work `new_name` (N593) sits before every pool
  computation in `creation_verdict`; keep it there in slices b and c.

## QA

See the journal entry for this slice's targeted QA verdict on d6b19f4ef.
