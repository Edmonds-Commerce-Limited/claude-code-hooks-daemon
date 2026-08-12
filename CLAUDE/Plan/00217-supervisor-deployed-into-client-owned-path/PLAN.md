# Plan 00217: supervisor deployed into client owned path

**Status**: Not Started
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A client-repo field report found three ruff findings in the deployed
`claude-supervise.py` and correctly concluded that **none of them is a bug** —
all three are deliberate, documented design choices. The real finding is
structural, and it is ours:

**The daemon deploys daemon-owned source into a client-owned directory.**
`claude-supervise.py` lands in `.claude/ccy/`, which a client legitimately owns
and lints (it also holds their `Dockerfile`, `ccy.env` and project handlers).
The vendor path clients exclude by convention is `.claude/hooks-daemon/`. So
every client repo lints ~3,100 lines of upstream code, and must independently
rediscover why and write its own exclusion.

The trap closes on three sides, which is what makes it worth fixing rather than
documenting:

1. **Not fixable by the client** — `ccy.deploy_supervisor: true` (the
   recommended setting; `false` makes the running supervisor go stale, which
   `ccy_supervisor_integrity` itself warns about) refreshes the file on every
   upgrade, discarding any local edit.
2. **Not silenceable by the client** — the daemon's own `qa_suppression`
   handler denies a Write/Edit introducing `# noqa`, so an agent cannot even
   add a stopgap; a human must do it by hand and then lose it to (1).
3. **Not covered by the conventional exclusion** — the pattern that would work
   is not the one anybody writes by default.

The net effect is a finding that is simultaneously not a real defect, not
fixable, and not silenceable — the exact shape that erodes trust in a QA gate.

## Context & Background

- `REPORT.md` — the field report as received, kept as a supporting document.

Reported against v3.51.0, ruff 0.16.2. The three findings: `BLE001` at line
2407 (a deliberate supervisory-boundary catch that preserves the traceback to a
file and substitutes a safe NOOP), and `DTZ005`/`DTZ006` at line 1907 (naive
local time, deliberate — the marker is read by a human scrolling their own
terminal history).

## Goals

- Make the ownership boundary match the directory layout, so daemon-owned code
  sits where clients already know not to touch it.
- Ensure a client repo running default `ruff check .` gets no findings from
  daemon-owned files.
- Fix it once upstream rather than having every client rediscover and re-encode
  the same exclusion.

## Non-Goals

- **Changing the supervisor's behaviour.** The report is explicit that all three
  findings are correct as written and asks for no code change. Narrowing the
  `BLE001` catch would defeat its stated purpose; making the timestamps
  timezone-aware would make a human-facing terminal marker worse.
- Disabling or weakening `qa_suppression`. Its stance is right; the problem is
  that daemon-owned code is inside the client's lint scope at all.

## Tasks

### Phase 1: Choose the fix

- [ ] ⬜ **Task 1.1**: Evaluate the report's options against this project's
  conventions. Its preference order is (a) carry `# noqa` upstream in the
  shipped source, (b) keep the real file under `.claude/hooks-daemon/` with a
  symlink or thin launcher shim at `.claude/ccy/`, (c) document the exact
  per-file ignore, (d) ship `.claude/ccy/claude-supervise*` in
  `qa_suppression`'s default `exclude_paths`
- [ ] ⬜ **Task 1.2**: Note the tension in option (a) before choosing it — this
  project bans agents from writing suppression annotations, so an agent
  implementing it would be blocked by the daemon's own handler. That is a signal
  worth weighing, not merely an obstacle to route around
- [ ] ⬜ **Task 1.3**: Record the decision with rationale under Technical
  Decisions

### Phase 2: Implement

- [ ] ⬜ **Task 2.1**: Implement the chosen fix with TDD
- [ ] ⬜ **Task 2.2**: Verify a default `ruff check` over a client-shaped fixture
  reports nothing from daemon-owned paths — the dummy-client-repo fixture exists
  for exactly this kind of check and is more representative than self-install
- [ ] ⬜ **Task 2.3**: Confirm the upgrade path preserves the fix (the v3.24.0
  class of bug: an asset install deploys and upgrade never refreshes)

### Phase 3: Close the documentation gap

- [ ] ⬜ **Task 3.1**: Whatever the fix, state the ownership boundary explicitly
  where a client will read it — a client should not have to infer which files
  under `.claude/` are theirs
- [ ] ⬜ **Task 3.2**: Stage a `truth-changes` entry if the fix changes where the
  supervisor lives, since client docs and exclusions may assert the old path

## Dependencies

- Related: Plan 00147 (ccy container workflow), which introduced
  `deploy_supervisor`.
- Related: Plan 00164, which added stale-running-supervisor detection and is why
  `deploy_supervisor: false` is not a viable client workaround.

## Success Criteria

- [ ] A default `ruff check .` in a client repo reports nothing from
  daemon-owned files
- [ ] The supervisor's behaviour is unchanged — no narrowed catch, no
  timezone-aware terminal markers
- [ ] The fix survives an upgrade
- [ ] A client can tell which files under `.claude/` are theirs without guessing

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00217-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Field report received and filed as a tracked plan
