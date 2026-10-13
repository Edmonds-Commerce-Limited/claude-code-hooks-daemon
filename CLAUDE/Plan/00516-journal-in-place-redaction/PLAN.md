# Plan 00516: journal in place redaction

**Status**: Not Started
**Created**: 2026-10-13
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #108

## Overview

Plan journals are append-only. `plan_journal_guard` (R-JOURNAL-HAND-WRITTEN-ENTRY, Plan 00461) denies any hand-written
Edit, Write or Bash write into a `JOURNAL/` day-file, so every entry goes through `mkplan.bash --journal`, which
stamps the real UTC time. The owner filed #108 after ledger 00474 N389: two committed journal lines held a real host
name, and no agent could replace it with a placeholder.

A factual error already has a controlled path: `mkplan.bash --journal <plan> correction <body> --ref [YY-MM-DD/]HH:MM`
appends a `correction` entry to today's day-file that names the entry it corrects, and refuses a `--ref` that names
no existing entry. What has no path is changing the old line itself. A correction entry leaves a leaked value where
it is, so a value that must not stay in the tracked tree needs an in-place replacement. This plan builds that, and
only that: a bounded, audited redaction of named text in an existing entry.

Coordinator reading of the issue: #108 proposes a general `--from`/`--to` replacement. Since factual fixes are
already covered by the append-only correction, this plan narrows it to redaction. Whether to keep the narrow scope is
owner question 1.

## Goals

- `mkplan.bash --journal-redact <plan> <YY-MM-DD/HH:MM> --from <text> --to <placeholder> --reason <text>` replaces
  `<text>` within the body of the one named entry, and appends a stamped `correction` entry (with `--ref` set to that
  entry) recording the reason and the placeholder, never the removed text.
- Bounded: the replacement touches only the named entry's body; never a `## HH:MM · category · REF` heading; at most
  a configured length of text; it refuses when `<text>` does not occur in that entry.
- `plan_journal_guard` keeps denying every other write into a day-file. The new path is the tool's own write, exactly
  as `--journal` is.

## Non-Goals

- Rewriting git history. The removed text stays in earlier commits; purging it is a history rewrite, which is a
  human's action.
- Deleting or reordering entries, or editing headings and stamps.
- Changing `plan_journal_guard`'s rule for hand edits.

## Open questions for the owner

1. **Scope:** redaction only (this plan's reading), or a general `--from`/`--to` replacement for any wording, as the
   issue proposes? Recommended: redaction only. A wrong fact is fixed by an append-only `correction`, which keeps the
   original visible; an in-place rewrite of wording would make the journal's past say something it never said.
2. **Size limit:** how much text one redaction may replace. Recommended: one run of up to 200 characters per call.
3. **Who may run it:** any agent, or the main thread only? Recommended: any agent; the appended correction entry is
   the audit trail.
4. **`sensitive_content` suggestion:** when the commit-time scan finds a term in an existing journal line, should its
   deny reason name `--journal-redact` as the fix? Recommended: yes, naming the command shape but never the term.

## Tasks

### Phase 1: Design confirmation

- [ ] ⬜ **Task 1.1**: Owner answers the questions above.

### Phase 2: Build (TDD)

- [ ] ⬜ **Task 2.1**: `mkplan.bash --journal-redact`: argument checks, entry lookup reusing the `--ref` resolver,
  body-only replacement, the appended `correction` entry, refusals (no such entry, text not found, heading touched,
  over the limit).
- [ ] ⬜ **Task 2.2**: Confirm `plan_journal_guard` still denies a hand edit of the same line, and does not deny the
  tool's own write.
- [ ] ⬜ **Task 2.3**: Per question 4, the `sensitive_content` remediation text.
- [ ] ⬜ **Task 2.4**: Docs in `CLAUDE/PlanJournalling.md`, and a release note in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Success Criteria

- [ ] An agent can replace a leaked value in a past journal entry with a placeholder, and the day-file then carries
  an appended `correction` entry naming the entry, the reason and the placeholder.
- [ ] A hand edit of any day-file is still denied.
- [ ] The release-bound consequence (a new `mkplan.bash` mode) is recorded in the UNRELEASED release notes.

## Delivery & Milestones

- Plan filed from #108 (ledger 00474 N389). Related: Plan 00163 (journalling), Plan 00461 (stamping-tool guard).
