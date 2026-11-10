# Plan 00478: unknown guard verdicts warn

**Status**: In Progress
**Created**: 2026-10-01
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #170 (Phase 0)

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

### Phase 0: First slice, GitHub #170

- [x] ✅ **Task 0.1**: `destructive_git`'s unreadable-removal route denies a command whose only git text is DATA:
  `printf p | awk '{print "git worktree remove " $1}'` (reproduced on `main`; GitHub #170). The raw-text pattern
  matches, the parser reads no removal, and the fail-closed branch denies. Fix the misreading, not the policy:
  git text that provably stays data (a quoted argument of a program that does not execute it) is no removal, so
  the route never fires. Text that may be executed (`| sh`, `| bash`, `| xargs`, `eval "$(…)"`, `source <(…)`)
  keeps today's verdict until Phase 2 converts the route itself. RED tests in both directions, release note

### Phase 1: Inventory

- [x] ✅ **Task 1.1**: List every route where a safety guard denies because it
  could not decide, as opposed to a positive match. Cover the evaluation-error
  rules, unreadable commands, deadlines and caps. Give a `file:line` and a test
  for each. Delivered as [INVENTORY.md](INVENTORY.md): 25 UNKNOWN routes (rows
  1-3, 5-26; row 4 misnamed), already-converted guards, and every handler
  checked with no UNKNOWN route.

### Phase 2: Convert

- [x] ✅ **Task 2.1**: Convert `secret_file_guard`'s UNKNOWN routes to warn
  (TDD). This includes the enumeration cap deferred from N256. Found already
  converted (INVENTORY.md "Already converted": every cap, deadline and parse
  failure routes to `_literal_finding_or_advisory`, pinned by
  `test_secret_file_guard_advisory.py`); no work left.
- [ ] 🔄 **Task 2.2a**: Commit gates (rows 6-13): conflict-marker timeout and
  unchecked commit, unreadable secret word list, failed staging simulation in
  `sensitive_content`, `staged_lint_gate`, `remote_docs_commit_gate`, and the
  block-mode `docs_qa`/`plan_qa` gates. Introduce ONE shared "unknown verdict"
  helper (advisory naming guard, cause and how to rephrase, plus a log line)
  that the later batches reuse (TDD; handler tests for rows 11-13, which have none).
- [ ] ⬜ **Task 2.2b**: `destructive_git` substitution route (row 2).
- [ ] ⬜ **Task 2.2c**: rows 14, 15, 19, 20, 22, 24 (flaggable channel, journal
  guard, release merge freeze, reference repo not verified, curl into a
  non-shell interpreter, root recursion on an unstattable path).
- [ ] ⬜ **Task 2.2d**: ESLint timeout and run failure (rows 17, 18).
- [ ] ⬜ **Task 2.2e**: Contested rows, after the owner rules (see "Owner
  questions"): 1, 3, 5, 16, 23, and scope rows 21, 25, 26.
- [ ] ⬜ **Task 2.3**: Update the rule explanations, the generated `CLAUDE.md`
  guidance, and add a release note.

## Owner questions (block Task 2.2e only)

- **Q1 (rows 1, 3):** `destructive_git` denies a positively recognised
  `git branch -D` / `worktree remove` / `git push --delete` when it cannot PROVE
  nothing is lost (unknown flag, variable `cd`, failed containment or
  `ls-remote` proof). Is "cannot prove it is safe" an UNKNOWN (warn) or part of
  the recognised dangerous action (deny)?
- **Q2 (row 5):** evacuate-then-destroy where both steps are present but the
  link between them cannot be placed: warn or deny?
- **Q3 (rows 16, 23):** a protected path or the plan directory is literally
  named but the action on it is unknown: does "literally named" keep the deny,
  as it does in `secret_file_guard`?
- **Q4 (rows 21, 25, 26):** are the public-issue body check, the plan-sync
  config check and the pipe-to-tail unknown tier "safety guards" under this
  ruling at all?

## Success Criteria

- [ ] No safety guard denies solely because it could not decide.
- [ ] Every positive-match deny in the existing suites is still a deny.
- [ ] A converted route emits an advisory and a log line, and a test pins both.

## Delivery & Milestones

- Ruling recorded here; implementation starts when the WIP limit allows.
- Phase 0 (GitHub #170, closed): `484ab6791` + `0726efd70`, main CI run 42713973768 green.
