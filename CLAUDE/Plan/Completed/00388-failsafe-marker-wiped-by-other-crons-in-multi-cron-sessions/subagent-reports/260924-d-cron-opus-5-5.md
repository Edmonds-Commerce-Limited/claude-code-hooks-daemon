# Delivery report — Plans 00388 and 00394 (d-cron, Opus 5.5)

Branch `worktree-d-cron`, worktree `untracked/worktrees/worktree-d-cron`.
Plan 00394 carries a pointer to this file.

## Rulings recorded

- **00388: approach 2′.** Recorded in PLAN.md next to the open question.
- **00394: options 1 and 2, not 3.** Recorded in PLAN.md next to the open question.

## Reproduction (00388 — the defect still reproduced today)

Tested against the unchanged handler with real prompts lifted from this
repository's session transcripts (`untracked/scratch/probe_marker_cleared_by_other_cron.py`):

```text
issue-sdlc (real, delivered)             matches=True decision=allow marker_survived=False
watchdog (real, agent-composed)          matches=True decision=allow marker_survived=False
issue-sdlc with [tick:job:issue-sdlc]    matches=True decision=allow marker_survived=False
watchdog with [tick:watchdog]            matches=True decision=allow marker_survived=False
```

After the fix, the last two rows read `deny/True` and `allow/True`. The first two
rows do not change: they are the residual that 2′ accepts.

## Per-task outcomes — Plan 00388

| Task | Outcome                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1.1  | Decided: 2′ (coordinator ruling).                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| 2.1  | Fixed. RED first (import-level, plus the behavioural probe above). `tests/unit/handlers/user_prompt_submit/test_failsafe_cron_multi_cron_ticks.py`, driven by the real delivered issue-sdlc prompt and a real agent-composed watchdog prompt.                                                                                                                                                                                                                                   |
| 2.2  | Fixed. `utils/cron_tick.py` holds the sentinel. The suppressor now clears the marker only for a prompt that carries no sentinel. `background_process_tracker.watchdog_cron_prompt()` is supplied verbatim. `cron_enforcement.declared_tick_prompt()` renders declared jobs for the assertor and the Stop-enforcer block, and `_prompts_match` strips sentinels. Every fail-open path is kept, pinned by `TestADeclaredCronStandsDownWithTheMarker` and the existing suite.      |
| 2.3  | Fixed. `TestAnotherCronsTickLeavesTheCadenceAlone`.                                                                                                                                                                                                                                                                                                                                                                                                                             |
| 2.4  | Fixed. A declared job's tick is dropped under a live marker (`R-DECLARED-CRON-SUPPRESSED`), pinned by `TestADeclaredCronStandsDownWithTheMarker`. The watchdog's tick is never dropped (`test_the_watchdog_is_never_stood_down`). For 00392 N1, the issue-sdlc runbook (`CLAUDE/development/IssueSdlc.md`) now tells a tick whose eligible backlog is entirely `agent-needs-human` to stop with `[awaiting-human]`. Without that, nothing arms the marker in the observed case. |
| 2.5  | Fixed. `TestAStoodDownIssueLoopResumesOnTheHuman::test_both_crons_resume_after_a_genuine_prompt`.                                                                                                                                                                                                                                                                                                                                                                               |

### DBF sweep (00388)

- **Class**: a UserPromptSubmit classifier that decides "automated tick or human"
  from the failsafe literal alone.
- **Instances found (3)**: the suppressor (the defect), `standing_authorisations._is_automated_prompt`
  and `skill_scan.constants.EXCLUDE_CONTENT_MARKERS`. They were found by grepping
  for the literal and for `_AUTOMATED_PROMPT_MARKERS`-style tuples. All three
  now recognise the sentinel. `idle_housekeeping_advisor` keys on the failsafe
  literal deliberately, because it is about failsafe ticks only, so it keeps it.
- **Defence**: the row `automated-prompt-classifiers-reach-the-tick-classifier`
  in `scripts/qa/declared-invariant-pairs.yaml`. It fires on the pre-fix sources
  (proof registry `untracked/scratch/dbf-registry-orig.yaml`, exit 1) and passes
  on the fix. `skill_scan` is a tuple, not a function, so a `reaches` row cannot
  cover it. It is pinned by `test_every_daemon_cron_tick_is_machine_traffic`.

## Per-task outcomes — Plan 00394

