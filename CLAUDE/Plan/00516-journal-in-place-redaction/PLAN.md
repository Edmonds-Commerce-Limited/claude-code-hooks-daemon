# Plan 00516: journal in place redaction

**Status**: Not Started
**Created**: 2026-10-13
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #108

## Overview

> **Re-scope needed (Plan 00543, merged `c127d7356`).** Journals are now one file per entry under
> `JOURNAL/YYYY-MM-DD/`, and the guard denies ANY change to an existing journal file (legacy day-file or entry file)
> except removing conflict-marker lines or an exact restore to HEAD; `journal-dayfile-is-today` now closes every
> existing journal file at EDIT and flags a rewritten entry file at COMMIT. The blockers listed below describe the
> pre-00543 rules. A redaction tool must now address an entry FILE (or a legacy day-file entry) and be an explicit,
> audited exception to the immutability rule. Re-verify each point below before building.

The owner filed #108 after ledger 00474 N389: two committed journal lines (in archived Plan 00413's 26-09-15
day-file) held the development host's real name, and no agent could replace it with a placeholder.

What blocks it today (verified on main):

- `journal-dayfile-is-today` (plan QA, `today_only_mode`, Plan 00197) denies an Edit/Write to any day-file not dated
  today. This repository leaves it at the `block` default with `legacy_plan_allowlist: []`. The config comment beside
  it records that the Plan 00201 redaction pass hit exactly this (a real session UUID in an old entry), flipped the
  mode to `advise` for four edits and back, and named the fix if it recurred: a first-class escape hatch, not a
  standing relaxation.
- `plan_journal_guard` (R-JOURNAL-HAND-WRITTEN-ENTRY, Plan 00461) denies a Write/Edit that adds a line or heading, and
  any Bash write into a day-file. A same-line Edit passes this guard, but not the check above.
- `journal-append-only` only advises, and `mkplan.bash --journal <plan> correction <body> --ref [YY-MM-DD/]HH:MM`
  appends a stamped correction naming an earlier entry. That fixes a wrong fact but cannot remove a leaked value.
- `CLAUDE/PlanJournalling.md` says never to edit earlier entries, and also that the guard allows "redacting within a
  line"; no procedure reconciles the two.

An Edit call cannot carry a `MUST_..._BECAUSE` declaration, so the escape hatch belongs in the stamping tool, which is
already the one sanctioned writer of day-files. #108 proposes `mkplan.bash --journal-correct <plan> <day-file> --line N --from <text> --to <text> --reason <text>`, a general replacement addressed by line; this plan narrows it to
`--journal-redact`, addressed by entry (`YY-MM-DD/HH:MM`) and limited to redaction (owner question 1).

## Goals

- `mkplan.bash --journal-redact <plan> <YY-MM-DD/HH:MM> --from <text> --to <placeholder> --reason <text>` replaces
  `<text>` in the body of the one named entry, in any day-file, and appends a stamped `correction` entry to today's
  day-file (with `--ref` set to that entry) recording the reason and the placeholder, never the removed text.
- Bounded: body only, never a `## HH:MM · category · REF` heading; at most a set length per call; refuses when `<text>`
  does not occur in that entry.
- Every other write to a past day-file stays denied by `journal-dayfile-is-today` and `plan_journal_guard`.
- `PlanJournalling.md` (and its install template) describes the redaction route and resolves the "never edit" /
  "redacting within a line" tension.

## Non-Goals

- Rewriting git history: the value stays in earlier commits; purging it is a human's action.
- Relaxing `today_only_mode` or `plan_journal_guard`.
- Rewording past entries for any reason other than redaction; a wrong fact gets an appended `correction`.

## Open questions for the owner

1. **Scope:** redaction only, or a general `--from`/`--to` replacement for any wording, as #108 proposes?
   Recommended: redaction only. A wrong fact is fixed by an append-only `correction`, which keeps the original
   visible; rewording would make the journal's past say something it never said.
2. **Size limit:** recommended one run of up to 200 characters per call.
3. **N389:** redact its two lines with the new mode once it lands, and add the name to the secret word list (a
   human-only edit) so it cannot recur?

## Tasks

### Phase 1: Owner decision

- [ ] ⬜ **Task 1.1**: Owner answers the questions above.

### Phase 2: Build (TDD)

- [ ] ⬜ **Task 2.1**: `mkplan.bash --journal-redact`: argument checks, entry lookup (the existing `--ref` check only
  confirms an entry exists, so entry-body extraction is new), body-only replacement, the appended `correction` entry,
  refusals (no such entry, text not found, heading touched, over the limit).
- [ ] ⬜ **Task 2.2**: Tests that `journal-dayfile-is-today` and `plan_journal_guard` still deny a hand edit of the same
  line, and that the tool's own run is not denied, including when `--from` or `--reason` text contains `JOURNAL` or
  `-Journal-` (the guard's Bash prefilter and fail-closed path).
- [ ] ⬜ **Task 2.3**: Docs in `CLAUDE/PlanJournalling.md` and `src/claude_code_hooks_daemon/install/templates/PlanJournalling.md`;
  update the `today_only_mode` config comment to point at the new mode; release note in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.
- [ ] ⬜ **Task 2.4**: Redact N389's two lines with it (per question 3).

## Success Criteria

- [ ] An agent can replace a leaked value in a past journal entry with a placeholder, and today's day-file then
  carries an appended `correction` entry naming the entry, the reason and the placeholder.
- [ ] A hand edit of a past day-file is still denied.
- [ ] The new `mkplan.bash` mode is recorded in the UNRELEASED release notes.

## Delivery & Milestones

- Plan filed from #108 (ledger 00474 N389). Related: Plan 00163 (journalling), Plan 00197 (today-only), Plan 00461
  (stamping-tool guard).
