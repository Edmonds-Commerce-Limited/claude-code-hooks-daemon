# Plan 00358: a worktree venv can silently test the WRONG source tree

**Status**: Complete
**Created**: 2026-09-08
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

A sub-agent working Plan 00356 in a harness-created worktree
(`Agent(isolation: "worktree")`) wrote a correct fix and correct tests, and its
tests could not see the fix. It reported 15 failures that look exactly like
real failures, and stalled. The same tests pass **177/177** on `main` once the
branch is merged — the code was never wrong.

**Mechanism, verified on disk:**

```text
<worktree>/untracked/venv        -> /workspace/untracked/venv
/workspace/untracked/venv        -> /workspace/untracked/venv-workspace-py311-<fp>
that venv's __editable__*.pth    -> /workspace/src
```

So `pytest` inside the worktree imports `claude_code_hooks_daemon` from
**`/workspace/src`** — the MAIN checkout — not from the worktree's own `src/`.
Confirmed directly: importing the package inside the worktree prints
`/workspace/src/claude_code_hooks_daemon/__init__.py`.

The `untracked/venv` symlink is dated during the agent's run, so it was created
by the agent (or by `ensure_venv` falling back), not by the harness.

**Why this is worse than an ordinary mistake.** The RED phase still "passes" —
the new symbol genuinely does not exist in main's source, so the test fails for
a plausible-looking reason. The GREEN phase can then NEVER pass, no matter how
correct the fix, and the failure text names the test rather than the cause. An
agent reads that as "my fix is wrong" and keeps editing working code. It also
means any QA result a worktree agent reports may describe main's source, so a
green run is not evidence about the branch.

## Goals

- A test session that imports the package from outside the current repository
  root fails LOUDLY, naming the resolved path, instead of silently testing
  someone else's code.
- The condition is detected wherever it arises, not only at worktree-creation
  time.

## Non-Goals

- **Not** changing the fingerprint venv layout or `resolve_venv`. The layout is
  correct and Plan 00184 already made venv accounting symlink-aware; the defect
  is the absence of a check, not the design.
- **Not** forbidding a shared venv outright. Sharing is a reasonable thing to
  want for speed on a read-only worktree; what is not reasonable is sharing one
  whose editable install silently points elsewhere while tests run.
- **Not** re-deriving whether the agent "should have known". The documented
  workflow already says so (below) — a rule that is documented and still
  produces a silent wrong answer needs a check, not a louder rule.

## Context & Background

`CLAUDE/Worktree.md` already mandates `./scripts/setup_worktree.sh`, whose
step 5 "Verifies the editable install points at the worktree's own `src/`", and
states plainly: "**Never hand-build the venv**". So the CREATION path is
guarded. Three gaps remain:

1. Nothing re-checks at TEST time, so a venv that becomes wrong later is silent.
2. Nothing prevents a symlink being added after creation.
3. `Agent(isolation: "worktree")` creates a worktree WITHOUT going through
   `setup_worktree.sh`, so an agent landing in one finds no venv and is nudged
   toward improvising exactly this.

Gap 3 is the one that made this happen, and it is the one the project does not
control — the harness creates that worktree. So the remedy has to be a check
that fires regardless of how the worktree was made.

| Plan  | Title                            | Status      | Relevance                                     |
| ----- | -------------------------------- | ----------- | --------------------------------------------- |
| 00184 | venv accounting is symlink-aware | Complete    | Same hazard family: a venv symlink misleading |
| 00356 | secret guard bracket glob        | In Progress | The plan whose agent hit this                 |
| 00100 | venv SSoT consolidation          | Dormant     | Owns the venv resolution surface              |

## Tasks

### Phase 1: Decide the check

- [x] ✅ **Task 1.1**: The assertion lives in `tests/source_tree_guard.py`,
  called once per session from `tests/conftest.py`'s `pytest_sessionstart`.
  The activation-time alternative was not chosen because it cannot see what
  Python ultimately imports, and the defect is exactly what Python imports.

- [x] ✅ **Task 1.2**: Hard error, raised before any test runs. The nested
  pytest runs some integration tests spawn write their own `conftest.py` in a
  temp directory and never load `tests/conftest.py`, so they are unaffected;
  a clone that used a foreign venv WOULD be refused, which is the correct
  answer for a clone too.

### Phase 2: Build it

- [x] ✅ **Task 2.1**: RED — `tests/unit/test_source_tree_guard.py` proves the
  check fires for a package resolved from another checkout, including the
  incident shape where a symlinked `src/` looks local until resolved.

- [x] ✅ **Task 2.2**: GREEN — `assert_package_is_this_checkout` names the
  imported path, the expected root and `./scripts/setup_worktree.sh`.

- [x] ✅ **Task 2.3**: Full QA on `main` is the legitimate case and passes with
  the guard armed; the nested-pytest integration tests pass unchanged.

### Phase 3: Close the dispatch gap

- [x] ✅ **Task 3.1**: The `worktree_create` handler's injected CLAUDE.md
  guidance now states that a fresh worktree has no venv and names the setup
  script, with a test pinning both strings; `CLAUDE/Worktree.md` describes
  the symlink variant and the guard.

## Success Criteria

- [x] A test run whose package resolves outside the invoking repository root
  fails, naming both paths
- [x] The end-to-end install acceptance fixture (which legitimately runs
  against a clone) still passes
- [x] The remedy is stated where a worktree is created, not only in
  `CLAUDE/Worktree.md`
- [x] Every release-bound consequence is in the pending-release holding area:
  `UNRELEASED/release-notes/06-worktree-guidance-names-the-venv-remedy.md`
  (the conftest guard itself is this repository's; the handler guidance ships)

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00358-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed from a live incident: a sub-agent's correct fix appeared as 15 test
  failures, and the symlink chain was traced on disk rather than guessed.
- Shipped the same day, while seven worktree agents were mid-flight on the
  release-review ledgers; their reported test results are treated as
  unverified and each branch is re-run on `main` after merge.
