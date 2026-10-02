# Plan 00470 Task 2.4: standing background watchdog cron

## Changes

- `.claude/hooks-daemon.yaml`: new `persistent_crons` job `background-watchdog`, schedule `37 * * * *` (off :00; failsafe is 47, issue-sdlc 23), no `hosts`. Prompt is the canonical watchdog text in self-install form.
- `background_process_tracker.py`:
  - `watchdog_cron_prompt()` no longer says to CronDelete when background work ends; it says an idle tick is a no-op and not to delete the cron. The advisory and `get_claude_md()` guidance carry the same wording.
  - The wrapper path in the prompt is now `daemon_cli_command_for_docs` (project-root-relative) instead of the absolute path. Reason: a live cron is matched to its declaration on the normalised prompt, so an absolute path would differ per checkout/worktree and the declaration could never be satisfied. Cron ticks fire from the project root, where the relative path runs. This is a behaviour change to what the advisory pastes (absolute to relative).
  - New `declares_watchdog_cron(config, hostname)` (by `[tick:watchdog]` sentinel, same shape as `declares_failsafe_cron`) and `_load_config`. When declared, `handle()` emits `_declared_advisory()`: no CronCreate, no prompt, no CronDelete; still says to run harvest-background and reap whole groups.
- `background_harvester.py`: `find_breaches` collapses breaches sharing a pgid (`_one_breach_per_group`): first record represents the group, reasons merged, max tree_pcpu, union of tree_pgids.

## Tests

- New `tests/unit/handlers/session_start/test_watchdog_cron_declaration.py`: declared prompt equals `watchdog_cron_prompt()` (pin), off-:00 and distinct schedule, assertor re-states it, enforcer finds it missing when absent, advisory-pasted cron satisfies it, idle-tick wording.
- Extended `test_background_process_tracker.py` (declared / undeclared / disabled section / no declaration advisory; no delete wording on any surface) and `test_background_harvester.py` (shared pgid listed once, text and JSON).
- Ran 658 passed: the 10 failsafe/persistent_cron/cron_stop/harvest/background test files, plus tests/daemon/test_init_config.py, tests/integration/test_claude_md_guidance_coverage.py, tests/integration/test_template_priorities_match_the_constants.py. `scripts/qa/check_generated_doc_drift.py`: no drift. ruff, black, mypy clean on changed files.

## Not done / notes

- Tests were written before the implementation but I did not capture a separate red run.
- CLAUDE.md's generated hooksdaemon section is unchanged (the drift check passes); nothing to regenerate.
- `test_failsafe_cron_multi_cron_ticks.py` still holds the old delete sentence inside `_REAL_AGENT_COMPOSED_WATCHDOG`; that is a recorded real agent-composed prompt, deliberately left.
- The daemon was not restarted, so the live session has not loaded the new declaration.
