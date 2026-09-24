# Plan 00461: journal entries only through the stamping tool

**Status**: Complete
**Created**: 2026-09-24
**Owner**: dev
**Priority**: Critical
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration (worktree, TDD)

## Overview

**Owner directive: "journal entries by hand are NOW FORBIDDEN".**
`mkplan.bash --journal <plan> <category> <body-file>` shipped in v3.66.0. It
stamps the real UTC time, so a guessed timestamp cannot get in through it.
Even so, in one session the coordinator and five sub-agents appended EVERY
journal entry by hand: Edit plus a manual `date -u`, following the
coordinator's own briefs, and once a Bash heredoc. The heredoc entry was
stamped `09:50` at `09:11`, and because the journal is append-only it
could only be corrected once the clock passed the wrong time (00422 N3
recurrence). This project ships the tool, and its own agents went around
it. That is a dogfooding failure (00422 N21).

Three causes. First, nothing enforces the tool: an `Edit`/`Write`/heredoc
append to a `JOURNAL/` day-file is allowed. Second, nothing even mentions
it at that moment. `PlanJournalling.md` says "prefer", but only a reader
already in that document sees it. Third, `mkplan.bash --help` does not
mention `--journal` at all, so an agent that checks the usage cannot find
it.

**Enforced, not advised.** An advisory is what already existed, in effect,
and it did not work. The guard DENIES, and names the exact command for the
plan in question.

## Goals

- An `Edit`/`Write` that adds a journal ENTRY (a `## HH:MM · category`
  heading) to a plan `JOURNAL/` day-file is denied. So is a `Write` that
  creates a day-file. The deny names `mkplan.bash --journal` with that
  plan's number, and the body-file pattern.
- A Bash command that writes INTO a `JOURNAL/` day-file (redirect, `tee`,
  heredoc, `cp`/`mv` onto it, or an interpreter one-liner) is denied the
  same way. Invoking `mkplan.bash --journal` is never blocked, and neither
  is a `git mv` of a plan folder.
- `mkplan.bash --help` documents `--journal`.
- It applies to every session and sub-agent, and to client projects where
  the plan workflow and the scaffolder are deployed (the same condition as
  `plan_number_helper`).

## Non-Goals

- Changing the entry grammar or the `--journal` interface.
- Rewriting existing hand-written entries. They are history, and they
  stay as they are.

## Tasks

### Phase 1: TDD in a worktree

- [x] ✅ **Task 1.1**: RED tests reproducing today's allowed paths: an
  Edit appending an entry, a Write creating a day-file, a
  `cat >> JOURNAL/… <<'EOF'`, `tee -a`, `printf … >>`, and a
  `python3 -c` writing to a journal.
- [x] ✅ **Task 1.2**: The guard. It covers the Edit/Write surface and the
  Bash write-target surface, reusing the project's existing Bash
  write-target detection rather than a new parser. Decide and test the
  narrow allowances: a deletion-only Edit (for example removing git
  conflict markers after a merge of two appends) is judged by the existing
  append-only rule and not by this guard; `mkplan.bash --journal`; and
  `git` commands. Acceptance probes: DENY for a hand append, ALLOW for
  `mkplan.bash --journal`.
- [x] ✅ **Task 1.3**: `mkplan.bash` usage documents `--journal`, in both
  the deployed copy and its template. Update the journalling docs,
  handler guidance and the plan-workflow core docs clients receive, so
  that `--journal` is THE way and not merely the preferred one. Release
  note: a client-facing behaviour change.
- [x] ✅ **Task 1.4**: Full QA green. Every journal entry this plan writes
  goes through `--journal`.
- [x] ✅ **Task 1.5**: Fix every finding of the pre-merge review
  ([report](subagent-reports/260924-plan461-review-opus-5-5.md)): worktree
  day-files guarded, with the remedy printed as that checkout's absolute
  command; any added line denied; a Bash destination the shell builds at
  run time fails closed when it names a day-file; a fresh body-file name
  per deny; every journal remediation names `--journal`; and the ten
  minors. Targeted QA only (Plan 00463); the full gate is the
  coordinator's.

### Phase 2: Deliver

- [x] ✅ **Task 2.1**: Merge `--no-ff`, verify ancestry and CI, and restart
  the daemon. Then confirm live that a hand append is denied in the main
  checkout.
- [x] ✅ **Task 2.2**: Mark 00422 N21 remedied.

## Success Criteria

- [x] Every hand-append path listed in Task 1.1 is denied with the exact
  `--journal` command.
- [x] `mkplan.bash --journal` still works end to end from the Bash tool.
- [x] Full QA passes and CI is green.
- [x] Every release-bound consequence is in the pending-release holding
  area: `UNRELEASED/release-notes/11-hand-written-journal-entries-are-now-denied.md`.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00461-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Delivered in integration batch A: merged `--no-ff` as `e3f03f3e`, full QA
  37/37 on the combined head `2c38ff05`, main fast-forwarded to `a8204ad0`,
  CI green at `ce31d6d8`. Live deny confirmed in the main checkout for an
  Edit and a Bash heredoc append. 00422 N21 remedied.
