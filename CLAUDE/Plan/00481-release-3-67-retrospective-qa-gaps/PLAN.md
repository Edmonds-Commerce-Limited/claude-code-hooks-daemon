# Plan 00481: release 3.67 retrospective - how #68 shipped, and the QA gaps

**Status**: Not Started
**Created**: 2026-10-02
**Owner**: dev
**Priority**: High
**Recommended Executor**: Opus (investigation), Sonnet (gate implementation)
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #68 (the defect that prompted the retrospective; fixed in 92b9b49e0)

## Overview

The owner asked how a release went out with a defect this large, and where the gaps are in
acceptance testing and QA.

v3.67.0 shipped `secret_file_guard` and `quarantine_artefact_read_guard` in a state that fails
closed (`TooManyToEnumerateError`, an EVALUATION-ERROR deny) on ordinary read-only commands.

- **Examples**: `cat /tmp/x/*/*` and the loop form `"$x"$F/*/*`.
- **Trigger**: any absolute glob with two or more wildcard segments under an existing directory.
- **Reproduced**: on main before the fix, with `untracked/scratch/gh68_repro.py`.
- **Root cause**: `bounded_recursive_glob` in `src/claude_code_hooks_daemon/utils/shell_expansion.py`
  counted wildcard segments across the whole pattern from `/`, ignoring an existing literal
  prefix.
- **Fix**: ledger 00474 N293.

A fix is not a retrospective. This plan asks why nothing between the commit and the tag caught
a deny on shapes this common, and closes those gaps with gates that would have caught it.

## Goals

- A written causal account of #68. It covers:
  - which commit introduced the refusal;
  - what its tests covered, and what they did not;
  - why each release gate (QA, acceptance tests, code review, dogfooding) let it through.
- Every gap found is closed by a gate, a test corpus or a process change, and each closure is
  shown to catch #68 when run against the pre-fix tree.
- A false-positive measure for the safety guards that a release can be gated on.

## Non-Goals

- Re-fixing #68 (done in N293).
- The release-process redesign of Plan 00476 (release through a PR with CI tagging). Findings that
  belong there are handed over, not rebuilt here.
- Handler crash containment: that is Plan 00482.

## Tasks

### Phase 1: Causal account (read-only investigation)

- [ ] ⬜ **Task 1.1**: Trace the root-refusal and multi-segment rule in `bounded_recursive_glob`.
  - The commit that introduced it, the plan and review finding it answered (its docstring cites
    Plan 00466 review 3), and the tests it added.
  - Record what those tests asserted and what input shapes they never tried.
- [ ] ⬜ **Task 1.2**: Trace each gate the change passed through: targeted QA, full QA at release
  prep, the acceptance-test run, the release code review, and dogfooding in this repository.
  - For each one, establish whether it ran an input that could have hit the defect.
  - If it did not, say why. If it did, say why the deny was not noticed.
- [ ] ⬜ **Task 1.3**: Prior art. Read the earlier fail-closed false-positive fixes the dedupe scout
  named: Plans 00356, 00357, 00200, and ledger 00466 N101 and N38. Decide whether #68 is a
  recurrence of a known class that should already have had a standing defence.
- [ ] ⬜ **Task 1.4**: Write `RETROSPECTIVE.md`. It sets out the causal chain, the gaps ranked by
  how much they would have caught, and what was luck (for example, the defect reaching an external
  user before an internal one).

### Phase 2: Close the gaps (TDD; each gate proven against the pre-fix tree)

- [ ] ⬜ **Task 2.1**: A realistic command corpus for the safety guards: ordinary read-only shell
  shapes (absolute globs, loops over `"$var"/…`, substitutions, regex operands, script content).
  - Every command in it must be ALLOWED when no protected file is reachable, and DENIED when one
    is planted.
  - Seed it from #68 and the N269, N291 and N293 cases, and from this repository's own denied-command
    history if one exists.
- [ ] ⬜ **Task 2.2**: Make the corpus a QA gate that runs on every change to the guard or
  shell-expansion code.
  - Prove it fails on the parent of the #68 fix.
  - Run it with the daemon-like process cwd `/`, the condition that turned relative words into
    root walks.
- [ ] ⬜ **Task 2.3**: An EVALUATION-ERROR deny rate as a release signal.
  - Count fail-closed evaluation errors per guard over the dogfooding window, from the verdict
    log (Plan 00209).
  - Block or flag a release when the count is above zero or above a threshold. The owner
    decides which (open question 1).
- [ ] ⬜ **Task 2.4**: Acceptance tests. Check whether the acceptance playbook exercises any
  realistic multi-wildcard or loop shape for these guards, and add the corpus's representative
  cases.
- [ ] ⬜ **Task 2.5**: Any further gap Phase 1 finds, one task each.

### Phase 3: Hand-over

- [ ] ⬜ **Task 3.1**: Feed release-process findings to Plan 00476. Record any new standing
  rule in `CLAUDE/development/RELEASING.md` and in `LESSONS.md`.

## Open questions for the owner

1. Should a non-zero fail-closed evaluation-error count during dogfooding BLOCK a release, or
   only be shown in the release report?
2. Should the realistic-command corpus also run on client-shaped projects (Plan 00470 hosts),
   or only on this repository?

## Success Criteria

- [ ] `RETROSPECTIVE.md` explains, gate by gate, why #68 shipped.
- [ ] Run against the parent of 92b9b49e0, the new corpus gate FAILS on the #68 shapes. On main
  it passes.
- [ ] The release checklist carries the new gate(s).

## Delivery & Milestones

- Plan filed at the owner's request after #68.
