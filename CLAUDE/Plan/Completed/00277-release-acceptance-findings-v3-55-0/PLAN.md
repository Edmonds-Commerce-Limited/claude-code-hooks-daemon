# Plan 00277: release acceptance findings v3 55 0

**Status**: Complete
**Created**: 2026-08-26
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

The v3.55.0 release gates surfaced findings that were deliberately NOT fixed
mid-release because none affects shipped handler behaviour: stale acceptance
test expectations, a documented-vs-implemented semantics mismatch in
`lsp_enforcement`, and one inconclusive acceptance test. Per RELEASING.md
("never drop a finding"), each is tracked here as a MUST-FIX to close
immediately after the release ships.

## Goals

- Every v3.55.0 acceptance/review finding below fixed or explicitly ruled on.

## Non-Goals

- No behaviour changes to handlers beyond what the rulings require.

## Tasks

### Phase 1: Stale acceptance expectations (test metadata only)

- [x] ✅ **Task 1.1**: `daemon_location_guard` playbook Test 19 expected
  `CORRECT USAGE`, which lives on the guidance channel, not in the deny
  reason a tester observes. Fixed in-release: expectation now matches the
  reason text.
- [x] ✅ **Task 1.2**: `recovery_cron_advisor` playbook Test 158 expected
  `[Rr]ecreat`; shipped advisory says "create one now". Fixed in-release.
- [x] ✅ **Task 1.2b**: `root_recursion_guard` playbook Test 64 expected a
  literal `workspace`; the deny text scopes via `$CLAUDE_PROJECT_DIR`.
  Fixed in-release.
- [x] ✅ **Task 1.2c**: `git_hooks_executable_fixer` playbook Test 139 was
  unpassable in a healthy repo (hint echoed, nothing to fix, silent by
  design). Converted in-release to an explicit negative control; the
  positive fixing path stays unit-tested. FOLLOW-UP below (Task 3.3) for a
  live positive-path test.
- [x] ✅ **Task 1.3**: `error_hiding_blocker` allow-case samples made
  lint-clean (Python: real function with `logging.exception`; Go: real
  `os.Open` err check) so `lint_on_edit` no longer denies the write the
  tested handler allowed.

### Phase 2: lsp_enforcement block_once semantics

- [x] ✅ **Task 2.1**: RULED per-session is intended (matches docs), and
  fixed: `HandlerDecisionRecord` gained `session_id`, the controller
  attributes every record, `count_blocks_by_handler` takes an optional
  session filter (unattributed records excluded from filtered counts), and
  `lsp_enforcement` passes the event's session id. The confusing live
  observations were consistent once daemon restarts (in-memory history
  wipes) were accounted for: the old behaviour was
  block-once-per-daemon-lifetime shared across sessions.

### Phase 3: Inconclusive acceptance observations

- [x] ✅ **Task 3.1**: ROOT-CAUSED: the thread registry counts
  statusline-emitting INTERACTIVE sessions; spawned sub-agents never
  register, so a single-terminal acceptance run always observes silence
  (verified: registry held exactly one entry — this session — while many
  sub-agents ran). Not a rate-limit and not a defect. Acceptance test
  rewritten with the two-interactive-sessions precondition and marked
  main-thread.
- [x] ✅ **Task 3.2**: NOT A DEFECT: reproduced live — the hint DID fire on
  `true; agent-browser --version` (second segment of a compound command)
  with fresh TTL state. Batch-3's silence was per-hint TTL rate limiting
  consumed by their earlier standalone run.
- [x] ✅ **Task 3.3**: RULED: accept unit-test-only coverage for the fixing
  path. The event cwd is captured at invocation and always names the
  session repo, so no probe command can fire the fixer against a fixture;
  the shipped acceptance test is an explicit negative control (silence in
  a healthy repo) and says so.
- [x] ✅ **Task 3.4**: `validate_eslint_on_write` deny branch VERIFIED
  live in the dummy-client fixture: with the handler enabled, `llm:lint`
  in `package.json` BEFORE daemon start, and `broken.ts` physically on
  disk, a synthesized Bash-authored PostToolUse write returned
  `decision: block` ("Failed to run ESLint: ... 'tsx'") — the documented
  DENY-on-failure-to-run branch. The earlier `{}` was environmental, not
  a defect: (a) the fixture ships the handler `enabled: false`, and
  (b) `has_llm_commands` is snapshotted at handler init, so adding
  `llm:lint` after startup cannot arm enforcement without a restart;
  additionally `matches()` requires the target file to exist on disk, so
  a synthesized event with no real file never matches.
- [x] ✅ **Task 3.5**: RULED a recorded boundary, not fixed: inside a
  quoted-string ARGUMENT (`[[ "... | tail -5" == 0 ]]`) the scanner cannot
  know which embedded word is the "producer" without executing the string,
  so it attributes the enclosing command; the DENY is correct, only the
  remediation template is non-runnable for this shape. `$( )` substitution
  shapes attribute correctly. Revisit only if a real workflow hits it.
- [x] ✅ **Task 3.6**: RULED: the livelock lives in Claude Code's own
  session-scoped `/goal` Stop hook, which the daemon cannot modify; the
  daemon's own Stop surfaces already honour `STOPPING BECAUSE:` (and the
  Plan 00276 ledger challenge is advisory text inside that same denial).
  Operational remedy documented: a goal whose remainder becomes human-gated
  should be cleared early (`/goal clear`) — the assistant should say so
  explicitly when it happens. A daemon-side "waiting on human" goal-ledger
  state remains a candidate enhancement for Plan 00276's next phase.

## Success Criteria

- [x] All rulings recorded (here or in the affected handlers' docs)
- [x] Regenerated playbook expectations pass against the live daemon
- [x] Full QA green; daemon restart RUNNING

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00277-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed during the v3.55.0 release acceptance gate
- Main delivery (per-session block_once, test precondition, lint-clean samples) at ebf7016a
- Task 3.4 deny-branch verification closed the plan (commit hash: the archiving commit)
