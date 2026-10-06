# Plan 00495: performance improvement programme

**Status**: In Progress
**Created**: 2026-10-06
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet (measurement and fixes), Opus (review of the ranked findings)
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Owner report (2026-10-06): the daemon's startup time "seems to have increased a LOT in recent release". The visible
symptom is the status bar taking a long time to appear when a Claude Code session starts. The owner asked for a profile
comparing current main with a few earlier versions, and asked whether parts of the system should be rewritten in Rust,
or optimised some other way. This plan is the single place that tracks all of that.

Prior work it builds on, all complete:

- **Plan 00154** (research): about 85 ms per tool call and a 1.26 s cold restart (`import` 141 ms) were measured. The
  full Rust rewrite was ruled out because it saves 4% end to end at most and costs auditability. The only Rust step
  judged worth having is a policy-free transport forwarder, which now exists as `relay/hooks_relay.rs` (Plan 00290).
- **Plans 00155 and 00156**: the tuning waves that followed (cache the per-Bash git fork, drop `jq`, slim `init.sh`).
- **`CLAUDE/Performance/BASELINE.md`**: the recorded baseline. Its daemon dispatch figure is marked "not re-measured".

Evidence already seen in this session (2026-10-06), not yet explained:

- **SessionStart chain**: it ran past its 20 s dispatch budget and dropped 16 handlers, among them
  `git-upstream-checker`, `plan-qa-sweep`, `docs-qa-sweep` and `reference-repo-sweep`.
- **After a restart**: hook calls were denied with "the daemon is starting" for some time, and one call hit the 30 s
  socket timeout.
- **Confounder**: both happened while another agent ran about 200 test files, so host load must be measured with every
  sample.

## Goals

- Measured startup-to-ready, SessionStart chain and first status-line times for current main and several earlier
  releases, with host load recorded per sample.
- The regression located, by commit or plan, if there is one.
- Each cost attributed to daemon process start, the SessionStart chain or the status line, and ranked by saving.
- The ranked fixes delivered, each with a before and after measurement.
- A regression guard, so a startup slowdown is caught before release rather than by the owner.
- The Rust question answered again, from the new numbers.

## Non-Goals

- A full Rust rewrite of the daemon or its handlers, unless the new numbers overturn Plan 00154's ruling. In that case,
  the owner decides.
- Removing or weakening any guard to save time. A check can move off the critical path; it cannot be dropped.

## Tasks

### Phase 1: Measure

- [ ] 🔄 **Task 1.1**: Cross-version startup profile, in isolated throwaway projects (never the live daemon). Cover
  current main, the latest release and releases about 3, 6 and 10 or more back; take 5 or more samples each, with host
  load recorded. Report: `untracked/scratch/startup-profile/REPORT.md`, to be copied into this plan's
  `subagent-reports/` when it lands.
- [ ] 🔄 **Task 1.2**: Per-handler wall time of the SessionStart chain, and what the status line waits on (daemon
  start, SessionStart, or neither). Part of the same dispatch.
- [ ] ⬜ **Task 1.3**: Bisect to the commit or plan responsible, if Task 1.1 shows a clear jump.
- [ ] ⬜ **Task 1.4**: Refresh `CLAUDE/Performance/BASELINE.md` with the new figures, including the dispatch figure it
  marks "not re-measured".

### Phase 2: Fix (TDD, one branch per fix)

- [ ] ⬜ **Task 2.1**: Rank the fix candidates from Phase 1 by measured saving and choose the clear winners. Candidates
  to test against the data:
  - **SessionStart**: move slow checks (network fetches, tree sweeps) off the blocking path, with results delivered on
    a later turn.
  - **Handler loading**: import a handler only when it is enabled.
  - **Config validation**: cache it, keyed by the config file's fingerprint.
  - **Status line**: render at once from cheap state, without waiting on a full start.
- [ ] ⬜ **Task 2.2 onwards**: one task per chosen fix, each with its before and after numbers.

### Phase 3: Guard and decide

- [ ] ⬜ **Task 3.1**: A startup-time regression check (a benchmark with a budget, run where it is cheap enough: a
  release gate or a scheduled routine), so the next slowdown is caught by the project, not the owner.
- [ ] ⬜ **Task 3.2**: Re-answer the Rust question from the Phase 1 and Phase 2 numbers. If any native step would pay,
  write it up for the owner with its saving and its auditability cost.

## Success Criteria

- [ ] Session start shows the status bar within a budget set from the Phase 1 data. The budget is recorded in
  `CLAUDE/Performance/README.md`.
- [ ] No SessionStart handler is dropped for running past the dispatch budget on a normal host.
- [ ] Every delivered fix has before and after numbers in this plan.
- [ ] A regression check exists and fails on a planted slowdown.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00495-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan filed from the owner's report; Phase 1 measurement dispatched.
