# Plan 00420: dangerous command rule modes and config migration

**Status**: Not Started
**Created**: 2026-09-16
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Fifteen blocking rules about dangerous commands are spread across five handlers
(`destructive_git`, `curl_pipe_shell`, `sudo_pip`, `pip_break_system_packages`,
`chmod_world_writable`), and every one of them is all-or-nothing. A project that
wants `git commit --amend` allowed has to switch off the handler that also
denies `git reset --hard`. `scripts/qa/dangerous-invocation-corpus.yaml` records
nine further dangerous invocations the chain allows today, and each row explains
itself with the same sentence: a rule that gets switched off protects nothing.
The granularity is the blocker, not the patterns.

This plan consolidates the dangerous-command surface under one handler with
per-concern groups (git, filesystem, network, package managers, credentials) and
a per-RULE-ID mode of `block` / `warn` / `off`, with an `all` shorthand at group
level. `warn` introduces no new `Decision`: it is ALLOW plus an advisory, the
shape `documentation.qa.check_modes` already uses. That unlocks the nine
`UNCOVERED-open` corpus rows, because a rule can ship as a warning and ratchet
to block per project instead of being refused entry for being too noisy.

Consolidation changes the config shape, deliberately. Handler ids being a public
contract is a reason to make the transition loud, not a reason to freeze the
shape. The defect to avoid is already written down in this codebase:
`constants/handlers.py:1290` records that a retired handler key is "accepted
silently at startup", and that a client who keeps the old key "still has a
config that says the detector is on, while nothing runs it". A config that lies
about what is protecting you is worse than one that refuses to start. So the
second half of this plan is the upgrade machinery — fail fast, fail loud, name
the remedy, and migrate automatically wherever the migration is unambiguous.

## Goals

- One dangerous-command handler, with rules grouped by concern.
- Per-rule-ID `block` / `warn` / `off`, and `all` at group level. Rule IDs are
  unchanged: they are the key the whole design rests on.
- Each of the nine `UNCOVERED-open` corpus rows becomes implementable at the
  mode its measured noise earns, rather than at the only mode available.
- A removed, renamed or relocated config key FAILS daemon start, with a message
  naming the old key, the new key, and the command that migrates it.
- `hooks-daemon config-migrate` applies the declared changes in
  `CLAUDE/UPGRADES/config-changes/v*.yaml` across a version range, making those
  manifests executable rather than prose.
- The invalid-config window during an upgrade is closed by construction; where
  it cannot be, it is time-boxed, loud, uncommittable and self-healing.

## Non-Goals

- No new `Decision` member. `warn` is ALLOW plus an advisory.
- No rule ID is renamed. That remains this project's breaking change of last
  resort, and this design depends on their stability.
- Not a general per-rule mode system for every handler in the daemon — only the
  dangerous-command surface. Generalising later is cheaper than reversing it.
- No silent acceptance of an unknown key anywhere. Typos stay hard errors.
- No change to what the existing fifteen rules MATCH. Mode plumbing only; new
  patterns arrive in Phase 4 behind their own tests.

## Key design decisions

### Decision A — the registry of retired keys becomes an instruction sheet

`RETIRED_HANDLERS` and `RELOCATED_HANDLERS` are worth keeping, but their purpose
inverts. Today a key in either is accepted silently, so the project is told
nothing. After this plan, presence in the registry is what makes a LOUD failure
ACTIONABLE: the daemon refuses to start and prints the old key, the new key, and
the exact migration. A key absent from the registry stays a hard unknown-key
error, as now. Silence is removed as an outcome; the registry is what turns the
refusal into an instruction.

### Decision B — `warn` is ALLOW plus an advisory

Adding a `WARN` decision would touch every response formatter and every
event-specific block mechanism in `core/hook_result.py`. The existing precedent
(`DocumentationQaConfig.check_modes`) resolves a per-check mode against a
surface mode and degrades to an advisory. Follow it exactly, including the
subordination rule: a per-rule `block` cannot exceed the group's mode.

### Decision C — the upgrade window is bound to a fact, not to a flag

Two orderings exist and both are broken alone: migrate config first and the
running daemon reads a shape it does not know; upgrade code first and the daemon
fails fast on a config it no longer accepts. The window exists only because
those are two separate acts, so the primary fix is to make them one —
`hooks-daemon upgrade` owns fetch, config migration, install and a single
restart, and no process ever observes the mismatch. A self-install checkout gets
the same property free, because the migration lands in the same commit as the
code.

The window survives only on out-of-band paths: a hand-edited config, a `git pull`
carrying someone else's config, an upgrade that died halfway. For those an
`upgrade:` block is warranted — but a plain boolean is the wrong shape, because
the failure mode of a permissive flag is that nobody turns it off, and a
permanently-permissive guard is this project's own class 2 defect
(`guard-self-disablement-unwatched`). Four properties make it unable to persist:

