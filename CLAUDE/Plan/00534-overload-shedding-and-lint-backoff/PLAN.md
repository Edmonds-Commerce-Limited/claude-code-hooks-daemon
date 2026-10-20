# Plan 00534: overload shedding and lint backoff

**Status**: Not Started
**Created**: 2026-10-19
**Owner**: dev
**Priority**: Medium
**GitHub Issue**: #124 (follow-up)
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Follow-up to [Plan 00533](../Completed/00533-dispatch-saturation-recovery/PLAN.md) (issue
#124), from the owner's discussion of what the daemon should do when the host is
overloaded. The strategy, in order:

1. **Wait first.** A bounded wait for a dispatch slot rather than an instant
   refusal (Plan 00533 Task 1.2).
2. **Shed expensive non-safety work, never the guards.** The daemon already has
   two tiers: a SAFETY+BLOCKING handler fails closed when it cannot be judged,
   and every other handler is skipped (`core/chain.py`). Overload should use that
   existing split, and no new protection levels are added. A guard that switches
   itself off under load is protection nobody can rely on, and load peaks when
   the most agents are acting.
3. **Say so honestly.** When a safety chain still cannot be judged, the deny
   tells the agent the host is overloaded and to pause rather than retry. In
   #124 the agents re-issued refused calls at once, which added load.
4. **Recovery always gets through** (Plan 00533 Task 1.1).

This plan holds steps 2 and 3, and the watchdog item Plan 00533 split out. The
owner proposed the lint backoff: a linter that keeps timing out is skipped for a
few minutes.

Facts on current `main`:

- `lint_on_edit` starts a fresh linter subprocess on every write, so the linter
  always starts cold. Its timeout is per-language, defaulting to
  `Timeout.LINT_CHECK` = 15 s, and on timeout it allows the write with a warning.
  It has no backoff: a linter that times out on every edit is retried on every
  edit, at the full 15 s each time.
- `validate_eslint_on_write` uses `Timeout.ESLINT_CHECK` = 30 s, above the 20 s
  `CHAIN_DEADLINE_DEFAULT`. The chain budget therefore always cuts ESLint off
  first, leaving it running as a straggler, so its own timeout path can never
  fire under the default budget.

## Goals

- Linter backoff: after N consecutive timeouts of one linter (per language and
  workspace), skip that linter for a cool-down period. Each skip says so in an
  advisory naming the remaining cool-down; a success, or the cool-down ending,
  resets it. N and the cool-down are configurable.
- Every subprocess-linter timeout fits inside its event's chain budget, with
  the handler margin, so a linter times out cleanly instead of becoming a
  straggler.
- Under sustained saturation, non-SAFETY handlers holding expensive work
  (subprocess linters first) are shed before a chain is queued for a slot.
- A saturation deny of a SAFETY chain says "host overloaded: pause, do not
  retry at once".

## Non-Goals

- Protection levels among the safety guards: none is skipped under load.
- Warm linter pools. Each tool needs its own daemon (`eslint_d`, `dmypy`), which
  is a separate decision per tool. Measure the cold-start share first (Task 1.1).
- Stop/SubagentStop semantics under saturation (an owner decision, Plan 00533).

## Tasks

### Phase 1: Measure

- [ ] ⬜ **Task 1.1**: For each configured linter, measure how much of a lint
  run is cold start and how much is the check itself, on this host, idle and
  loaded. This decides whether a warm pool is worth a plan of its own.

### Phase 2: Lint backoff and budgets

- [ ] ⬜ **Task 2.1**: Red test, then a consecutive-timeout backoff in
  `lint_on_edit` and `validate_eslint_on_write`, configurable, with the skip
  advisory.
- [ ] ⬜ **Task 2.2**: Red test, then clamp each linter timeout below its
  event's chain budget minus the handler margin, including ESLint's 30 s.

### Phase 3: Shedding and the overload message

- [ ] ⬜ **Task 3.1**: Red test, then shed expensive non-SAFETY handlers under
  sustained saturation.
- [ ] ⬜ **Task 3.2**: Red test, then the "host overloaded: pause" deny text
  for a SAFETY chain refused for saturation.
- [ ] ⬜ **Task 3.3**: Decide the watchdog's action on sustained saturation,
  split out of Plan 00533, once 00533 and Phase 2 have landed.

## Success Criteria

- [ ] Each change has a test that failed before it.
- [ ] A release note for the backoff and its options is in the pending-release
  holding area `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.
- [ ] Targeted QA green on the merged head; CI green.

## Delivery & Milestones

- <!-- delivery commit hashes -->
