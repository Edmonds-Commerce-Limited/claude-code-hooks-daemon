# Phase 3 report: three branch pools (slices a to e), targeted QA green

Branch `agent-ab77ce31393d94cc9-a05306f2`. Design: `phase-3-pools-handoff.md`. Earlier
progress: `phase-3-pools-impl.md`, `-impl-2.md`, `-impl-3.md`. This agent did slices (d) and (e),
merged `origin/main` (at `ca1d8f961`) and ran targeted QA.

## Slices

- **(a) config and inventory.** `BranchPoolConfig` / `BranchParkedConfig` / `BranchMergedConfig`,
  `BranchesConfig.parked`, `.merged`, `.bot_owned` (default `["dependabot/*"]`),
  `effective_pool_cap` (null = `wip.cap`), `effective_pool_max_age` (null = dormancy `block_days`).
  `BranchState.BOT_OWNED`, `Pool`, `pool_of`, and the `BranchRecord` fields `stale` and `park_count`.
- **(b) parked pool.** Park age is computed from the tip. `R-BRANCH-PARKED-POOL` denies at the cap
  or when a member is stale. A re-park with the same reason raises `BranchParkSameReason` (CLI exit 2).
  The sweep shows `STALE`, `re-parked N times` and one footer line per pool.
- **(c) merged pool.** `core/branch_keep.py` stores keep notes in `refs/notes/hooks-daemon/keep`,
  with a per-remote tracking ref. `branch-keep <name> --reason` exits 1 when the branch has no record
  or is not merged, and 2 when the reason is the same. An unkept merged branch is stale at once
  unless a worktree holds it. `R-BRANCH-MERGED-POOL` is the fourth rule in the creation verdict.
  The extra `for-each-ref --merged` call raises the `init.sh` WorktreeCreate wait from 85 s to 90 s.
- **(d) `clean_sweep`** (`core/branch_cleanup.py`). With `remote`, `branch_keep.fetch_keeps` runs
  BEFORE `build_inventory`. If it fails, the remote half is not attempted and the run reports
  `"<remote>: keep notes could not be fetched (<err>), so the remote half was refused"`; the local
  half still runs. `_spared()` skips a keep that is not stale (`kept: <reason>`) and any
  `bot_owned` name, on both sides, and reports each skip (`origin/<name>: ...` for the remote side).
  A stale keep is still a candidate. Tests: `tests/unit/core/test_branch_cleanup_keeps.py`, 7 tests
  (kept skipped, lapsed cleaned, unkept cleaned, bot-owned never cleaned, kept remote skipped, keep
  from another clone fetched first, failed fetch refuses the remote half). The four tests that
  exercise new behaviour failed before the implementation.
- **(e) docs and release material.**
  - `docs/guides/CONFIGURATION.md`: a new "Branch pools" section with a table, `branch-keep`,
    `bot_owned` and an example. The claim that a parked branch "still counts against the WIP cap"
    is corrected. The paragraph on `--clean --remote` now covers the keep fetch.
  - `docs/guides/HANDLER_REFERENCE.md`: the branch_creation_guard description names all four
    rules. The "merged ones first" sentence was false and is removed.
  - `daemon/init_config.py`: the template gains `parked:`, `merged:` and `bot_owned:` blocks. The new
    test `test_full_template_writes_out_every_pool_key` failed first, then passed.
  - `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.73.0.yaml`: seven `added` keys, `breaking: false`,
    date `UNRELEASED`.
  - Three `git-safety` truth changes, appended to the existing
    `UNRELEASED/truth-changes/v3.73.0.yaml` (the same target version as Plan 00573's draft).
  - Release note `UNRELEASED/release-notes/007-branch-pools-parked-merged-caps.md`. It states the
    90-second WorktreeCreate wait (was 85). `test_pending_release_notes_holding_area.py` passes.

## QA fixes made in this pass

- black reformatted `branch_keep.py`, `branch_creation.py`, `branch_inventory.py` and three test
  files.
- bandit B603/B607 in `cmd_branch_keep`: `user.name` is now read through `run_git`.
- `error_hiding` (return-none-on-error) in `branch_keep._epoch`: the `ValueError` now goes through
  `log_and_continue` with a specific reason.
- pyright: the cleanup-keeps test passes `BranchMergedConfig(max_age_days=7)`.

## Verdict

`llm_qa.py changed --range origin/main..HEAD --allow-unmapped`: **42/42 PASSED**. changed_tests:
6134 passed, 0 failed, 5 skipped, in 76 test files mapped from 36 changed files. Fourteen files are
unmapped as too broad (models.py, cli.py, the branch core modules, init.sh, the truth-changes yaml);
only the full gate covers them, which is the coordinator's run.

## Notes for the coordinator

- The worktree holds an untracked file that is not from this plan:
  `CLAUDE/Plan/00474-niggles-ledger-seventeen/subagent-reports/261107-fact-check-n596-3.md`.
  Another agent wrote it. It is not committed here.
- The release note credits "(issue #165)" without "reported as": whether that issue was reported
  externally is not established here. If it was, the release should change the wording.
- `HANDLER_REFERENCE.md:5259`, the summary row "a new branch while open work branches are at
  branches.wip.cap", is left as it is. It is still true but incomplete.
