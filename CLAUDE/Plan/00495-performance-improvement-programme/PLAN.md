# Plan 00495: performance improvement programme

**Status**: In Progress (all three phases delivered; awaiting archive)
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

- [x] ✅ **Task 1.1**: Cross-version startup profile, in isolated throwaway projects (never the live daemon). Report:
  [261006-startup-profile-sonnet.md](subagent-reports/261006-startup-profile-sonnet.md). The host was loaded throughout
  (load average 24 to 40), so versions are compared on CPU seconds, 5 runs each:

  | Version      | Daemon start CPU |
  | ------------ | ---------------- |
  | v3.30, v3.40 | about 1.0 s      |
  | v3.58        | about 1.5 s      |
  | v3.65        | about 2.0 s      |
  | v3.68, main  | about 2.5 s      |

  Top costs on main (cProfile, inflated about 2x):

  - the YAML config parsed about 4 times with the pure-Python loader (2.3 s);
  - handler registry discovery run 4 times (1.7 s);
  - imports and pydantic model builds (1.6 s);
  - the CLAUDE.md markdown formatting on every start (about 0.4 s).

- [x] ✅ **Task 1.2**: The status line waits on daemon START, not on SessionStart. `ensure_daemon` polls up to 15 s
  for the socket, so a cold start under load shows "DAEMON FAILED / still starting" or arrives late. Once the daemon is
  warm the status line takes 0.3 s idle, and 0.75 to 1.06 s while a SessionStart chain runs.

  This repository's own SessionStart chain needs about 8 CPU-s: `docs-qa-sweep` 4.1 and `plan-qa-sweep` 1.75. The docs
  corpus reuses per-file records when mtime and size are unchanged, but the checks themselves rerun on every start,
  with no result cache. Measured chain runs of 21.1 s and 20.1 s overran the dispatch budget (reported as 20 s
  in this session's SessionStart notice) and dropped the late handlers. A client with the shipped
  example config runs the chain in about 1.6 s wall.

  Not measured: network fetches (no external network in the sandbox).

- [x] ✅ **Task 1.3**: Bisect. No single culprit: start-up CPU grew steadily, with the largest steps at v3.50 to v3.58,
  v3.62 to v3.65 and v3.65 to v3.68. The shipped example config grew from 15 KB to 58 KB over the same span. The
  report names where to bisect further, if a fix needs it.

- [x] ✅ **Task 1.4**: Refresh `CLAUDE/Performance/BASELINE.md` with the new figures, including the dispatch figure it
  marks "not re-measured". Also correct `CLAUDE/Performance/README.md:72`, which still lists the Rust transport
  forwarder as "Never, until…" although `relay/hooks_relay.rs` exists (found by the plan's fact check). Done in
  COMMIT_HASH: BASELINE.md has a "Plan 00495 re-measurement" section (start 2.55 s -> 1.03 s CPU on the Phase 1 method;
  dispatch 7.4 to 10.2 ms; a new finding in the content scanners), and the README row now reads "Landed, opt-in".

### Phase 2: Fix (TDD, one branch per fix)

- [x] ✅ **Task 2.1**: Rank the fix candidates by measured saving. The clear winners, each its own branch:
- [x] ✅ **Task 2.2**: Parse the YAML config once per start, with the C loader (`CSafeLoader`) where available. Done
  in d356d41bc: 4 parses became 1 (the controller's validation and both asset syncs reuse the loaded config). Daemon
  start CPU on this repository's config, 6 interleaved runs, median: 1.88 s -> 1.21 s.
- [x] ✅ **Task 2.3**: Run handler registry discovery once per start. Done in c67fdb33a: walks of the handlers package
  per start 2 -> 1 (after Task 2.2). Start CPU, 10 interleaved runs, median, 1.31 s -> 1.33 s, no measurable change: a repeated scan costs 6 ms
  against 0.58 s for the first, so the Phase 1 figure of about 0.4 s was the first call's imports, not repeats.
- [x] ✅ **Task 2.4**: Skip the CLAUDE.md markdown formatting when the generated block is unchanged. About 0.4 s CPU
  saved. Done (9456b40fe): `inject()` CPU on a copy of this repository's 114 KB CLAUDE.md, steady state, median of 5,
  before -> after: 0.19-0.21 s -> 0.006 s (three interleaved rounds; host loaded).
- [x] ✅ **Task 2.5**: Bind the socket before the non-essential start-up work, so the first request is answered sooner.
  Done in be944c475: the CLAUDE.md regeneration, both asset syncs and the index pre-warm run in a worker thread behind
  the bound socket; handler registration and config validation stay before it. Real forked start in a throwaway
  project, 8 interleaved runs, median: first request answered 1.94 s -> 1.51 s, `start` returned 2.12 s -> 1.68 s. A test
  sends a destructive git command while the deferred work is blocked and gets the same deny as afterwards.
- [x] ✅ **Task 2.6**: Add a result cache to `docs-qa-sweep` and `plan-qa-sweep`, keyed by an input fingerprint, and run them off the
  blocking chain. About 6 CPU-s saved on this repository, and no handler dropped for the budget. Done in 78a7fa47d
  (report: [261015-p495-sweep-cache-implementer.md](subagent-reports/261015-p495-sweep-cache-implementer.md)).
  Same chain-timing method as Task 1.2, idle host, this repository, before -> after: docs sweep 3.3 to 8.0 s wall ->
  0.09 to 0.14 s on a hit; plan sweep 1.2 to 1.6 s -> 0.10 to 0.13 s on a hit; SessionStart chain 5.8 to 12.7 s -> 1.9 to
  2.2 s on a hit and 5.0 s on a miss (each sweep waits at most 1 s, then finishes in the background).
- [x] ✅ **Task 2.7**: Status line: while the daemon is starting, show a baseline line saying the hooks daemon is
  loading (owner ruling A3, 2026-10-06), with any cached fallback text, instead of "DAEMON FAILED". Done: the status
  line forwarder asks for a non-blocking start (`_HOOKS_DAEMON_NONBLOCKING_START`, 1 s deadline) and prints
  "⏳ hooks daemon loading…" with exit 0 while the daemon is starting; a daemon whose pid is alive but whose socket is
  not yet answering also shows it; a launcher that finished with no daemon alive still prints "DAEMON FAILED". No
  cache was built. Time to first status-line output, daemon stopped, throwaway project with its own daemon, before ->
  after: real cold start 3.65 s and 5.32 s -> 0.46 s and 0.21 s; slowed 7 s init 11.34 s and 10.60 s -> 0.10 s and
  0.92 s.

### Phase 3: Guard and decide

- [x] ✅ **Task 3.1**: A startup-time regression check (a benchmark with a budget, run where it is cheap enough: a
  release gate or a scheduled routine), so the next slowdown is caught by the project, not the owner. Done in
  COMMIT_HASH: `scripts/release/check_startup_budget.py`, a blocking release step (RELEASING.md Step 8b) with the budget
  in `CLAUDE/Performance/startup-budget.json` (2 s CPU, median of 5, a failing round is measured again). A release step
  and not the per-commit suite because a sample costs about a CPU-second; CPU seconds and a retry round so host load does
  not flake it. Proof: a clean run printed PASS at 1.39 s, and with 1.5 s of CPU planted in the start path (a
  `sitecustomize.py`) it printed FAIL at 2.92 s and exited 1; the planted-slowdown test (`tests/integration/ test_startup_budget_planted_slowdown.py`) does the same on every run of the slow tests.
- [x] ✅ **Task 3.2**: Rust helpers for specific hot paths (owner ruling A3, 2026-10-06: no full rewrite was
  proposed; the question is whether particular heavy paths justify a Rust helper). From the Phase 1 and Phase 2
  numbers, name each path that stays heavy after the Python fixes (candidates to measure: the content scanners on large
  writes, the docs and plan QA sweeps, the transport path). For each, give the measured saving a native helper would
  bring and its auditability cost, and put the list to the owner. Delivered in COMMIT_HASH:
  [RUST-HELPERS-ASSESSMENT.md](RUST-HELPERS-ASSESSMENT.md) names six paths. None passes the cost test; the one path over
  the budget (the secret-file guard, 1.2 s per 115 KB Write) is a Python algorithm problem. The owner's decision is put
  to them in [Plan 00529](../00529-owner-decision-on-rust-helpers-from-00495-assessment/PLAN.md).

## Success Criteria

- [x] Session start shows the status bar within a budget set from the Phase 1 data. The budget (1 s to first output, 2 s
  CPU for the start before the bind) is recorded in `CLAUDE/Performance/README.md`, section "Start-up budget". Measured
  0.46 s and 0.21 s cold (Task 2.7), against up to 15 s and "DAEMON FAILED" in Phase 1.
- [x] No SessionStart handler is dropped for running past the dispatch budget on a normal host. The chain on this
  repository, the case that overran, is 1.9 to 2.2 s on a sweep-cache hit and 5.0 s on a miss against the 20 s budget
  (Task 2.6, [report](subagent-reports/261015-p495-sweep-cache-implementer.md)); a client with the example config was 1.6 s
  in Phase 1.
- [x] Every delivered fix has before and after numbers in this plan (Tasks 2.2 to 2.7 above; Task 2.3 measured no change
  and says so).
- [x] A regression check exists and fails on a planted slowdown (Task 3.1: the demonstrated FAIL run and the
  planted-slowdown test).
- [x] The release-bound consequences are recorded in the pending-release holding area: release notes 067 to 070 in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/` cover Phase 2 (067 sweeps, 068 config parsed once, 069 registry discovery,
  070 socket bound first). Tasks 1.4, 3.1 and 3.2 change documentation and a release-procedure script that no client
  install receives, so they have no release note.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00495-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan filed from the owner's report; Phase 1 measurement dispatched.
