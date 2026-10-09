# N359: plan fact-check feed fixes

Branch `agent-a2c1639ebf327c0d2-c58056dc`, not merged. Unblocks Plan 00480 Task 4.4 once merged and the daemon restarted.

## Rules chosen

1. **Worktree paths: ignore.** `_plan_matches` skips a write whose enclosing checkout (via `enclosing_checkout`, the shared worktree helper) is a worktree nested under `ProjectContext.project_root()`. Mapping to the main root was rejected: a sub-agent's edit does not change the main tree until a merge, so a map would debounce and diff unchanged content. A session whose own root is the worktree still feeds, because its paths are not nested under its root. A path outside the project root is ignored.
2. **Archived plans: deliver with the resolved path, drop if gone.** `resolve_plan_root` returns the recorded folder, else `<plan dir>/Completed/<folder>`, else `None` (record dropped, content left owed).
3. **First sight:** `process_quiet_plan` with no checked content records a baseline and returns nothing.
4. **Lost delivery.** The daemon cannot see whether text arrives, so delivery no longer calls `record_checked`. A delivered record is kept as `<folder>.offered.json`. The checked content advances in `confirm_dispatch`, when the main thread dispatches a `Task`/`Agent` call with `subagent_type: plan-fact-checker` whose prompt contains the diff path (the instruction now asks for that). An offer unconfirmed after 300 s is re-offered, at most 3 offers, then dropped with a WARNING and the content stays owed (the next diff folds it in). A newer pending record supersedes an offer.
5. **Correction loop: absorb small edits soon after a confirmed check.** An edit of at most 20 changed lines within 600 s of the confirmed check (`checked_at`) is recorded into the checked content without owing a check, so one check covers its burst plus its corrections. The window is anchored on the confirmed check and does not slide. Not applied while a check for that plan is pending or offered. The risk accepted: a genuinely new small false claim inside that window goes unchecked; the size and time bounds keep it narrow. The diff-restates-findings variant was rejected (the daemon cannot read the checker's report).
6. **Stale comments** in `.claude/hooks-daemon.yaml.example` and `init_config.py` rewritten.

Handlers keep `handle()` short; the constants (`REOFFER_AFTER_SECONDS`, `MAX_OFFERS`, `CORRECTION_WINDOW_SECONDS`, `CORRECTION_MAX_CHANGED_LINES`) are named in `utils/plan_fact_check.py`.

## Tests (test-first through the real handler and util)

`tests/unit/handlers/post_tool_use/test_plan_fact_check_feed.py` (`TestWorktreePaths`, `TestFirstSight`, `TestDelivery`) and `tests/unit/utils/test_plan_fact_check.py` (`TestProcessQuietPlan`, `TestDelivery`, `TestCorrectionLoop`). Existing tests that assumed a first-fire pending record or delivery-time `record_checked` were rewritten to the new contract (they seed a baseline).

## Notes

- A pending or checked file written by the previous build still reads: `offers`, `offered_at` and `checked_at` are optional.
- Release callout: `CLAUDE/UPGRADES/UNRELEASED/release-notes/002-plan-fact-check-feed-delivers-the-right-check-once.md`.
- This worktree had no venv; built one with `bin/hooks-daemon repair` and installed pytest into it.
