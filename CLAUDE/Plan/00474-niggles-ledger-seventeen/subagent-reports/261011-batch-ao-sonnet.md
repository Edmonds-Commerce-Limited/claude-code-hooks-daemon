# Batch AO report (N423, N422, N421)

Worktree `worktree-batch-ao`. Targeted QA only; the daemon was not restarted.

## N423: the stated cause does not reproduce through the handler; the actual incident has a different cause

**What the brief said.** `_maybe_refresh_on_retirement` derives the plan root as `plan_md_path.parent.parent`; for an archived plan that is `<root>/Completed`, so no live plan is found and every owner is cleared.

**What I found.**

- The code reading is right at the method level. Red test, quoted failure:
  `AssertionError: the live plan 00298 was cleared with the archived one` (calling `_maybe_refresh_on_retirement` directly with a PLAN.md under `Completed/`).
- But it cannot be reached through `handle()`. `matched_plan_write_or_edit` returns `None` for any path containing `/Completed/`, so a Write/Edit inside `Completed/` never calls the retirement refresh (checked with an end-to-end repro: `matches()` is False, no `.goal-clear`). The sheet-B Edit that the verdict log shows `goal-injection` handling at 15:02:57 therefore landed on a non-`Completed` path.
- **The likely actual cause of the 15:02:59 clear**: commit a17535d43 (12:59 UTC, same day) set Plans 00470, 00474, 00479, 00484 and 00500 to `Blocked`. `GoalLedger.live_plan_numbers` counts only `In Progress` plans as live (`_plan_state`: `Blocked` is `other`). In `untracked/goal-ledger.json`, 00470, 00474, 00479 and 00484 are unretired entries but all `Blocked`, and 00500 was the last. When 00500 retired, `live_plan_refs` correctly returned nothing and every owner was cleared. That is the designed "no In Progress plan left" retraction, not a path-depth bug. So the "four plans were still live" premise in N423 holds for the `/goal` text but not for the ledger's definition of live.
- **Decision for the owner**: is a `/goal` that names only `Blocked` plans meant to be retracted when the last In Progress plan retires? I did not change that. Changing it would alter the Plan 00320/00321 retraction contract.

**What I changed anyway** (the latent defect is real and cheap to close): `plan_root_for(plan_md_path, archive_dirs)` and `archive_dirs_for(layout)` in `utils/plan_trigger.py`; `GoalInjectionHandler._plan_root` uses them at all three call sites (`_maybe_refresh_on_retirement`, `_write_combined_signal`, `_ledger_record`). It steps over the configured archive directory names (layout `plan_archive_dirs`, default `Completed`). I walked past the archive segment rather than resolving from config because the handler already derives the root from the written path (subproject plan trees keep working). The second `live_plan_refs` call site (line ~1482) and `record_emission`'s `plan_dir` had the same derivation and are fixed. `utils/goal_ledger.py` itself derives no root from a PLAN.md path.

Tests: `TestCombinedGoalSignal::test_retiring_an_archived_plan_keeps_the_other_live_plan`; `TestPlanRootFor` (3) in `tests/unit/utils/test_plan_trigger.py`.

## N422: main red, two invariants

- `install/effective_handlers.py` (`_is_write_protected`) now reads `write_protected_paths` options through `config.models.handler_options`.
- `AGENT_ID_EVENTS` is in `core/handler_scope.py` (not `constants/events.py`). It gates only `validate_scope_for_event`/`event_supports_scope`, used by config validation (`config/models.py`) and the probe (`daemon/hook_probe.py`). The three contracts do declare `agent_id` in `conditional_input_fields`/`input_example` (TeammateIdle: "the in-process teammate about to go idle"), so the contracts are right and the set was stale. Added `TeammateIdle`, `TaskCreated`, `TaskCompleted`.
- **What changes**: a handler on those events may now set `scope: MAIN` or `SUB` (previously refused at config load); `hooks-daemon probe` of those events now resolves a thread (default MAIN) and accepts `probe_as`, and adds the non-probe-source note. No existing handler's verdict changes (default scope is `ALL`). `tests/unit/config`, `tests/unit/install`, handler_scope and hook_probe tests: 2299 passed.

## N421: guard false positive

Red (4 failures in `TestSubstitutedProgramIsNotTheUpgrade` before the fix), e.g. `PYTHONPATH=/x/src $(ls -d /v/bin/python) -m pytest tests/x` was denied. A literal interpreter path and a `$PY` variable were already allowed. Cause: shlex split `$(ls -d p/python)` into `$(ls`, `-d`, `p/python)`; `_variable_program_is_upgrade` took `p/python)` as the script operand, could not read it, and `_cannot_tell_script` counted that as the upgrade because `PYTHONPATH` steers.

Fix in `handlers/pre_tool_use/upgrade_approval_guard.py`:

- `_join_leading_substitution` rejoins a leading `$(...)` or backtick program word; the command inside is itself checked with `_command_runs_upgrade`.
- A `$(`/backtick program is then judged like a `$` program (both `startswith` checks), so `-m <module>` decides, as for `$PY`.
- `-mpytest` (attached module) is read too, for variable and substituted programs.
- `_program_is_literal_tool` refuses a name containing `)`, so a substituted program is never treated as a "literal tool" and `$(ls -d /v/bin/bash) up.sh` stays denied.

Both directions are tested: 5 allowed shapes (the owner's `$W` shape, plain, attached `-mpytest`, backtick, quoted path) and 13 still-denied shapes (`PYTHONPATH=x bash scripts/upgrade.sh`, a variable holding `upgrade.sh`, substituted program running `scripts/upgrade.py`, `$SCRIPT`, `-c "$CODE"`, daemon `-m claude_code_hooks_daemon.x`, `-m pytest scripts/upgrade.sh`, `-m $MODULE`, a substituted upgrade, a trailing `; bash scripts/upgrade.sh`, a substituted bash running `up.sh`, `HOOKS_DAEMON_UPGRADE_HANDOFF=1 ...`, and a readable renamed upgrade script inside the substitution). 640 upgrade/approval handler tests pass.

Note: while working, my own scratch commands tripped this very guard twice (a heredoc python carrying `PYTHONPATH` plus a path through `scripts/../`), which is the same false-positive family; the `probe` route would hit the running daemon's code, not the worktree's, so unit tests were the reproducer.

## Release note

`CLAUDE/UPGRADES/UNRELEASED/release-notes/021-...md`. On main 019 exists and another worktree holds 020 (`020-stop-reentry-unreadable-transcript-and-fewer-inline-code-advisories.md`), so 021 is next free.

## QA

`./scripts/qa/llm_qa.py changed`: magic_values, format, lint, type_check, pyright, error_hiding, eacces_safe, docs_qa, shell_check, shell_audit and repo_hygiene all clean. The only finding is an unrelated plan_qa advisory (`journal-freshness`, Plan 00495 quiet for 5 days). The run noted the tree changed during `shell_check` because this report was written mid-run; no shell file was touched. A first `llm_qa` launch of mine timed out waiting for the host-wide QA lock held by batch AL.
