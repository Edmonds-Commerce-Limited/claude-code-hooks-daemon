# Plan 00558 Phase 2: Tasks 2.2 and 2.3 (branch `worktree-558-sweep`)

## What was built

- `src/claude_code_hooks_daemon/core/branch_sweep.py`: the report layer over `core/branch_inventory.py`. It runs no git. Groups (`group_records`), the open-work count (`open_work_count`: every non-exempt, non-default, non-line, non-protected branch, merged and unclassified included, names linked by `same_tip_as` counted once, DESIGN.md section 3), the cap (`effective_wip_cap`: `branches.wip.cap` when set, else the old `max_open_branches`, else the model default 10), the deprecation line, the CLI text, the `--json` document and the SessionStart summary.
- `hooks-daemon branch-sweep` (`daemon/cli.py`, `cmd_branch_sweep`): text grouped CONTAINED NOWHERE, merged not deleted, patch-equivalent, dormant, live, parked, not yet classified, then `Open work: N of C (branches.wip.cap)`. `--all` adds the never-work branches. `--json` prints every record with `JSON_RECORD_KEYS` (listed in the verb's `--help` epilog). Exit 0 for any report, 1 when `build_inventory` raises (not a repository). No `--clean`.
- `handlers/session_start/branch_sweep.py` (`BranchSweepHandler`, key `branch_sweep`, priority 56), replacing `branch_count_advisor` (module and its tests deleted, `Priority.BRANCH_COUNT_ADVISOR` and `HandlerID.BRANCH_COUNT_ADVISOR` renamed to `BRANCH_SWEEP`).
- The alias: `constants.handlers.HANDLER_KEY_ALIASES` (`{"session_start": {"branch_count_advisor": "branch_sweep"}}`), folded by `config.models.fold_handler_aliases` in a `mode="before"` validator on `HandlersConfig`. Either key's `enabled: false` disables; options merge, the new key winning. The config validator accepts an alias key as known. Pinned end to end in `tests/unit/handlers/test_registry_branches_injection.py` (old `enabled: false` leaves the handler unregistered; old options reach `_max_open_branches`).
- Config-changes manifest `changed` entry for `handlers.session_start.branch_count_advisor` with a `migration_note`; release note `024-branch-sweep-report-and-summary.md` (also covers the Task 2.0 `delete-branch`/`worktree-reap` default change); the init-config template and this repository's `.claude/hooks-daemon.yaml` now name `branch_sweep` without the old options.

## Decisions to check

1. **"Contained nowhere" is a dormant branch whose containment is `NOWHERE`.** The inventory measures containment only for dormant branches (DESIGN.md section 4), so a live unpushed branch is not loud. This repository's sub-agent branches are never pushed; making every live local branch loud on every session would fire on all of them.
2. **Fail-closed reading.** A dormant branch with unmeasured containment (budget ran out) is listed as dormant with "containment not measured", never as a cleanup candidate. A remote-only merged branch whose proof is an unpushed local ref gets no delete command ("push <ref> first"); one proven by `<remote>/<default>` gets `git push <remote> --delete <name>`. A branch merged into a line or patch-equivalent to one gets `delete-branch <name> --protected-ref <proving ref>`.
3. **Source split.** Contained-nowhere lines on every SessionStart source; dormant lines, the merged count, the unresolved-default warning and the count-vs-cap line on new sessions only. The count line appears when `count >= cap`. At most 10 branch lines, then `and N more: run \`bin/hooks-daemon branch-sweep\`\`.
4. **A branch at the default tip is "merged"** (the inventory's verdict), so a freshly created, still-empty branch shows as merged-not-deleted. That is the inventory's existing classification; not changed here.
5. **This repository's cap is now 10**, because the old `max_open_branches: 3` was dropped from `.claude/hooks-daemon.yaml` (DESIGN.md section 1: "drops the two old options"). Reconciling with `CLAUDE/Worktree.md`'s 3 stays Task 5.1's.

## Not done

- **The behind-default warning is not in the new summary.** The old advisor named branches more than `behind_main_threshold` commits behind; the brief's summary list does not include it, so `branches.sweep.behind_threshold` is now read by nothing except the deprecation line. Records carry `behind` (in `--json`). Either add a line or drop the key; owner/lead call.
- The 14-day noisy and 30-day block stages (Task 4.3) were not built.

## SessionStart timing on this repository

`untracked/scratch/time_sweep.py` (worktree), the handler's `handle()` called directly with the repository's config, cache deleted first: cold 1,536 ms and 1,494 ms (two runs), warm 44-57 ms. Under the 3,000 ms `sweep.budget_ms`. Caveat: `budget_ms` bounds only the per-branch step 5 and containment; the bulk steps (for-each-ref, worktree list, `--merged`) are bounded only by each git call's own timeout, as in the inventory module.

## Evidence

Targeted tests: `tests/unit/core/test_branch_sweep.py`, `tests/unit/handlers/session_start/test_branch_sweep.py`, `tests/unit/daemon/test_cli_branch_sweep.py`, `tests/unit/handlers/test_registry_branches_injection.py`, `tests/unit/config/`. The QA verdict is in the journal entry and the reply to the lead.
