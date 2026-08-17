# Plan 00253: Plan 00249 review findings

**Status**: In Progress
**Created**: 2026-08-17
**Owner**: Claude (Opus 5)
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

A peer review of the Plan 00248 + 00249 diff (`4d1a553b1..HEAD`, 15 files)
returned six findings and eight explicitly-checked-and-unfounded candidates.
**Every finding was re-verified here by execution before being written down**,
per the standing discipline that a report is evidence rather than an oracle —
and one mechanism description needed correcting (see finding F). None was
dismissed.

Two are blocking, and they compound: F-A produces the natural partial batch that
exposes F-B. Both live in `delete-branch`, the daemon's own branch-deletion tool,
so this is dogfooding: the tool currently promises a delete it cannot perform,
and then reports a partial batch as though nothing happened while withholding the
only recovery route for the branch it did delete.

## Verified findings

| ID  | Severity   | Where                               | Defect                                                              |
| --- | ---------- | ----------------------------------- | ------------------------------------------------------------------- |
| A   | BLOCKING   | `daemon/branch_safety.py:228-232`   | `-d`'s HEAD predicate is uncovered, so the dry run promises wrongly |
| B   | BLOCKING   | `daemon/cli.py:3012-3024`           | A partial batch reports "nothing was deleted" and hides the bundle  |
| C   | SHOULD-FIX | `tests/…/test_branch_safety.py:742` | The bundle-budget test guards a constant, not the call site         |
| D   | SHOULD-FIX | `tests/…/test_branch_safety.py:751` | Test name says "refusal"; it asserts the raise                      |
| E   | NOTE       | `handlers/…/version_check.py:33-40` | Correct fix, false stated reason; narrow behaviour change           |
| F   | NOTE       | `daemon/branch_safety.py:387-399`   | `ls-tree` quotes paths, `rev-list --objects` does not — miscount    |

Per-finding evidence — the reproductions, the exact classifier and git output,
and the correction to the report's finding-F mechanism — is in
[FINDINGS.md](FINDINGS.md). It is durable detail rather than current truth, so
it lives beside the plan instead of inside it.

## Goals

- `delete-branch`'s dry run and real run agree in every state, including HEAD
  elsewhere.
- A partial batch reports what actually happened and always discloses a
  surviving bundle.
- The bundle budget the code calls critical is guarded by a test that fails when
  it is removed.
- Every remaining finding is fixed or explicitly recorded as declined with a
  reason. None is dropped.

## Non-Goals

- Widening `merged` to force-delete. F-A is a classification bug, not a licence
  to escalate; `-D` on a branch git will not `-d` is exactly what
  `destructive_git` exists to prevent.
- Re-litigating the eight unfounded candidates the review checked by execution
  (`gone` upstream, `remote=.`, self-upstream, `/` in names, a local branch
  shadowing `origin/<name>`, leading-`-` names, the timeout constants, `_make_stale`
  residual vacuity). They are recorded in the journal so a later pass does not
  redo them.
- Fixing the ambient-git-premise class or the staged-content secret gap. Those
  are Plan 00252, and the review confirmed no remaining sibling of the
  missing-identity defect in these files (190 passed with no identity reachable).

## Tasks

### Phase 1: The dry run must not promise what git refuses (finding A)

- [x] ✅ **Task 1.1**: RED — a branch merged into `main`, with no upstream, while
  HEAD is on another branch: classifier says `merged`/safe, real git refuses
  - [x] ✅ New `_merged_but_head_is_elsewhere` fixture, because every existing one
    returns to `main` before classifying — which is why the whole axis was
    uncovered
  - [x] ✅ RED proved by reverting ONLY the defect (`tracking or HEAD` →
    `tracking or name`, which restores "no upstream ⇒ git will accept"):
    4 failed / 4 passed, then 57 passed with the fix
- [x] ✅ **Task 1.2**: GREEN — mirror git's actual rule: the reference is
  `<name>@{upstream}` when it resolves, else HEAD (the detached commit when
  detached); require ancestry into that reference
  - [x] ✅ Git's rule established by EXECUTION before any test asserted it: an
    upstream that resolves is used exclusively (a branch level with
    `origin/<name>` deletes while absent from HEAD), and a detached HEAD refuses
    exactly as an attached one does
  - [x] ✅ Extracted as `_safe_delete_reference` returning the REF, not a boolean,
    so the choice lives in one place
- [x] ✅ **Task 1.3**: Fix the tier detail. `merged-unpushed`'s text ("until those
  commits are pushed") is false for the HEAD case, so widen it or add a tier
  - [x] ✅ Added `TIER_MERGED_NOT_IN_HEAD` rather than widening: no push is
    involved, and a tier whose name misdescribes the refusal is the defect this
    tier exists to remove