1. **Bound to a target.** `upgrade: {to_version: "X.Y.Z"}`. The window is
   honoured only while the running daemon's version differs from `to_version`.
   The moment the upgrade succeeds the flag is spent by its own terms, and the
   daemon resumes failing fast while reporting the key as stale.
2. **TTL backstop.** `started_at` plus a bounded window, for the abandoned
   upgrade where the version never reaches the target and property 1 would
   otherwise hold the window open indefinitely.
3. **Uncommittable.** A commit gate denies staging a config carrying a live
   upgrade flag, so the permissive state cannot reach history, a teammate, or a
   fresh clone.
4. **Loud while live.** A status-line segment and a SessionStart report every
   session, naming what is being tolerated and the command that clears it, plus
   a log line per tolerated key so "the upgrade finished" is a claim with
   evidence behind it.

## Tasks

### Phase 1: Defence Before Fix — the Detectors

- [ ] ⬜ **Task 1.1**: Silent-key-acceptance Detector. A QA check that reads the
  config-validation path and fails when any key in `RETIRED_HANDLERS` or
  `RELOCATED_HANDLERS` resolves to an accept that surfaces no message.
  Expected to fire RED on the current tree; commit the red proof first.
- [ ] ⬜ **Task 1.2**: Window-persistence Detector. Asserts the upgrade flag
  carries all of a target-version bound, a TTL, and a commit-gate refusal. A
  flag missing any one of the three can become permanent.
- [ ] ⬜ **Task 1.3**: Mode-coverage Detector. Every rule ID declared by the
  dangerous handler must appear in the group map, and every group entry must
  name a declared rule ID. A rule reachable by no mode key cannot be turned
  off; a mode key naming no rule is config that does nothing.

### Phase 2: Loud, actionable config failure

- [ ] ⬜ **Task 2.1**: Invert retired/relocated key handling — refuse to start,
  naming old key, new key and the migration command. Remove silent accept.
- [ ] ⬜ **Task 2.2**: Extend the `config-changes/v*.yaml` schema so a `renamed`
  or `removed` entry carries a machine-applicable migration, not only prose.
- [ ] ⬜ **Task 2.3**: `hooks-daemon config-migrate` with a version range and a
  dry-run mode; applies those declarations and reports every key it moved,
  so the manifests become executable.
- [ ] ⬜ **Task 2.4**: Backfill the existing manifests with machine-applicable
  migrations for the keys already retired or relocated.

### Phase 3: The upgrade window

- [ ] ⬜ **Task 3.1**: `upgrade:` config block (`to_version`, `started_at`), with
  resolution bound to the running version per Decision C property 1.
- [ ] ⬜ **Task 3.2**: TTL backstop and the stale-flag report.
- [ ] ⬜ **Task 3.3**: Commit gate refusing a staged config with a live flag.
- [ ] ⬜ **Task 3.4**: Status-line segment and SessionStart report while live,
  plus the per-tolerated-key log line.
- [ ] ⬜ **Task 3.5**: Make the upgrade path own the whole transaction (fetch,
  migrate, install, one restart) so the window is unnecessary on the
  supported route.

### Phase 4: Consolidation and modes

- [ ] ⬜ **Task 4.1**: New dangerous-command handler with concern groups; the
  existing fifteen rules move across unchanged in what they MATCH.
- [ ] ⬜ **Task 4.2**: Mode resolution (`block`/`warn`/`off`, `all` shorthand),
  following the `check_modes` subordination precedent.
- [ ] ⬜ **Task 4.3**: Retire the five old handler keys through the Phase 2
  machinery — this plan's own migration is the dogfood of it.
- [ ] ⬜ **Task 4.4**: Corpus verdict vocabulary. A rule shipping at `warn` is
  not `COVERED`; decide and implement the fourth verdict before any row
  flips, or the corpus will report a warned command as guarded.
- [ ] ⬜ **Task 4.5**: Implement the nine `UNCOVERED-open` rows, each at the mode
  its noise measurement earns, each with a discriminating control test.

## Success Criteria

- [ ] Every Detector in Phase 1 was committed RED before its fix landed.
- [ ] No config key in any registry resolves to a silent accept.
- [ ] A config carrying a live upgrade flag cannot be committed.
- [ ] An upgrade flag left behind stops being honoured without anyone acting.
- [ ] Every rule ID is reachable by exactly one mode key, and every mode key
  names a declared rule ID.
- [ ] `./scripts/qa/llm_qa.py all` passes.
- [ ] The corpus distinguishes blocked from warned, and no row's verdict is
  stale against the real chain.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00420-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
