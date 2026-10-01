# Plan 00478: unknown guard verdicts warn

**Status**: Not Started
**Created**: 2026-10-01
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

On 2026-09-29 the coordinator asked the owner "whether guards deny unknown
commands". The owner answered, verbatim: "2 - sounds very risky, warn dont
block". So a guard that cannot tell what a command does must ALLOW it, with an
advisory naming the cause. A positively recognised dangerous action still
denies.

Nothing implements that ruling yet. Until now it was recorded only in session
summaries, so this plan makes it durable. Today several guards turn "could not
decide" into a deny. Examples are R-SECRET-EVALUATION-ERROR,
R-SECRET-COMMAND-UNREADABLE, the scan-deadline deny (ledger 00474 N281), and the
enumeration cap (N256). Each of these blocks ordinary work whenever the reader
meets text it cannot place.

A starting point exists: `untracked/briefs/n253-unattributed-warn-dont-block.diff`.
These are 253 lines a sub-agent wrote, unasked, into the wrong worktree (ledger
00474 N264). Reuse them only as reference, never wholesale.

## Goals

- Every UNKNOWN verdict in the safety guards becomes an allow with an advisory.
  The advisory names the guard, the cause, and how to rephrase.
- A positively recognised mention, path or action still denies.
- Every converted route is logged, so a field report can show how often the
  guards fell back to warning.

## Non-Goals

- Changing what counts as a positive match.
- Guards whose only verdicts are match or no-match.

## Known consequence (the owner's ruling accepts it)

A command written to defeat the reader can force an UNKNOWN verdict, for example
by exceeding the scan deadline or the enumeration cap. Under this ruling it then
runs, with only a warning. The advisory and the log line are what remain. This
plan states that cost; it does not re-decide the ruling.

## Tasks

### Phase 1: Inventory

- [ ] ⬜ **Task 1.1**: List every route where a safety guard denies because it
  could not decide, as opposed to a positive match. Cover the evaluation-error
  rules, unreadable commands, deadlines and caps. Give a `file:line` and a test
  for each.

### Phase 2: Convert

- [ ] ⬜ **Task 2.1**: Convert `secret_file_guard`'s UNKNOWN routes to warn
  (TDD). This includes the enumeration cap deferred from N256.
- [ ] ⬜ **Task 2.2**: Convert the other guards' UNKNOWN routes from Task 1.1
  (TDD).
- [ ] ⬜ **Task 2.3**: Update the rule explanations, the generated `CLAUDE.md`
  guidance, and add a release note.

## Success Criteria

- [ ] No safety guard denies solely because it could not decide.
- [ ] Every positive-match deny in the existing suites is still a deny.
- [ ] A converted route emits an advisory and a log line, and a test pins both.

## Delivery & Milestones

- Ruling recorded here; implementation starts when the WIP limit allows.