- [x] ✅ **Task 1.4**: Correct the `_is_merged_into_its_upstream` docstring, whose
  stated justification is the defect
  - [x] ✅ Renamed to `_tier_for_merged_branch`; the old name described the wrong
    question
- [x] ✅ **Task 1.5**: Re-check the `destructive_git` guidance at `:248` once the
  gap is actually filled, so the resident text stays true

### Phase 2: A partial batch must report what happened (finding B)

- [x] ✅ **Task 2.1**: RED — a partial report (some deleted, one refused, bundle
  written) currently prints "nothing was deleted" and withholds the bundle path
  - [x] ✅ RED proved by restoring HEAD's `cli.py` wholesale: 4 failed / 3 passed,
    then 7 passed with the fix
  - [x] ✅ `test_a_genuine_partial_batch_produces_this_shape` builds the shape with
    REAL git, so the other six tests are not resting on an invented report
- [x] ✅ **Task 2.2**: GREEN — branch on `report.deleted`: name what went, print
  the bundle path whenever one survives, and offer `--allow-unproven` only when a
  tier is actually `unproven`
- [x] ✅ **Task 2.3**: Keep the exit code non-zero — a refusal happened, and the
  bug is the message, not the status
- [x] ✅ **Task 2.4**: Confirm `--format json` still agrees with the text path
  - [x] ✅ The JSON path was already correct and is untouched; it reports
    `refused`, `deleted` and `bundle` as independent fields

### Phase 3: Make the two vacuous tests load-bearing (findings C, D)

- [x] ✅ **Task 3.1**: Replace the constant comparison with a spy on
  `branch_safety.run_git` asserting the argv/timeout pair, as
  `tests/unit/core/test_claude_md_injector.py` already does
  - [x] ✅ Proved: the SAME mutation that previously left 64 tests passing now
    fails exactly one test — the right one
  - [x] ✅ Kept the constant comparison as a secondary assertion, so the test
    covers both "the call passes the big budget" and "the big budget is bigger"
- [x] ✅ **Task 3.2**: Either rename the timed-out test to what it asserts, or move
  the assertion to the CLI boundary where the refusal conversion lives
  - [x] ✅ Renamed to `test_a_timed_out_bundle_raises_for_the_cli_to_convert`, and
    its docstring now points at the CLI test class that covers the conversion

### Phase 4: The two notes (findings E, F)

- [x] ✅ **Task 4.1**: Correct the `_CWD_IMMATERIAL` comment — the root
  deliberately bypasses repo-local remote config — and decide explicitly whether
  to prefer the project root with `Path("/")` as fallback
  - [x] ✅ Renamed to `_REMOTE_ONLY_CWD`, since "immaterial" was the false claim
  - [x] ✅ Decided to KEEP the root, and recorded the trade in the comment rather
    than leaving it implicit: the URL is fixed and known-external, a client's
    repo-local `insteadOf` almost always redirects ITS dependencies (so honouring
    it is as likely to send the check to a mirror with no such repo), and proxy/CA
    settings that must apply are conventionally global or system — which are still
    read. The bounded cost is no advisory rather than a wrong one
- [x] ✅ **Task 4.2**: Make the two path listings comparable (`-z` on both sides,
  or `-c core.quotePath=false`), with a non-ASCII-path test
  - [x] ✅ `-c core.quotePath=false` on both `ls-tree` calls; verified by execution
    that the two outputs are then byte-identical
  - [x] ✅ Three tests, and all three fail with the flag removed
- [x] ✅ **Task 4.3**: Deduplicate the copied test setup the review flagged — the
  12-line block in `test_claude_md_injector.py` and the byte-identical `remote`
  fixture in two `test_branch_safety.py` classes
  - [x] ✅ `_seed_repo_without_a_claude_md` extracted; it also pins `commit.gpgsign`
    and `tag.gpgsign` off, which is the live sibling of the ambient-premise class
    the review found in exactly these two files (Plan 00252 owns the guard)
  - [x] ✅ `remote` promoted to a module-level fixture — including in the test I
    had just written, which had quietly become a third copy

### Phase 5: Verify

- [ ] ⬜ **Task 5.1**: Full QA green, daemon restart RUNNING
- [ ] ⬜ **Task 5.2**: Re-run the two blocking reproductions and confirm both now
  behave correctly, rather than trusting the unit tests alone
- [ ] ⬜ **Task 5.3**: Client-mode verification — `delete-branch` is a CLI command
  whose repo resolution differs in a client install

## Dependencies

- Follows: Plan 00249 (Complete) and Plan 00248 (Complete) — this is the review
  of their combined diff.
- Related: Plan 00252, which covers the test-environment class the same review
  confirmed has no remaining sibling in these files.

