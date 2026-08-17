# Plan 00248: Plan 00246 Review Findings

**Status**: Complete
**Created**: 2026-08-17
**Owner**: Claude (Opus 5)
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

A code review of Plan 00246 (the `run_git` migration — one bounded home for
every git spawn) landed after that plan had shipped, and it found six real
defects. Every one was verified against the code before this plan was filed;
two were verified by execution.

Two are regressions Plan 00246 itself introduced. That plan's whole point was
that a property held per-call-site drifts, so centralising it makes it hold by
construction. It is exactly the shape of change that quietly imposes the
CENTRE's defaults on a call site that needed something else — which is what
happened to `branch_safety`, whose runner was deliberately unbounded and now
has five seconds for a `git bundle create`.

None of this argues against the migration. Each finding is a small edit that
turns a correct design into wrong behaviour on one specific real path: a large
repository, a single invalid byte, a deleted working directory, a killed
`git add`.

## Goals

- Fix F1–F4: the four behaviour defects, each with a test that fails first.
- Close F5's three mechanically-closeable guard escapes, so the guard matches
  what its own docstring already claims ("unambiguous shapes").
- Fix F6: the fixture that can silently restore the vacuity it exists to
  prevent.
- Fix the two nits that are the same class of defect as Plan 00245's entire
  Phase 3 — a test depending on the ambient environment.

## Non-Goals

- Revisiting the migration. The design is right; the review says so explicitly.
- Chasing every escape shape in F5. `asyncio.create_subprocess_exec` and
  `shutil.which("git")` are not idioms this codebase uses, and a guard that
  guesses gets disabled (the doctrine `check_magic_values.py` established).
- Any release. This is repair of shipped-to-main-but-unreleased code.

## Verified findings

Each was re-derived from the source before being accepted — the review is a
peer's report, not an oracle.

| ID  | Severity   | Where                                              | Defect                                                                    |
| --- | ---------- | -------------------------------------------------- | ------------------------------------------------------------------------- |
| F1  | MUST-FIX   | `daemon/branch_safety.py:155`                      | `_git` lost its unbounded budget; `delete-branch` now has 5s for a bundle |
| F2  | MUST-FIX   | `utils/git_repo.py:74`                             | "Never raises" is false — `UnicodeDecodeError` escapes                    |
| F3  | SHOULD-FIX | `handlers/session_start/version_check.py:123`      | `Path.cwd()` unguarded, and can raise `FileNotFoundError`                 |
| F4  | SHOULD-FIX | `core/claude_md_injector.py:349`                   | the one kept lock-taking write got the 5s read budget                     |
| F5  | SHOULD-FIX | `tests/integration/test_git_spawns_are_bounded.py` | three unambiguous spawn shapes escape the guard                           |
| F6  | SHOULD-FIX | `tests/conftest.py::_make_stale`                   | non-recursive, so `expect_none` can pass vacuously one directory deep     |

### F1 — evidence

`git show 013b48e7~1` confirms the pre-migration `_git` passed **no** timeout.
It now inherits `run_git`'s default `Timeout.GIT_CONTEXT = 5`, a hook-context
budget, and caps `bundle create` (`:340`, `check=True`), `cherry` (`:200`) and
two `rev-list --objects` walks (`:228`, `:244`). On a repo with a few thousand
objects the bundle exceeds 5s, `run_git` returns 127, `_git` raises
`CalledProcessError`, and `cmd_delete_branch` catches only `ValueError` — so
the human-gated safety command dies with a traceback instead of refusing.

### F2 — evidence (executed)

`text=True` decodes with `errors="strict"`. Reproduced on a real repo holding
one invalid byte: `subprocess.run` raises `UnicodeDecodeError`, which is
`ValueError` — **not** `OSError`, **not** `SubprocessError`, so it is not
caught. `errors="replace"` returns `'valid then �� invalid'` instead.
This matters because two callers deleted their own except clauses citing the
"never raises" docstring, and one path (`claude_md_injector` →
`DaemonController.initialise`) would fail daemon startup.

## Tasks

### Phase 1: The two MUST-FIX behaviour defects

- [x] ✅ **Task 1.1**: F2 — make `run_git`'s contract true
  - [x] ✅ RED: a real repo holding `\xff\xfe`, committed and read back with
    `git show` — reproduced the escape verbatim through the production runner
  - [x] ✅ GREEN: `errors="replace"` at the chokepoint, one keyword for every
    caller
- [x] ✅ **Task 1.2**: F1 — restore a generous budget for `branch_safety`
  - [x] ✅ RED: asserts the budget is not `GIT_CONTEXT`, rather than provoking a
    real timeout — a repo big enough to exceed 5s would add minutes to the suite
    to prove what a constant states exactly
  - [x] ✅ GREEN: `Timeout.GIT_BRANCH_SAFETY` (120s) for the object walks, with
    `GIT_BUNDLE_CREATE` (300s) overridden per call for the pack
  - [x] ✅ `cmd_delete_branch` reports a git failure as a refusal quoting git's
    own stderr; two tests pin that the branch survives it

### Phase 2: The two SHOULD-FIX behaviour defects

- [x] ✅ **Task 2.1**: F3 — removed the `Path.cwd()` hazard in `version_check`
  - [x] ✅ `_CWD_IMMATERIAL` (the filesystem root) rather than catching the
    raise: `ls-remote` never reads the cwd, so the fix is to stop asking a
    question whose answer can fail
  - [x] ✅ Plus an argv assertion — the process-wide `subprocess.run` patch in
    that file means every test there would pass if the handler stopped calling
    git altogether
