# Plan 00220: stale exclusion audit in qa suppression files

**Status**: Complete
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

`scripts/qa/error_hiding_exclusions.json` grants standing exemptions from the
error-hiding audit. It was only ever consulted to REMOVE findings, so nothing
asked whether each entry still earned its place. Two kinds of rot followed, and
both were invisible:

1. **Drift.** A `lines`-keyed entry moves out of alignment whenever anything
   above it is edited. It then exempts an innocent line while the real finding
   resurfaces somewhere else — presenting as a brand-new violation with no hint
   that a suppression caused it. Observed twice in one session in
   `upgrade_version.sh` after an unrelated edit shifted the file by 21 lines.
2. **Spent licences.** When the underlying code is fixed or removed, the entry
   survives as a standing permission to hide errors in that location, ready to
   silently cover a future re-introduction.

The obvious remedy — "re-key everything by function" — is not available. Every
remaining `lines` entry is a shell script or a module-level import, where there
is no enclosing function to key on. So the guard belongs on the EXCLUSION, not
on the keying style, which also catches the function-keyed case (a rename
orphans an entry just as surely as an edit orphans a line number).

This is DBF (Core Standard 15): the mis-targeted entries are the symptom, the
unaudited suppression file is the bug. It is the unused-`noqa` pattern (ruff's
RUF100) applied to our own suppression file.

## Goals

- Report any exclusion that suppresses no finding, as a QA violation.
- Cover both keying styles, since both rot.
- Make the message distinguish the two causes — their remedies are opposite.

## Non-Goals

- Abolishing line-keyed exclusions. Not possible for module-level and shell
  sites, and the guard makes their fragility visible rather than fatal.
- Auditing other suppression files. Worth doing, but prove the pattern here
  first.

## Tasks

### Phase 1: Guard

- [x] ✅ **Task 1.1**: TDD `find_stale_exclusions()` — drifted line entry,
  matching entry, renamed function entry, and message content
- [x] ✅ **Task 1.2**: Extract `_exclusion_matches()` as the single definition
  of the matching rule, called by BOTH `apply_exclusions()` and the new audit,
  so "what an exclusion suppresses" and "what counts as suppressing nothing"
  cannot drift into two different answers
- [x] ✅ **Task 1.3**: Wire into `main()` against the UNFILTERED violation set,
  so findings are reported rather than only available to tests
- [x] ✅ **Task 1.4**: Positive control — run the check against the real
  127-entry file, since synthetic dicts alone would pass against an
  implementation that only worked on hand-built input

### Phase 2: Act on what it found

- [x] ✅ **Task 2.1**: Six stale entries surfaced on the first run. Each
  triaged individually rather than deleted en masse: five named functions no
  longer exist at all (removed in a refactor), and `_read_effort_level` still
  exists but its try/except moved out into `read_claude_settings()`
- [x] ✅ **Task 2.2**: Remove all six, and verify the violation count is
  unchanged at zero — which it must be, since by definition they suppressed
  nothing, making the deletion provably incapable of unmasking anything
- [x] ✅ **Task 2.3**: Update the file's own `description` so the contract is
  stated where the entries live

### Phase 3: Verify

- [x] ✅ **Task 3.1**: Full QA green, daemon restart RUNNING

## Technical Decisions

### Decision 1: Guard the exclusion, not the keying style

**Context**: The obvious reading of the drift incident is "line-keyed
exclusions are bad, migrate them".

**Options Considered**:

1. Migrate all `lines` entries to `function` — impossible for the 9 that
   remain, which are shell scripts and a module-level import with no enclosing
   function.
2. Add a content hash to each entry — drift-proof, but it makes every entry
   brittle against legitimate reformatting and adds maintenance burden to a
   file that is edited rarely.
3. Report exclusions that match nothing — catches drift AND spent licences,
   works identically for both keying styles, and needs no schema change.

**Decision**: Option 3. It targets the actual failure (a suppression that is
no longer doing what it claims) rather than one mechanism that can exhibit it.

**Date**: 2026-08-12

## Success Criteria

- [x] An exclusion matching no finding fails QA with an actionable message
- [x] Both `lines` and `function` keying are covered
- [x] The check runs against the real exclusions file, not only fixtures
- [x] The live file is clean, with every removal individually justified

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). -->

- Found while auditing the drift incident recorded in Plan 00209's journal
