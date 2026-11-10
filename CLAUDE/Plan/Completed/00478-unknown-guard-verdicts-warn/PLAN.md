# Plan 00478: unknown guard verdicts warn

**Status**: Complete (2026-11-10)
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
- [x] ✅ **Task 2.2a**: Commit gates (rows 6-13): conflict-marker timeout and
  unchecked commit, unreadable secret word list, failed staging simulation in
  `sensitive_content`, `staged_lint_gate`, `remote_docs_commit_gate`, and the
  block-mode `docs_qa`/`plan_qa` gates. Introduce ONE shared "unknown verdict"
  helper (advisory naming guard, cause and how to rephrase, plus a log line)
  that the later batches reuse (TDD; handler tests for rows 11-13, which have none).
  Delivered: `utils/unknown_verdict.py` `unknown_verdict_allow(guard, cause, rephrase)`,
  log prefix `UNKNOWN-VERDICT`; an independent review caught a found marker lost on
  a later timeout, fixed before merge (`a2a7f5687`; branch merged to main via
  `6014e3814`, main CI run 42747571106 green); release note 027.
- [x] ✅ **Task 2.2b**: `destructive_git` substitution route (row 2). The stand-in's
  Q1 ruling keeps the deny (a recognised forced delete with an unproven target), so
  this task only pins the local-delete substitution deny with a test (none found by
  name in INVENTORY.md row 2). Delivered with 2.2e (`afcda1796`).
- [x] ✅ **Task 2.2c**: rows 14, 15, 19, 20, 22, 24 (flaggable channel, journal
  guard, release merge freeze, reference repo not verified, curl into a
  non-shell interpreter, root recursion on an unstattable path).
  Delivered: an independent review found two critical regressions (a literal journal
  path allowed; a curl option value swallowed) and one important one (`git -C`
  treated as unplaceable), all fixed before merge (`0057dc4ad`, branch merged via
  `39da746f2`, main `4e3f77db6` CI run 42758232505 green on rerun after an unrelated
  Kotlin-linter timeout); release note 028.
- [x] ✅ **Task 2.2d**: ESLint timeout and run failure (rows 17, 18).
  Delivered: `validate_eslint_on_write` `_not_linted` allows with the shared advisory;
  R-ESLINT-TIMEOUT and R-ESLINT-RUN-FAILURE are advisory-only (`a215b3ae6`, branch
  merged via `2d9e6c762`, main `47dae7574` CI run 42756436040 green); release note 029.
- [x] ✅ **Task 2.2e**: Contested rows 1, 3, 5, 16, 23 and scope rows 21, 25, 26,
  under the stand-in's ruling (see "Owner questions"). Convert to warn: row 16's
  sub-branches that deny with no literal mention of a listed path (the `**`-only
  glob), and row 26 (an unknown producer piped to `tail`/`head`; blacklisted
  producers still deny). Rows 1, 3, 5, 16-literal and 23 stay deny; rows 21 and 25
  are out of scope. Delivered: three review rounds. Round 1 found an unknown pipe
  laundering a later blacklisted one, and wrapped blacklisted producers read as
  unknown. Round 2 found the same for parser gaps, so an unknown pipe now allows only
  when no blacklisted name appears anywhere in the command. Round 3 approved. Main
  `7995c3330`; shipped in v3.73.2 (release note 031).
- [x] ✅ **Task 2.2f**: The three minor findings from the third 2.2e review (report
  `untracked/agent-reports/auto/261110-114115-code-reviewer-ae1ac874080c044d0.md`,
  copied into `subagent-reports/` with 2.2e). First, `pipe_blocker` also scans heredoc
  bodies on the unknown-producer path (`cat > t.sh <<'EOF' … pytest … EOF; bash t.sh | tail`).
  Second, `py.test` is blacklisted. Third, an operator-form expansion operand
  (`${PWD:-.}/protected/x`) counts by its literal part in `write_protected_paths`, or
  release note 031 is narrowed to the forms it covers. Delivered: its review found a
  2.2e regression already shipped in v3.73.2 (an awk `FILENAME` rewrite of a named
  protected file allowed after an operator-form expansion operand). Fixed at the root:
  the shared word scanner reads a brace-balanced `${...}` as part of its word, which
  also closed an older gap for `rm`, `cp`, `tee` and other verbs. Main `99b1917c9`;
  main CI green on `2ef61af10` (run 42897828693); release note 037.
- [x] ✅ **Task 2.3**: Update the rule explanations, the generated `CLAUDE.md`
  guidance, and add a release note: rule texts, `get_claude_md` and
  `HANDLER_REFERENCE.md` per batch; release notes 027-029, 031 and 037.

## Owner questions (block Task 2.2e only)

The owner did not answer by the stand-in deadline. The STAND-IN's ruling (not the
owner's; the owner may overturn any line) is journalled in
`JOURNAL/2026-11-10/100942Z-decision-97aacd.md`: Q1 deny, Q2 deny, Q3 deny where
the path is literally named and warn where it is not, Q4 rows 21 and 25 out of
scope and row 26 in scope (warn).

- **Q1 (rows 1, 2, 3):** `destructive_git` denies a positively recognised
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

- [x] No safety guard denies solely because it could not decide. Rows 1-3, 5, 21, 23
  and 25 stay deny as positively recognised actions, under the stand-in's ruling.
- [x] Every positive-match deny in the existing suites is still a deny. The existing
  deny tests stayed green in every batch. The 2.2e and 2.2f reviews also compared
  verdicts before and after the change over broad probe sets. 2.2b is test-only.
- [x] A converted route emits an advisory and a log line, and a test pins both: the
  shared `unknown_verdict_allow` helper with an `UNKNOWN-VERDICT` log line.
- [x] Release-bound consequences in the holding area: release note 037 in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`. Notes 027-029 and 031 have already
  shipped, in `CLAUDE/UPGRADES/v3/v3.73.1-to-v3.73.2/release-notes/`.

## Delivery & Milestones

- Ruling recorded here; implementation starts when the WIP limit allows.
- Phase 0 (GitHub #170, closed): `484ab6791` + `0726efd70`, main CI run 42713973768 green.