| Task | Outcome                                                                                                                                                                                                                                                                                                                                       |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1.1  | Decided: options 1 and 2 (coordinator ruling).                                                                                                                                                                                                                                                                                                |
| 2.1  | Fixed. `tests/unit/handlers/session_start/test_failsafe_cron_session_advisor.py::TestASessionWithNoPlanWorkIsStillCovered`.                                                                                                                                                                                                                   |
| 2.2  | Fixed. Option 1: a `failsafe-recovery` job in `.claude/hooks-daemon.yaml` at `47 * * * *`. Option 2: the new `failsafe_cron_session_advisor` (SessionStart, new sessions only, follows `recovery_cron_advisor`'s switch, silent when the failsafe cron is declared).                                                                          |
| 2.3  | Fixed. `TestThisRepositoryHasExactlyOneFailsafeSurfaceAtSessionStart`. It checks that the declared prompt is byte-identical to `CANONICAL_CRON_PROMPT`, that at most one SessionStart surface speaks, that there is no second identity, and that a cron made from any surface satisfies the enforcer. Every surface also says CronList first. |
| 2.4  | Fixed. A correction note sits under the claim in `Completed/00384-…/PLAN.md`. Plan 00393 already quotes the claim as half-true.                                                                                                                                                                                                               |

### Two interactions the 00394 ruling had to settle

1. **Declared means enforced.** `cron_stop_enforcer` requires a declared job, but
   the completion advice said to `CronDelete` the failsafe cron once the session
   was finished. Where the failsafe cron is declared, the completion advice now
   says to keep it (`test_a_declared_failsafe_cron_is_never_advised_for_deletion`).
   The canonical prompt itself still says "remove it only once the session is
   genuinely finished". I did not change it, because 00394's non-goal forbids
   rewording it. So in this repository an agent that follows the prompt at
   session end gets one blocked stop and re-creates the cron. That costs one turn
   and cannot leave the session uncovered.
2. **The schedule is matched exactly.** The live failsafe cron in this session
   runs at `:47`, so the job is declared at `47 * * * *`. Any other minute would
   have made the enforcer demand a second failsafe cron here after the merge. An
   agent that creates the failsafe cron at a different minute from the
   PostToolUse creation advice (which suggests :17 or :37) before seeing the
   assertor would hit the same demand. In practice the assertor speaks first, at
   session start.

## Residual risks, stated plainly

- **Crons that already exist keep their old prompts.** This session's live
  `issue-sdlc` and watchdog crons carry no sentinel, so they still clear the
  marker until the next session re-creates them. I did not delete or recreate
  any cron. They still satisfy their declarations: `cron_enforcement` strips
  sentinels before matching, and a test pins this.
- **Text the daemon never supplied still reads as the human.** That covers
  agent-composed prompts, `/loop` and `ScheduleWakeup`. This is the accepted 2′
  residual, and it fails toward clearing.
- **The ccy-supervisor nudge (`🤖 [ccy-supervisor …`) still clears the marker in
  the suppressor**, although `standing_authorisations` treats it as automated. It
  is not a cron tick and is outside this ruling. It is recorded here so it is not
  lost.
- **The canonical prompt is 996 characters**, under the 1000-character delivery
  cap (pinned by `test_the_prompt_fits_under_the_delivery_cap`). An agent that
  re-flows it can still push it over the cap. Truncation-prefix matching already
  handles that case.

## Files shared with the parallel branch `worktree-n422-owner-b`

Seven files are touched by both branches:

- `.claude/hooks-daemon.yaml`
- `CLAUDE/UPGRADES/UNRELEASED/truth-changes/v3.67.0.yaml`
- `CLAUDE/development/IssueSdlc.md`
- `docs/guides/HANDLER_REFERENCE.md`
- `src/claude_code_hooks_daemon/handlers/session_start/persistent_cron_assertor.py`
- `src/claude_code_hooks_daemon/utils/cron_enforcement.py`
- `tests/unit/handlers/session_start/test_persistent_cron_assertor.py`

`git merge-tree` reports content conflicts in three of them, and all three are
mechanical: keep both sides.

- **`persistent_cron_assertor.py`**: the import block, plus the last line of
  `_render_job`, which becomes `declared_tick_prompt(job).splitlines()`.
- **`cron_enforcement.py`**: the import block only.
- **`truth-changes/v3.67.0.yaml`**: two appended entries on each side.

There is no semantic interaction. I did not touch `cron_stop_enforcer.py`, the
SubagentStop enforcer or `blockage_marker.py`.

## Release-bound consequences

- Release notes 48 (Plan 00388) and 49 (Plan 00394), renumbered 29 and 30 at
  integration B2.
- A `config-changes/v3.67.0.yaml` entry for
  `handlers.session_start.failsafe_cron_session_advisor`.
- Two `truth-changes/v3.67.0.yaml` entries under the `plan-workflow` topic.
- No post-upgrade task. New sessions pick up the new prompts on their own, and
  old crons keep matching their declarations.

## Verification

- Targeted QA: `format lint type_check pyright magic_values error_hiding docs_qa plan_qa`,
  8 of 8 passed.
- `check_declared_invariant_pairs.py` passes with 9 rows.
- pytest on every touched module and its existing tests (session_start,
  user_prompt_submit, stop, subagent_stop, recovery_cron_advisor,
  background_process_tracker, utils, skill_scan, config, constants, and the
  CLAUDE.md guidance coverage): 4261 passed.
- `tests/integration`, `tests/unit/daemon` and `tests/unit/core`: 8419 passed,
  9 skipped, 2 failed. Both failures are
  `test_repo_hygiene_check.py` (`plan-stats-arithmetic` in
  `CLAUDE/Plan/README.md`: 454 vs 455 distinct, 467 vs 468 allocated). They
  predate this branch. It never touches that file, and main's `d10bbf13`
  (Plan 00468 opened) last changed it. I left it alone because the brief forbids
  editing the plan README.
- Worktree daemon restarted and reports RUNNING, with no errors in the logs. The
  new handler is listed at priority 70.
