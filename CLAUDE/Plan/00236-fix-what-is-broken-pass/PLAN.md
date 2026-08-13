# Plan 00236: Fix What Is Broken Pass

**Status**: In Progress
**Created**: 2026-08-13
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

[Plan 00234](../00234-handler-value-audit/PLAN.md) audited all 100 handlers and
returned KEEP 76 · FIX 12 · REMOVE 10 · MERGE 2. This plan executes the first
slice of the FIX column — the findings where a mechanism is **broken** rather
than merely expensive — plus two supporting fixes from the same audit.

The removals and the cost-tuning findings are deliberately NOT in scope. A
removal is a different kind of decision from a repair, and the cost findings
should be argued against real firing data, which only starts existing once
Phase 1 below has been logging for a while.

One finding did not survive verification. Plan 00234 reported the nitpick
`dismissive_language`/`hedging_language` handlers as structurally double-firing
with their Stop-event twins, and prescribed dropping the `stop:1/1` trigger. A
live chain trace shows the opposite: `auto_continue_stop` is terminal at
priority 10 and matches nearly every Stop, so the Stop twins never run and the
nitpick leg is the ONLY one that fires. The prescribed fix would have deleted
the working copy and kept the dead one. See
[DECISIONS.md](DECISIONS.md) Decision 1.

## Goals

- Make the wall-TTL half of `harvest-background` capable of firing at all
- Stop `lsp_enforcement` false-positiving on multi-line commands
- Give `suggest_statusline` a way to take "no" for an answer
- Narrow `release_blocker` so an ordinary docs edit cannot trap the session
- Exclude Status renders from the verdict log so it records decisions, not noise
- Repoint the always-resident docs at `llm_qa.py all`, which agents may run
- Leave a GUARD behind each fix, not just the fix (CLAUDE.md principle 15, DBF)

## Non-Goals

- The 10 REMOVE verdicts — a separate pass, with its own retired-handler work
- Cost tuning (`git_branch` TTL, `account_display` caching,
  `supervisor_indicator` negative cache, `git_context_injector` payload) —
  needs real firing data first
- Re-litigating Plan 00234's verdicts wholesale; only findings contradicted by
  direct evidence are revised, and each revision records that evidence

## Tasks

### Phase 1: Verdict log records decisions, not noise

- [x] ✅ **Task 1.1**: Exclude Status events from `verdicts.jsonl`
  - [x] ✅ `record_status_events` flag on `build_verdict_lines` / `append_verdicts`
  - [x] ✅ `VerdictLogConfig.record_status_events` so a project can opt back in
  - [x] ✅ Controller passes the configured value through
- [x] ✅ **Task 1.2**: Stop the exclusion creating a NEW false signal
  - [x] ✅ `_behavioural_handler_names` omits Status handlers from the roster,
    so 14 renderers do not become false "never-fired" entries
  - [x] ✅ `_WINDOW_CAVEAT` states the exclusion AND the anti-inference rule:
    "never fired" is not evidence a handler is pointless

### Phase 2: Docs point at the command agents may actually run

- [x] ✅ **Task 2.1**: Repoint 16 `run_all.sh` instructions at
  `./scripts/qa/llm_qa.py all` across the six always-resident docs; leave the
  one reference that is genuinely ABOUT the script as source-of-truth
- [x] ✅ **Task 2.2**: Replace the stale "6 automated checks" count with the
  runner-is-the-source-of-truth phrasing that cannot drift

### Phase 3: release_blocker stops trapping ordinary work

- [x] ✅ **Task 3.1**: Narrow `RELEASE_FILES` to files a release cannot avoid
  touching — drop `README.md` and `CLAUDE.md`
  - [x] ✅ Pin that a version file ACCOMPANYING a README edit still fires, so
    narrowing costs no coverage
- [x] ✅ **Task 3.2**: Fix the block message — drop the drifted "89 EXECUTABLE"
  count, point at `generate-playbook`, cite the archived plan path
  - [x] ✅ Test asserts the cited path exists, so a future archive move fails
    the test rather than misleading the reader

### Phase 4: The four broken mechanisms

- [x] ✅ **Task 4.1**: `background_process_tracker` wall-TTL can fire
  - [x] ✅ Correlate by recorded COMMAND text, not by a `pgid` the daemon can
    never learn (verified against a live `ps` snapshot)
  - [x] ✅ Blank-command guard — `"" in args` would track every process
  - [x] ✅ GUARD: `tests/integration/test_background_tracker_harvester_roundtrip.py`
    runs the real writer against the real reader
- [x] ✅ **Task 4.2**: `lsp_enforcement` multi-line false positive
  - [x] ✅ `\n` added to the segment terminators
  - [x] ✅ Exemption now describes the WHOLE command: every grep must be
    single-file, so one narrow grep cannot buy cover for a recursive one
- [x] ✅ **Task 4.3**: nitpick `stop:1/1` — verified, finding revised, NOT changed
  - [x] ✅ GUARD: `tests/integration/test_stop_chain_terminal_shadowing.py`
    pins which Stop handlers actually run, and proves itself by showing the
    advisories DO fire once the terminal handler is removed
- [x] ✅ **Task 4.4**: `suggest_statusline` takes "no" for an answer
  - [x] ✅ Persisted showing counter, capped at `_MAX_SUGGESTIONS`
  - [x] ✅ Fails OPEN on a corrupt counter — a permanently silent handler is
    indistinguishable from a working one

### Phase 5: Verification

- [ ] 🔄 **Task 5.1**: Full QA — `./scripts/qa/llm_qa.py all`
- [ ] ⬜ **Task 5.2**: Daemon restart verified RUNNING
- [ ] ⬜ **Task 5.3**: Commit and push

## Dependencies

- Depends on: [Plan 00234](../00234-handler-value-audit/PLAN.md) (Complete)
- Related: Plan 00235 (shared heredoc scanner), which fixed the dogfooding bug
  found while running the audit

## Technical Decisions

Recorded in [DECISIONS.md](DECISIONS.md): the nitpick reversal, the
correlation-key choice for the harvester, and why `stop:1/1` stays.

## Success Criteria

- [ ] Every fix above has a test that FAILED before it
- [ ] Two seam guards exist where previously both sides were tested in isolation
- [ ] Full QA passes with zero failures
- [ ] Daemon restarts and reports RUNNING
- [ ] No Plan 00234 finding is silently dropped: each is fixed, deferred with a
  stated reason, or revised with the evidence that contradicted it

## Delivery & Milestones

- Phases 1-4 delivered at <commit-hash>
