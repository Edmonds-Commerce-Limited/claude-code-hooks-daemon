# Task 4.4 handoff (stop guard), by p558-stopguard

Branch `worktree-558-stopguard`, pushed. Head 25597d0ba. Python for tests: `PYTHONPATH=src /workspace/untracked/venv-workspace-py313-0d6d49c6/bin/python -m pytest <file> --no-cov -p no:cacheprovider` (`/workspace/.venv` has no pytest). Create `untracked/scratch/` first in a fresh worktree.

## Done (committed)

- `constants/timeout.py`: `Timeout.GIT_STOP_GUARD_BUDGET = 8.0` (under `CHAIN_DEADLINE_DEFAULT`).
- `core/branch_records.py`: `touched_by_session(repo, session_id) -> dict[branch, set[agent_id]]` (main thread = `""`); `touched_branches` now shares the parser.
- `core/branch_stop_guard.py`: `judge_stop(repo, inventory, config, *, session_id, agent_id, handoff, budget) -> StopJudgement(findings, tips, incomplete)`; `StopFinding(branch, check, tip, commands, advisory)`; `StopCheck` DIRTY/UNPUSHED/MERGED. Scope per DESIGN section 6 (coordinator owns sub-agents' unpushed and merged, not their dirty); default and integration lines excluded unless `include_default`; `unpushed_subagent` block/advise/off; handoff waives MERGED only; budget exhausted gives `incomplete`, never a finding.
- `tests/unit/core/test_branch_stop_guard.py`: 20 tests pass.

## Not done

1. Two handlers: `handlers/stop/branch_stop_guard.py` (priority 9, MAIN scope, non-terminal) and `handlers/subagent_stop/branch_subagent_stop_guard.py` (priority 12, SUB scope, non-terminal). Pattern: `subagent_handoff_gate.py` (`MAX_STOP_BLOCKS`, `STATE_HARD_ENGAGED` via `state_path(untracked, session, STATE_KIND, agent)`). `_branches: BranchesConfig` attribute is injected by the registry (see `branch_creation_guard.py`). Handler flow: allow if `hook_is_usage_paused(hook_input)` or `(untracked / RELEASE_STATE_FILENAME).exists()` (from `handlers/stop/idle_workable_issue_stop_gate.py`); `mode` off/warn from `config.stop_guard.mode`; `build_inventory(repo, branches)` (catch `BranchInventoryError`, allow); `judge_stop`; block count in spend-ledger state kind `branch-stop-guard`; after 3 blocks allow and log/record "abandoned at stop" (SessionStart reporting of that is not built). Reason names branch, check, commands, appends `BRANCH_LIMIT_PRINCIPLE` (`constants/branch_guard.py`), and on handoff the branch and tip sha. Advisory findings go in `context`. Need a RuleID (e.g. `R-BRANCH-STOP-GUARD` in `constants/rule_ids.py`) and `.under_rule`.
2. Noisy line: at main-thread Stop when allowing, list records with `dormancy_stage` in NOISY/BLOCK as `context`, at most hourly, `noisy_last` in the same state document.
3. Registration (mirror `branch_touch_recorder`): `constants/handlers.py` IDs, `constants/priority.py`, `handlers/stop/__init__.py` and `handlers/subagent_stop/__init__.py`, `daemon/init_config.py` template lines, `.claude/hooks-daemon.yaml` (enable both, set `branches.stop_guard.unpushed_subagent: advise` with comment: this repo's sub-agents commit without pushing and the coordinator merges locally, until the owner rules on Q5), `get_claude_md`, acceptance tests or `harness_cannot_produce`, config-changes manifest `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.72.0.yaml` entries, and `tests/integration/test_claude_md_guidance_coverage.py` / bash-write-blindness lists if they enumerate handlers. Regenerate CLAUDE.md guidance the way the repo does.
4. Handler unit tests (TDD), release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/032-branch-stop-guard.md` (`# Callout:`, `**Plan**: 00558`).
5. Targeted QA: `FULL_QA_LOCK_WAIT_SECONDS=5400 ./scripts/qa/llm_qa.py changed > untracked/scratch/qa-558-stopguard.txt 2>&1` in the background.

## Notes

- Inventory pass time is not charged against the 8 s budget.
- A sub-agent's MERGED check blocks for any branch it touched that is merged (the "only if it merged it" refinement is not tracked).
