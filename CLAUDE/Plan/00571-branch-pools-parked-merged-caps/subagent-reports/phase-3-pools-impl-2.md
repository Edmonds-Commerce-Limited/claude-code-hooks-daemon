# Phase 3 handoff 2: slice (b) done; (c), (d), (e) remain

Branch `agent-a5e6c43d269df7fa9-29a107d6` (contains slice (a) branch `agent-aa87210ca7838e9c4-79b323ad`
and main; origin/main was already merged into it, so the second merge was a no-op).
Design: [phase-3-pools-handoff.md](phase-3-pools-handoff.md); slice (a): [phase-3-pools-impl.md](phase-3-pools-impl.md).
This agent stopped at its context budget after committing and pushing slice (b).

## Environment notes (save the next agent time)

- The worktree had no venv. `bin/hooks-daemon repair` built one at
  `untracked/venv-workspace_claude_worktrees_agent-a5e-a5ba-py313-0d6d49c6/bin/python`
  (use the ABSOLUTE path; the main checkout's venv fails `tests/source_tree_guard.py`).
  Run tests with `-p no:cacheprovider --no-cov`, output redirected to `untracked/scratch/`
  (no pipes to tail/head; `tail -n N file` is fine).
- Hook gotchas: `sed`, `grep` for CamelCase symbols and pipes to tail are blocked; the post-edit
  lint hook reports F821/F401 transiently when an import edit and its use land in separate
  Edit calls: ignore it if the later edit completes it.

## Slice (b): DONE (commit "Plan 00571 Phase 3 slice (b) ...")

- `constants/rule_ids.py`: `BRANCH_PARKED_POOL`, and `BRANCH_MERGED_POOL` (added now for slice c).
- `core/branch_park.py`: `BranchParkSameReason(BranchParkError)`, `_refuse_same_reason`
  (compares the tip's `Parked-Reason` trailer), used by the local and remote-only paths; not on `--clear`.
  `daemon/cli.py::cmd_branch_park` maps it to exit 2.
- `core/branch_inventory.py`: `BranchRecord.stale`, `.park_count`; `_with_pools(repo, config, records)`
  after `_with_same_tips` (parked stale = mode != off and age_days >= `effective_pool_max_age(PARKED)`;
  `_park_count` = one `git log --first-parent -n 64` per parked tip). Only parked records are filled so far.
- `core/branch_sweep.py`: JSON keys `stale`, `park_count`; `_parked_line` prints `STALE (past branches.parked.max_age_days N)` and `re-parked N times`.
- `core/branch_creation.py`: `write_labels` stores `"stale": "true"|None`; `clear_label_stage` clears it;
  `_stale_parked`, `_parked_pool_lines`; `creation_verdict` computes `parked` (pool PARKED groups of
  `all_groups`), `over_parked`, appends its lines after dormancy, deny precedence WIP_CAP, DORMANT,
  PARKED_POOL; mode warn gives a warn verdict, off skips. Uses `daemon_cli_command_for_docs`.
- `handlers/pre_tool_use/branch_creation_guard.py`: `_parked_rule`, `_rules_by_id` map used in `handle`.
- `daemon/playbook_harness.py::BRANCH_STATE_RULE_IDS` now lists all four branch rule ids.
- Tests: `TestParkedPool` in `tests/unit/core/test_branch_pools.py`, park tests in
  `test_branch_park.py` and `test_cli_branch_park.py`, a handler deny test and the rules-list
  assertion in `test_branch_creation_guard.py`, `TestLabels.test_round_trip` gains `"stale": None`.
- 755 tests in `tests/unit/core`, the park CLI, the harness and the guard/worktree handlers pass.
  Targeted `llm_qa.py changed` has NOT been run yet.

## Remaining (unchanged design; see the earlier handoff for detail)

- (c) `core/branch_keep.py` (tests first in `tests/unit/core/test_branch_keep.py`), `branch-keep` CLI beside
  branch-park (`cmd_branch_keep`, parser; exit 1 no record / not merged, exit 2 same reason),
  inventory `_with_pools` merged half (kept fields on `BranchRecord`: `kept_reason`, `kept_by`,
  `kept_at`; unkept merged = stale unless a worktree holds it or `worktree_known` is False),
  merged cap + stale in `creation_verdict` (labels `stale` for merged groups; deny lines carry
  `sweep_clean_line(remote=any on_remote)` from `core/branch_cleanup.py` plus `branch-keep <name> --reason`),
  a `_merged_rule` in the handler (add to `_rules_by_id`, `get_rules`; update the rules-list test),
  `get_claude_md` text for three pools. Existing `test_branch_creation.py` `TestCapNamesTheCleanCommand`
  must be checked against the moved clean line.
- (d) `core/branch_cleanup.py::clean_sweep`: `fetch_keeps` before inventory when `remote`
  (failure refuses the remote half), skip `kept_reason and not stale` and bot_owned names, report skips.
- (e) `docs/guides/CONFIGURATION.md` branches section (~line 346), `daemon/init_config.py` template blocks
  (`parked:`, `merged:`, `bot_owned:`), config-changes entry (seven keys, `breaking: false`), three
  truth-changes (read `CLAUDE/UPGRADES/UNRELEASED/README.md`), release note
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/007-<slug>.md` (format in the dispatch: `# Callout: ...`,
  blank, `**Plan**: 00571`, `**Audience**: client projects`, blank, body; MUST state the init.sh
  WorktreeCreate client wait is now 90 seconds, was 85, from the extra `--merged` git call).
  Root `CLAUDE.md` rule table is auto-generated (it lists R-BRANCH-DORMANT): do not hand-edit; check
  whether a test compares it and regenerate through the daemon restart path if so.
  Also check `docs/guides/HANDLER_REFERENCE.md` and the CHANGELOG-style files for rule-id lists.
- Finally run targeted QA: `FULL_QA_LOCK_WAIT_SECONDS=3600 <venv python> ./scripts/qa/llm_qa.py changed --range origin/main..HEAD --allow-unmapped`.
