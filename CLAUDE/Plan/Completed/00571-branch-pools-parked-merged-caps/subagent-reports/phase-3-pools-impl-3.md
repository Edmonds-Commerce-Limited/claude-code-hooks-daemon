# Phase 3 handoff 3: slice (c) done; (d), (e) and targeted QA remain

Branch `agent-ab77ce31393d94cc9-a05306f2` (it contains slices a and b plus current main). Slice (c) is
committed and pushed. This agent stopped at its context budget.

## Environment

- Venv for this worktree (built with `bin/hooks-daemon repair`):
  `untracked/venv-workspace_claude_worktrees_agent-ab7-3044-py313-0d6d49c6/bin/python` (use it by a
  relative-from-worktree path, NOT through a shell variable: a computed command name is refused).
- Run tests as `<venv python> -m pytest -p no:cacheprovider --no-cov --color=no -q <paths> > untracked/scratch/x.txt 2>&1`
  then `tail -n 30 untracked/scratch/x.txt`. Without `--color=no` the output floods your context.
- Chain every Bash command with `&&` only: a `;` sequence is denied (R-BASH-SAFE-MODE-PRELUDE-MISSING) and any pipe to tail is denied.
- `tests/unit/core`, `tests/unit/daemon`, `tests/unit/constants`, `tests/unit/handlers/worktree_create`
  (7641 tests) and the guard handler test pass on the slice (c) commit.

## Slice (c): DONE

- `core/branch_keep.py` (new, tests in `tests/unit/core/test_branch_keep.py`): `KEEP_NOTES_REF`,
  `keep_tracking_ref`, `Keep`, `KeepResult`, `parse_keep_note`, `read_keeps(repo, tips, remote)` (offline),
  `fetch_keeps(repo, remote) -> str | None` (error text), `keep_branch(...)`, `BranchKeepError`, `BranchKeepSameReason`.
- `core/branch_inventory.py`: `BranchRecord.kept_reason/kept_by/kept_at`; `_with_merged_pool` (called from `_with_pools`,
  which now takes `moment`): unkept merged is stale unless a worktree holds it or worktrees are unknown;
  a keep older than `effective_pool_max_age(MERGED)` is stale.
- `core/branch_sweep.py`: merged lines show `kept: ... (by X)`, `STALE (unkept|keep lapsed, past branches.merged.max_age_days N)`
  and a `keep it instead: branch-keep <n> --reason ...` line; JSON gained `kept_reason`, `kept_by`, `kept_at`.
- `core/branch_creation.py`: `_stale_merged` (labels `stale`), `_merged_pool_lines` (carries
  `sweep_clean_line(remote=any on_remote)`), merged pool in `creation_verdict` (deny rule `BRANCH_MERGED_POOL`
  after WIP_CAP, DORMANT, PARKED_POOL), `clear_label_stale`.
- `daemon/cli.py`: `cmd_branch_keep` and the `branch-keep` parser (exit 1 no record or not merged, 2 same reason).
- `handlers/pre_tool_use/branch_creation_guard.py`: `_merged_rule`, `get_rules` (four rules), `get_claude_md` for three pools.
- Tests: `TestMergedPool` in `tests/unit/core/test_branch_pools.py`, `tests/unit/daemon/test_cli_branch_keep.py`.

## Remaining

- (d) `core/branch_cleanup.py::clean_sweep` (tests first, in `tests/unit/core/` beside the existing clean_sweep tests):
  - when `remote`, call `branch_keep.fetch_keeps(repo, config.remote)` BEFORE `build_inventory`; on an error text, skip the
    whole remote half (do not call `_proven_remote`) and add `"<remote>: keep notes could not be fetched (<err>), so the remote half was refused"` to `skipped`; the local half still runs.
  - candidates (local list and `_proven_remote`) skip `record.kept_reason is not None and not record.stale`
    (report `"<name>: kept: <reason>"`) and any name matching `config.bot_owned` (the state already excludes them: defence in depth).
    A stale kept branch IS a candidate. Note `build_inventory(repo, config)` in clean_sweep has no `now`; fine.
  - `render` already prints `skipped`.
- (e) docs and release material (see handoff 2 "Remaining (e)"): `docs/guides/CONFIGURATION.md` branches section (~line 346),
  `daemon/init_config.py` template blocks `parked:`, `merged:`, `bot_owned:`, config-changes entry (seven keys, `breaking: false`),
  three truth-changes (read `CLAUDE/UPGRADES/UNRELEASED/README.md`), release note
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/007-<slug>.md` (`# Callout: ...`, blank, `**Plan**: 00571`, `**Audience**: client projects`,
  blank, body; MUST state the init.sh WorktreeCreate client wait is now 90 seconds, was 85). Check the root `CLAUDE.md` rule table
  is not compared by a test (it is auto-generated; do not hand-edit). Also check `docs/guides/HANDLER_REFERENCE.md`.
- Then: targeted QA `FULL_QA_LOCK_WAIT_SECONDS=3600 <venv python> ./scripts/qa/llm_qa.py changed --range origin/main..HEAD --allow-unmapped`
  and fix what it finds (black/ruff/mypy on the new files; `branch_keep.py` has one long line in `_kept_tips` and `_push` that black will reformat).
- Finally the full Phase 3 report `phase-3-pools-impl-be.md` in this folder, commit and push.