## Technical Decisions

### Decision 1: mirror git's predicate, do not widen the tier

**Context**: F-A could be "fixed" by classifying the uncovered case as
`merged-unpushed`, which force-deletes and would make the reproduction pass.

**Decision**: no. The dry run would then be honest, but the tool would
force-delete a branch git declines to delete safely — trading a wrong promise for
a wrong action. Git applies one rule with two references; the fix is to compute
against the same reference git will use, so the classification is right and the
`-d`/`-D` choice follows from it.

**Date**: 2026-08-17

### Decision 2: the exit code stays non-zero on a partial batch

**Context**: F-B's message says a refusal happened when a deletion also happened,
so one option is to treat a partial success as success.

**Decision**: no. Something the caller asked for did not happen, and a zero exit
would hide that from any script. The defect is the message asserting "nothing was
deleted" and suppressing the bundle path — fix the words and the disclosure, keep
the status.

**Date**: 2026-08-17

### Decision 3: keep continue-and-report; change the SIGNAL, not the loop

**Context**: a mid-loop git refusal currently continues through the remaining
branches and reports what happened. The alternative is to abort on the first
refusal. Put to the reviewer as the one thing this plan had not interrogated.

**Decision**: keep continuing. The load-bearing reasons, each checked here rather
than accepted:

- **Stopping buys no atomicity.** A ref removed before the refusal stays removed
  either way, so the choice is between two mixed states, not between a mixed one
  and a clean one.
- **Stopping makes the surviving set depend on argument ORDER.** Same repo, same
  proofs, `delete-branch a b c` and `c b a` would leave different branches behind.
  Continuing is order-independent.
- **Continuing adds no unrecoverable exposure.** Verified by reading
  `delete_branches`: the bundle is written for EVERY classified branch before any
  ref is removed, so recovery coverage is uniform and does not depend on how far
  the loop got.
- **A refusal does not invalidate the remaining classifications.** A remaining
  `-d` tier is predicted by the same predicate and git will independently refuse it
  too (reported, nothing lost); a remaining `-D` tier rests on this project's own
  patch-id/blob-sha proof, which git never consults, so git's opinion about branch
  N carries no information about branch N+1.
- **Aborting on a transient is the worse failure.** This project deliberately runs
  parallel agents in one checkout, so a peer touching one branch would abort a
  legitimate multi-branch cleanup.

**What changed instead**: the blocker now carries a DIAGNOSIS, not just the fact.
Once the predicate mirrors git on both axes, a refusal means our model disagreed
with git, and there are exactly two causes — a concurrent change, or a predicate
gap. Naming both and how to distinguish them turns each occurrence into a bug
report: DBF applied to the guard's OUTPUT rather than its control flow.

**Date**: 2026-08-17

### Decision 4: exit code marks "not what you asked for", JSON carries the detail

**Context**: on a partial batch the exit code alone cannot distinguish "nothing
went" from "two of three went" — only `--format json` carries `deleted`.

**Decision**: the exit stays non-zero (a batch that did not do what was asked must
not exit 0), and the asymmetry is recorded rather than left implicit: **a scripted
caller must parse `--format json` to act on a partial, and must not read the
non-zero exit as "no change to the repository".** The text path now says
`PARTIALLY REFUSED` and names what went, so a human reading stderr is not misled;
the constraint is on machine callers only.

**Date**: 2026-08-17

## Success Criteria

- [ ] Classifier and real git agree for a merged branch with no upstream while
  HEAD is elsewhere, verified by executing both
- [ ] A partial batch names what was deleted and prints the surviving bundle path
- [ ] Removing the bundle timeout from the call site fails the suite
- [ ] The non-ASCII path count is correct
- [ ] Every finding is fixed, or declined in writing with its reason
- [ ] QA green, daemon restart RUNNING, client-mode verified

## Risks & Mitigations

| Risk                                                           | Impact | Probability | Mitigation                                                                                     |
| -------------------------------------------------------------- | ------ | ----------- | ---------------------------------------------------------------------------------------------- |
| The HEAD fix escalates branches to `-D` that git would refuse  | High   | Low         | Decision 1 forbids widening; tests assert the argv AND that real git accepts it                |
| Detached HEAD is a distinct third reference and gets missed    | Medium | Medium      | Task 1.2 names it explicitly; a detached-HEAD fixture is required                              |
| The reworded partial-batch message drifts from the JSON output | Medium | Medium      | Task 2.4 makes agreement an explicit condition                                                 |
| Fixing the path quoting changes the safety proof by accident   | High   | Low         | The review re-verified `_reachable_object_shas` is sha-based and unaffected; keep it untouched |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow log lives in JOURNAL/. -->

- Filed at the commit that adds this plan.
