# Plan 00516: journal in place redaction

**Status**: Not Started
**Created**: 2026-10-13
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #108

## Overview

The owner filed #108 after ledger 00474 N389: two committed journal lines (in archived Plan 00413's journal) held the
development host's real name, and the coordinator left them for a human because "journal entries are not
hand-edited". The issue proposes a controlled correction tool.

What the code allows today (verified on main):

- `plan_journal_guard` (R-JOURNAL-HAND-WRITTEN-ENTRY, Plan 00461) denies a `Write`/`Edit` into a day-file only when
  it adds a non-blank line or an entry heading, and denies any `Bash` write into one. Its docstring names "a
  same-line redaction" as an Edit that passes. So an Edit-tool redaction of a past line is not blocked.
- `journal-append-only` (plan QA, Plan 00163) flags any non-append edit, but is advisory forever: "a same-day typo
  fix is a legitimate non-append", and `mode: block` never escalates it. Its remediation text says corrections are
  new entries, never rewrites.
- `mkplan.bash --journal <plan> correction <body> --ref [YY-MM-DD/]HH:MM` appends a stamped `correction` entry naming
  the entry it corrects, and refuses a `--ref` that names no entry. That fixes a wrong fact while keeping the
  original visible, but cannot remove a leaked value.

So the gap is policy, not mechanism: nothing documents when an agent may change a past line in place. This plan
proposes a narrow, documented redaction procedure using the tools that exist, and builds new tooling only if the
owner wants it.

## Goals

- A documented redaction procedure in `CLAUDE/PlanJournalling.md`: replace a leaked value with a placeholder in the
  past line using the Edit tool (same line count, no heading touched), then append a `correction` entry with `--ref`
  naming that entry, recording the reason and the placeholder, never the removed value.
- The `journal-append-only` remediation text names that procedure for a redaction, so an agent that hits the
  advisory is pointed at the audited route rather than told it may never change a past line.
- N389's two lines redacted by that procedure once the owner approves it.

## Non-Goals

- Rewriting git history. The value stays in earlier commits; purging it is a history rewrite, which is a human's
  action.
- Loosening `plan_journal_guard`: added lines and Bash writes stay denied.
- Rewording past entries for any reason other than redaction. A wrong fact gets an appended `correction`.

## Open questions for the owner

1. **Policy:** may an agent redact a leaked value in a past journal line in place, using the Edit tool, provided it
   appends a `correction` entry? Recommended: yes, for redaction only.
2. **Tooling:** is the documented procedure enough, or should `mkplan.bash` gain a `--journal-redact` mode that
   performs the replacement and appends the correction entry in one step (as #108 proposes)? Recommended: the
   procedure first; a tool only if the procedure is used often or gets misapplied.
3. **N389's two lines:** redact them now, under the procedure? And add the host name to the secret word list (a
   human-only edit) so it cannot recur?

## Tasks

### Phase 1: Owner decision

- [ ] ⬜ **Task 1.1**: Owner answers the questions above.

### Phase 2: Procedure (if question 1 is yes)

- [ ] ⬜ **Task 2.1**: Document the redaction procedure in `CLAUDE/PlanJournalling.md` (and its install template
  `src/claude_code_hooks_daemon/install/templates/PlanJournalling.md`).
- [ ] ⬜ **Task 2.2**: TDD the `journal-append-only` remediation text naming the procedure for a redaction.
- [ ] ⬜ **Task 2.3**: Redact N389's two lines by the procedure; close N389's journal half.
- [ ] ⬜ **Task 2.4**: Only if question 2 asks for it: `mkplan.bash --journal-redact`, TDD. The existing `--ref`
  check only confirms an entry exists, so it needs entry-body extraction added.

## Success Criteria

- [ ] An agent can remove a leaked value from a past journal entry by a documented, audited route, leaving an
  appended `correction` entry that names the entry, the reason and the placeholder.
- [ ] Added lines and Bash writes into a day-file are still denied.
- [ ] Release-bound consequences (a docs change shipped in the install template; a `mkplan.bash` mode if built) are
  recorded in the UNRELEASED release notes, or the plan records that there are none.

## Delivery & Milestones

- Plan filed from #108 (ledger 00474 N389). Related: Plan 00163 (journalling), Plan 00461 (stamping-tool guard).
