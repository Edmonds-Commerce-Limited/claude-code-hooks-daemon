# Plan 00209: field feedback daemon self observability

**Status**: Not Started
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Acts on a field feedback report from a long working session in a *documentation*
repo (filed here as `FEEDBACK.md`). Read it first — it is unusually careful, it
re-rates two of its own findings after push-back rather than quietly dropping
them, and it states what worked as well as what did not.

The headline item is not a bug. **The daemon makes hundreds of decisions per
session and persists none of them.** Every interesting question about the
tool — which handlers earn their keep, what the real false-positive rate is per
handler, whether a handler is in the wrong mode, whether adding one changed
anything measurable — is currently unanswerable, and answerable cheaply.

The remaining items are one real presentation defect and two small precision
refinements.

## Goals

- Give the daemon a **verdict log**, so its own effectiveness stops being
  anecdote
- Fix `pipe_blocker`'s remediation output, which quotes prose back as a shell
  command
- Reduce two sources of advisory noise, since noise is how advisories get
  ignored wholesale — including the ones that matter

## Non-Goals

- No change to `pipe_blocker`'s **detection**. Erring toward caution is correct
  for a safety handler, and properly separating heredoc bodies from executable
  text needs real shell parsing. The block is not the defect; the output is.
- No weakening of the `error`/`warning` output advisory. The report initially
  called it a false positive and then withdrew that: an advisory has no
  false-positive failure mode in the sense a blocker does.

## Context & Background

Findings, in the report's own ordering by cost:

| #   | Item                                             | Rating                            |
| --- | ------------------------------------------------ | --------------------------------- |
| 1   | `pipe_blocker` echoes heredoc prose as a command | Real defect, cosmetic impact      |
| 2   | `error`/`warning` output advisory                | **Working as intended**           |
| 3   | No verdict log                                   | Missing capability, highest value |
| 4   | `recovery_cron_advisor` repetition               | Minor noise                       |
| 5   | Formatter causes a stale-string `Edit` failure   | Minor, already documented         |

**§1 in detail**: appending a journal entry via a heredoc whose prose *described*
two earlier pipe blocks tripped the handler — so the document describing the
guardrail could not be written past the guardrail. The block is defensible. What
is not: the matched "command" was run through the remediation template, which
extracted `the` as the binary name (first word of a sentence) and emitted
`extra_whitelist: - "^the\\b"`, then offered `set -o pipefail` and suggested
redirecting the author's own narrative to `$TEMP_FILE`. A correct safety
decision was presented in a way that reads as broken, and it burned a large
amount of context re-quoting text just written.

**§3 in detail**: what exists today is `notifications.jsonl` and
`subagent_completions.jsonl`. Neither records which handler fired, on which tool
call, with what verdict. Decisions are emitted to the agent and discarded.

**Confirmed independently in this repo's own session**: §1 and §2 were both hit
repeatedly while working on v3.52.0, which is corroboration from a second
codebase of a different kind (code, not docs).

## Tasks

### Phase 1: `pipe_blocker` remediation output (TDD) — §1

- [ ] ⬜ **Task 1.1**: Failing test — a heredoc body of prose produces a block
  reason with NO remediation template and NO echoed prose
- [ ] ⬜ **Task 1.2**: Sanity-check before templating: if the matched "command"
  has no recognisable binary as its first token, or exceeds a sane length, emit
  the reason alone
- [ ] ⬜ **Task 1.3**: Cap the echoed command at N characters regardless. The
  full text is rarely what makes a block actionable
- [ ] ⬜ **Task 1.4**: Audit every other handler that echoes matched input into
  a remediation template — this defect class is not unique to `pipe_blocker`
  (DBF: fix the shared output path, not the one instance)

### Phase 2: Verdict log — §3, the valuable half

- [ ] ⬜ **Task 2.1**: Design decision — where the write happens so EVERY
  handler decision is captured without each handler opting in (front controller,
  not per handler)
- [ ] ⬜ **Task 2.2**: Append-only `verdicts.jsonl`, one line per decision:
  `{ts, session, event, tool, handler, verdict, rule, mode}`
- [ ] ⬜ **Task 2.3**: Record an `overridden` marker when a `MUST_…_BECAUSE`
  escape hatch was used — an override is the strongest available signal that a
  rule is mis-tuned
- [ ] ⬜ **Task 2.4**: Retention. It must be bounded like the other JSONL logs,
  but note the Plan 00206 lesson: a cap that discards the oldest half silently
  corrupts any cumulative statistic derived from it. Decide explicitly whether
  this log is a rolling sample or a durable counter, and say which in the docs
- [ ] ⬜ **Task 2.5**: A `hooks-daemon verdicts` reporting command — per-handler
  fire counts, verdict mix, override rate, never-fired handlers
- [ ] ⬜ **Task 2.6**: Config gate + docs. Decide default-on vs default-off on
  privacy grounds: the log records tool names and rule names, not payloads

### Phase 3: Advisory noise — §2, §4, §5

- [ ] ⬜ **Task 3.1**: §2 (optional, offered as such) — skip the output-keyword
  advisory when the trigger keyword also appears in the COMMAND string, e.g. a
  `grep` pattern or a repo name. Those fires cannot carry signal
- [ ] ⬜ **Task 3.2**: §4 — rate-limit `recovery_cron_advisor`'s creation and
  completion phases the way the progress phase already is, and/or suppress for
  the rest of a session after N ignored fires
- [ ] ⬜ **Task 3.3**: §5 — have `markdown_table_formatter`'s advisory NAME the
  transformations it applied (list renumbering, pipe alignment) so an `Edit`
  retry after a stale-string failure is targeted rather than a blind re-read

## Dependencies

- Related: Plan 00206 — its retention finding (a capped log cannot back a
  cumulative counter) directly constrains Task 2.4

## Technical Decisions

### Decision 1: The verdict log is the priority, not the bug fixes

**Context**: §1 is a real defect but cosmetic. §3 is not a bug at all.

**Decision**: §3 first. Without it, every judgement about this daemon — including
which of §1/§2/§4 actually matter — rests on anecdote, which is precisely what
the daemon exists to replace elsewhere. It also makes the tuning questions the
other findings raise answerable with a query rather than a discussion.

**Date**: 2026-08-12

## Success Criteria

- [ ] A heredoc of prose produces a short, accurate block reason and no
  fabricated shell scaffolding
- [ ] `verdicts.jsonl` records every handler decision across a real session
- [ ] `hooks-daemon verdicts` answers "which handlers have never fired" and
  "what is the override rate per handler" over that data
- [ ] The retention decision for `verdicts.jsonl` is explicit and documented,
  and does not silently corrupt cumulative statistics
- [ ] Full QA passes; daemon restarts RUNNING

## Risks & Mitigations

| Risk                                                  | Impact | Probability | Mitigation                                                                                     |
| ----------------------------------------------------- | ------ | ----------- | ---------------------------------------------------------------------------------------------- |
| Verdict log becomes a per-event write hot path        | Medium | Medium      | Written once in the front controller, append-only, no read-modify-write; measure dispatch cost |
| The log records something privacy-sensitive           | High   | Low         | Record handler/rule/verdict metadata only — never tool payloads or file contents               |
| Capped retention silently corrupts derived statistics | Medium | Medium      | Task 2.4 makes the choice explicit; Plan 00206 hit exactly this with a 5 MB cap                |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00209-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Not started. Field report filed as `FEEDBACK.md` in this folder.
