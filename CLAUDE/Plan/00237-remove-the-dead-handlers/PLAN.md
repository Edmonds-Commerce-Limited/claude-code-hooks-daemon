# Plan 00237: Remove The Dead Handlers

**Status**: In Progress
**Created**: 2026-08-13
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

[Plan 00234](../00234-handler-value-audit/PLAN.md) audited all 100 handlers and
returned 10 REMOVE and 2 MERGE verdicts.
[Plan 00236](../Completed/00236-fix-what-is-broken-pass/PLAN.md) took the
repair slice; this plan takes the deletions.

Removal has a client-facing cost that repair does not: a handler name that
vanishes from the daemon while still present in a client's
`.claude/hooks-daemon.yaml` is an unknown key, and handler-name validation is a
hard error by design. Plan 00233 built `RETIRED_HANDLERS` for exactly this — a
deliberate map of retired config key to the reason it went — so every removal
here must land its registry entry in the same commit, plus a `config-changes`
manifest entry so upgrading projects are told rather than left to discover it.

The verdicts split into two very different risk classes, and the phases follow
that split rather than the audit's cohort order. Five handlers **cannot fire or
have no consumer** — deleting them changes no observable behaviour, and the
audit's evidence for each is a structural fact (`matches()` returns a hardcoded
False; the directory has no producer). Five **do fire** and removing them
changes what reaches the agent's context, so each needs its duty accounted for
before it goes. The two MERGE verdicts are last because one carries a live side
effect that must be relocated first.

## Goals

- Delete the 10 REMOVE handlers, each with a `RETIRED_HANDLERS` entry and a
  `config-changes` manifest row landed in the same commit
- Fold the 2 MERGE handlers into `plan_qa`, relocating `validate_plan_number`'s
  counter-advance side effect before its handler goes
- Resolve the shadowed Stop advisories Plan 00236 identified — remove or
  re-prioritise, but not leave registered-and-unreachable
- Delete what each removed handler took with it (dead readers, state files,
  cache modules) rather than leaving orphans behind
- Verify in a real client install, not only in self-install mode

## Non-Goals

- The cost-tuning FIX verdicts (status-line TTLs, `git_context_injector`
  payload) — deferred to a later pass with real verdict-log data behind it
- Re-auditing the KEEP verdicts
- Removing any handler whose duty is real but whose implementation is poor —
  that is a repair, and repairs were Plan 00236's job

## Tasks

### Phase 1: The five that cannot fire or have no consumer

Deleting these changes no observable behaviour. Each verdict rests on a
structural fact, re-verified here before deletion rather than taken on trust.

- [x] ✅ **Task 1.1**: `usage_tracking` (Status) — `matches()` has returned a
  hardcoded False since commit 71593163; config claims `enabled: true`, which
  is a lie about runtime state. Takes `stats_cache_reader.py` with it
- [x] ✅ **Task 1.2**: `cleanup` (SessionEnd) — reaps `temp/hooks/`, which
  nothing in the codebase writes and which does not exist on disk. The
  Plan 00233 shape exactly
- [x] ✅ **Task 1.3**: `yolo_container_detection` (SessionStart) —
  `show_on_session_start` defaults False independently of `enabled: true`, so
  it is silent in every install
- [x] ✅ **Task 1.4**: `subagent_completion_logger` — writer with zero readers
  repo-wide; superseded in intent by the verdict log. 3.4 MB live
- [x] ✅ **Task 1.5**: `notification_logger` — same class, same corroboration
- [x] ✅ **Task 1.6**: Checkpoint commit with registry + manifest entries
- [x] ✅ **Task 1.7**: DBF — guard the registry/manifest seam. Two checks in
  `tests/integration/test_config_migrations_integration.py`: every handler a
  manifest documents as `removed` must carry a `RETIRED_HANDLERS` entry, and
  every staged manifest must match the `v*.yaml` glob the release step moves.
  Both found real pre-existing bugs on first run — see Decision 2 and 3

### Phase 2: The five that DO fire

Each of these reaches the agent's context today, so the question is not "does
it run" but "does its duty survive elsewhere". Record that answer per handler.

**Correction to that framing, established by live probe**: two of the five do
NOT fire on an ordinary stop. A Stop dispatched through the live daemon with a
valid `STOPPING BECAUSE:` transcript returns `{}` — no advisory context at all
— because `auto_continue_stop` (priority 10, `terminal=True`) matched and broke
the chain. So `task_completion_checker` (20) and the Stop leg of
`remind_prompt_library` (100) are shadowed exactly as Plan 00236's guard
describes, and belong to Phase 1's "cannot fire" class rather than this one.
They remain reachable only in `auto_continue_stop`'s two narrow non-matching
cases (confirmed re-entry, AskUserQuestion turn), and `remind_prompt_library`
also runs on SubagentStop, where no terminal handler precedes it.

- [ ] ⬜ **Task 2.1**: `task_tdd_advisor` — its ~30-line payload is already
  resident via CLAUDE.md's eager `@`-imports; `get_claude_md()` is None
- [ ] ⬜ **Task 2.2**: `remind_prompt_library` — points at an npm script and a
  `CLAUDE/PromptLibrary/` directory that do not exist, with no existence
  gating (both verified absent; `matches()` is `return True`). Removing it
  empties SubagentStop, so that section becomes `subagent_stop: {}` on the
  same footing as `session_end` and `notification`
- [ ] ⬜ **Task 2.3**: `task_completion_checker` — static checklist whose
  substance `auto_continue_stop` *enforces* rather than reminds