- [x] ✅ **Task 2.2**: F4 — gave the kept `git add` the write budget, so neither
  lock-taking call can be killed mid-index-write
  - [x] ✅ Needed a test of its own: staging runs only for an UNTRACKED
    CLAUDE.md, so the existing budget test never saw the call

### Phase 3: Guard and fixture quality (the plan's actual deliverable)

- [x] ✅ **Task 3.1**: F5 — closed the unambiguous escapes
  - [x] ✅ Four shapes, each RED first: `import subprocess as sp`,
    `from subprocess import run`, `from subprocess import run as launch`, and
    `args=` passed as a keyword
  - [x] ✅ Import bindings are resolved PER MODULE from that module's own
    imports, so a project-local `run(["git", ...])` is still not flagged — two
    negative tests pin that, because inferring from the name alone is the
    guessing this guard's docstring rules out
- [x] ✅ **Task 3.2**: F6 — `_make_stale` now drives from `git ls-files`
  - [x] ✅ A new test file treats the fixture as the SUBJECT: a throwaway repo
    whose only tracked file sits two directories down, where the old root-only
    scan touched nothing at all
  - [x] ✅ Both helpers fail loudly on a vacuous repo (no tracked files, no
    index) instead of raising a bare `FileNotFoundError` or passing silently
- [x] ✅ **Task 3.3**: The ambient-environment nits — `tmp_git_repo` now bounds
  every git call and disables `commit.gpgsign`/`tag.gpgsign` locally, so a
  developer who signs commits globally does not get a hung suite in a file that
  has nothing to do with signing

### Phase 4: Verify

- [x] ✅ **Task 4.1**: Full QA green, daemon restart RUNNING
  - [x] ✅ `12466 passed, 0 failed, 6 skipped | coverage: 95.1%`; every other
    check 0 violations. `error_hiding` is clean because `_discard_unused_bundle`
    RETURNS its failure into `DeletionReport.blockers` rather than logging and
    continuing — the checker was right, and reporting through the channel the
    module already has is better than an exclusion
  - [x] ✅ Daemon RUNNING (PID 1757054) on the new code
- [x] ✅ **Task 4.2**: Record the durable lesson: centralising a property
  imposes the centre's defaults on every call site that had its own
  - [x] ✅ In LESSONS.md, with the reviewable-diff corollary: the properties a
    call site can no longer choose (timeout, encoding, `check=`, env, cwd) are
    part of the change even though they appear nowhere in it

## Dependencies

- Follows: Plan 00246 (Complete) — these are findings against its delivery.
- Related: Plan 00245's Phase 3, which is the same ambient-premise defect class
  as Task 3.3.

## Technical Decisions

### Decision 1: fix in place rather than reopen Plan 00246

**Context**: Plan 00246 is Complete, archived and pushed. The findings are
against its delivered code.

**Decision**: a new plan. Reopening a completed plan makes its record a moving
target, and there is precedent here — Plan 00241 was "v3.53.0 review findings"
for exactly this shape. The findings table above carries the evidence so the
next reader does not have to re-derive it from a peer's report.

**Date**: 2026-08-17

### Decision 2: accept the review's findings, but re-derive every one

**Context**: the findings arrived from a sub-agent review, and a peer's report
is not an oracle — an earlier session in this same repository had an agent
report confidently on a rule that was live, calling it stale.

**Decision**: every finding was re-checked against the source before this plan
was filed, and the two MUST-FIX ones were verified by execution (`git show` for
F1's pre-migration state, a real invalid-byte repo for F2). The evidence sits in
this document rather than in the report, because the report is scrollback.

**Date**: 2026-08-17

## Success Criteria

- [x] `delete-branch` completes on a repository whose bundle takes longer than
  a hook-context budget — `GIT_BUNDLE_CREATE` (300s) for the pack,
  `GIT_BRANCH_SAFETY` (120s) for the object walks
- [x] `run_git` cannot raise, for any output any git command can produce
- [x] The guard catches all three unambiguous escape shapes — four, in the end:
  `import subprocess as sp`, `from subprocess import run`, the aliased form, and
  `args=` as a keyword
- [x] `expect_none` cannot pass vacuously on a repo with subdirectories
- [x] QA green (12466 passed, 95.1% coverage), daemon restart RUNNING

## Risks & Mitigations

| Risk                                                    | Impact | Probability | Mitigation                                                                      |
| ------------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------------------------- |
| A generous timeout re-opens the hang Plan 00246 bounded | Medium | Low         | The lock is still declined; a bounded-but-generous budget is not unbounded      |
| Widening the guard makes it flag legitimate code        | Medium | Low         | Only shapes whose argv is a literal starting `git` are matched, as before       |
| `errors="replace"` masks a real encoding problem        | Low    | Low         | Callers log or parse line-wise; a mangled byte is visible, a dead daemon is not |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow log lives in JOURNAL/. -->

- Filed at the commit that adds this plan.
- All six findings plus both nits delivered at `a74b0489`, jointly with Plan
  00249 — the two are entangled in `branch_safety.py`, where this plan's timeout
  fix and that plan's new tier touch the same `_git` runner.
