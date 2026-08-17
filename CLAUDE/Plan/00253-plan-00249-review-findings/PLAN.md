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

### A — reproduced: `tier=merged`, `is_safe=True`, and git refuses

`_is_merged_into_its_upstream` returns `True` when no upstream resolves, on the
stated grounds that "git then falls back to HEAD, which the caller's ancestry
proof already covers". The caller's proof is against `protected_ref` (default
`main`), **not** HEAD, so the fallback is not covered at all.

Executed against real git — branch `done` merged into `main`, HEAD on `work`,
`done` with no upstream:

```
done in main? : True        done in HEAD? : False      upstream: (rev-parse exit 128)
CLASSIFIER  tier='merged' is_safe=True
            detail='tip is an ancestor of the protected ref — nothing can be lost'
            argv=('branch', '--delete')
REAL GIT    exit=1  error: The branch 'done' is not fully merged.
            branch still present: True
```

This is the exact dry-run/real-run contradiction Plan 00249 was opened to
remove, reappearing on the HEAD axis rather than the upstream axis — both come
from git's single `branch_merged()` rule. The trigger is an ordinary workflow:
tidying a merged branch while standing on another one.

It also dead-ends the agent: `-d` refuses, `delete-branch` refuses, and
`git branch -D` is denied by `destructive_git` — so the guidance at
`handlers/pre_tool_use/destructive_git.py:248` ("that specific gap is what
`delete-branch` fills") now has a third refusal reason it does not fill.

Pre-diff this state crashed, so the diff did improve it. The label and the dry
run are still wrong.

### B — reproduced end to end: three inaccuracies in one message

`delete_branches` (`branch_safety.py:555-578`) deliberately allows
`refused=True` with a non-empty `deleted`, and deliberately KEEPS the bundle when
something was deleted. The CLI was not updated for that: `if report.refused:`
prints a hard-coded "REFUSED — nothing was deleted." and returns 1 at `:3024`,
before the bundle disclosure at `:3030-3033`.

Executed through the real `cmd_delete_branch` (only the project-marker lookup
stubbed) with one `merged-unpushed` branch that force-deletes plus one
plain-`merged` branch that git refuses via F-A:

```
CLI exit=1
stderr: REFUSED — nothing was deleted. Blockers:
          - done: git refused the delete (proven merged) — …not fully merged.
        …re-run with --allow-unproven and --reason…
GROUND TRUTH
  branches now       : ['done', 'main', 'work']      <- 'shipped' IS gone
  bundle on disk     : True  829 bytes
  bundle path shown  : False
```

So: a branch WAS deleted; the only recovery route for it is withheld; and the
remediation offered is irrelevant because no tier was `unproven`.
`--format json` is correct (`:2978-2979`), so only the human path lies.

### C and D — two tests that cannot fail for the reason they name

C: `test_the_bundle_gets_a_larger_budget_than_the_reads` asserts only
`Timeout.GIT_BUNDLE_CREATE > Timeout.GIT_BRANCH_SAFETY`. It names neither
`write_recovery_bundle` nor `run_git`, and that assertion is the ONLY mention of
the constant anywhere under `tests/`. Verified by execution: downgrading the call
site at `:417` to the read budget leaves **64 tests passing** — while the
docstring at `:412-414` calls that call the one "that must not be killed
part-way".

D: `test_a_timed_out_bundle_is_reported_as_a_refusal` asserts
`pytest.raises(subprocess.CalledProcessError)` — the raise, not a refusal. The
refusal conversion lives at `cli.py:2957`; deleting that `except` clause leaves
this test passing. It re-tests `_git`'s pre-existing raise-on-nonzero.

### E — the fix is right, the comment is not

`_CWD_IMMATERIAL = Path("/")` correctly stops `Path.cwd()` raising
`FileNotFoundError` in a deleted working directory. But the comment asserts
"which directory it runs in is immaterial", and that is false: `git -C <dir>`
selects which repo-local config applies, and `ls-remote` reads
`url.<base>.insteadOf`, `http.proxy`, `http.sslCAInfo` and `credential.*` from
it. A project with a repo-local mirror or proxy silently loses it, and the
upgrade advisory just goes quiet.

### F — the mechanism is quoting, not decoding (correction to the report)

The report attributed this to `errors="replace"` turning raw non-UTF-8 bytes into
U+FFFD. Executed, the cause is narrower and broader at once — it is
`core.quotePath`, and it bites for **any** non-ASCII path, valid UTF-8 included:

```
ls-tree           -> b'"caf\\303\\251.txt"'     (octal-escaped AND quoted)
rev-list --objects -> b'…sha caf\xc3\xa9.txt'   (raw)
the two path texts MATCH: False
```

So `_paths_in_tree` (`ls-tree`) and `_paths_in_history` (`rev-list --objects`)
can never agree on a non-ASCII path, and the `"{len(unique_paths)} path(s) are new"` message at `:399` miscounts. Pre-existing, but pre-diff it aborted loudly
(`UnicodeDecodeError` is a `ValueError`, caught at `cli.py:2954` → exit 2); it is
now a silent miscount in the text a human reads before abandoning work.

The report's own verification that `_reachable_object_shas` is byte-identical was
re-confirmed as sound: the safety-critical content proof is unaffected. This is a
message defect, not a safety defect.

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

- [ ] ⬜ **Task 3.1**: Replace the constant comparison with a spy on
  `branch_safety.run_git` asserting the argv/timeout pair, as
  `tests/unit/core/test_claude_md_injector.py:869-888` already does
  - [ ] ⬜ Prove it: removing `timeout=Timeout.GIT_BUNDLE_CREATE` must now FAIL
    (it currently leaves 64 tests passing)
- [ ] ⬜ **Task 3.2**: Either rename the timed-out test to what it asserts, or move
  the assertion to the CLI boundary where the refusal conversion lives

### Phase 4: The two notes (findings E, F)

- [ ] ⬜ **Task 4.1**: Correct the `_CWD_IMMATERIAL` comment — the root
  deliberately bypasses repo-local remote config — and decide explicitly whether
  to prefer the project root with `Path("/")` as fallback
- [ ] ⬜ **Task 4.2**: Make the two path listings comparable (`-z` on both sides,
  or `-c core.quotePath=false`), with a non-ASCII-path test
- [ ] ⬜ **Task 4.3**: Deduplicate the copied test setup the review flagged — the
  12-line block at `test_claude_md_injector.py:852-864` duplicating `:803-815`,
  and the byte-identical `remote` fixture at `test_branch_safety.py:485-493` and
  `:597-605`

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