- [ ] ⬜ **Task 2.4**: `post_clear_auto_execute` — its originating plan is
  Cancelled as unachievable and rates the surviving code marginal, and its
  once-per-session contract is implemented with a single `_last_session_id`
  slot, which cannot hold per-session state in a daemon that parallel sessions
  deliberately SHARE. Note `scripts/qa/check_handler_reference.py` cites it
  twice as its worked example of a shipped handler with no `HandlerID` entry —
  repoint those comments, do not leave a dangling example
- [ ] ⬜ **Task 2.5**: `bash_error_detector` — decide REMOVE vs narrow +
  rate-limit, and record the decision. It is the most active behavioural
  handler in the log and fires on any common-word hit in output the agent can
  already see
- [ ] ⬜ **Task 2.6**: Checkpoint commit

### Phase 3: The shadowed Stop advisories

- [ ] ⬜ **Task 3.1**: Decide `hedging_language_detector` /
  `dismissive_language_detector` — remove the Stop registration (the nitpick
  pseudo-event already delivers both) or move them below priority 10
- [ ] ⬜ **Task 3.2**: Update the Plan 00236 shadowing guard to match whatever
  the reachable set becomes — the guard exists to fail when this changes, so
  it must be updated deliberately, never silenced

### Phase 4: The two MERGE verdicts

- [ ] ⬜ **Task 4.1**: Relocate `validate_plan_number._record_allocation` —
  the counter-advance side effect must move BEFORE the handler goes, or plan
  numbering breaks
- [ ] ⬜ **Task 4.2**: Fold `validate_plan_number` into `plan_qa`
  (`counter-sanity` / `no-new-collisions` are the real check; it never denies)
- [ ] ⬜ **Task 4.3**: Fold `plan_completion_advisor` into `plan_qa`
  (`terminal-placement-hint` + `terminal-state-atomic` already co-fire on the
  same tool call with a more complete check)

### Phase 5: Verification

- [ ] ⬜ **Task 5.1**: Config template, `.claude/hooks-daemon.yaml`, and
  generated docs regenerated
- [ ] ⬜ **Task 5.2**: Full QA — `./scripts/qa/llm_qa.py all`
- [ ] ⬜ **Task 5.3**: Daemon restart verified RUNNING
- [ ] ⬜ **Task 5.4**: Client-mode verification — a real client install with a
  config naming every retired handler must start WITHOUT degraded mode
- [ ] ⬜ **Task 5.5**: Commit and push

## Technical Decisions

### Decision 1: an event with no handlers keeps its config section

**Context**: removing `cleanup` emptied SessionEnd, and removing
`notification_logger` emptied Notification. A dogfooding guard
(`test_config_has_all_event_types`) then failed.

**Options**: drop the event from the expected set, or keep an empty section.

**Decision**: keep `session_end: {}` / `notification: {}`. Both events are
still registered and dispatchable — probed live, each returns `{}` on a valid
payload — they simply ship no handlers. Dropping them from the expected set
would weaken an invariant to make a symptom go away, and would leave a
project-level handler for those events with no documented place to live.

### Decision 2: six handlers retired before the registry existed were still rejected

**Context**: the new manifest/registry guard failed on first run, naming
`eslint_disable`, `python_qa_suppression_blocker`, `php_qa_suppression_blocker`,
`go_qa_suppression_blocker` (v2.9.0) and `validate_sitemap`, `remind_validator`
(v2.11.0).

Verified rather than assumed: a config naming any of the six was still
REJECTED by `ConfigValidator.validate_and_raise` today. `RETIRED_HANDLERS`
arrived in Plan 00233, so every handler removed before it had its documented
removal on one side and nothing on the other — an unedited v2.x config has been
tipping client daemons into DEGRADED MODE for every release since, over a
removal we performed deliberately.

**Decision**: add all six to the registry. This is not scope creep from the
plan's remit — the registry IS this plan's mechanism, and the bug is the exact
failure mode the plan exists to prevent, found by the guard rather than by
hand.

### Decision 3: a staged manifest not matching `v*.yaml` is silently stranded

**Context**: `UNRELEASED/config-changes/` held `transcript-archiver-removal.yaml`.
`RELEASING.md` Step 6 moves `UNRELEASED/config-changes/v*.yaml`, so that file
would never have been moved — Plan 00233's entire client-facing removal note
was set to sit in staging forever, with no error at any point.

**Decision**: merge its content into `v3.53.0.yaml` (alongside this plan's five
removals), delete the mis-named file, and add a guard asserting every staged
`*.yaml` also matches `v*.yaml`. The filename is the contract; nothing else
enforced it.

## Dependencies

- Depends on: [Plan 00234](../00234-handler-value-audit/PLAN.md) (the verdicts)
- Depends on: Plan 00233 (Complete) for `RETIRED_HANDLERS`
- Related: [Plan 00236](../Completed/00236-fix-what-is-broken-pass/PLAN.md),
  whose Decision 1 identified the shadowed Stop advisories in Phase 3

## Success Criteria

- [ ] Every removed handler has a `RETIRED_HANDLERS` entry and a
  `config-changes` manifest row
- [ ] A client config naming every retired handler starts cleanly, verified in
  a real client install rather than inferred from self-install mode
- [ ] Nothing removed leaves an orphan behind — dead readers, state files and
  cache modules go with their handler
- [ ] Each Phase 2 removal records where its duty survives, or that it had none
- [ ] Full QA passes; daemon restarts RUNNING

## Delivery & Milestones

- <!-- milestone or delivery commit hash -->
