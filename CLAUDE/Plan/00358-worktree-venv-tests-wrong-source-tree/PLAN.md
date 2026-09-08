# Plan 00358: a worktree venv can silently test the WRONG source tree

**Status**: Not Started
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

- [ ] ⬜ **Task 1.1**: Decide where the assertion lives. Leading candidate is a
  session-scoped `conftest.py` check comparing the imported package's resolved
  path against the repository root that `pytest` was invoked from, failing with
  BOTH paths. Alternative: a `venv-include.bash` check at activation, which
  covers non-pytest entry points too but cannot see what Python ultimately
  imports. Record which, and why the other was not chosen.

- [ ] ⬜ **Task 1.2**: Decide the failure mode. A hard error is right for a
  test session (a silent wrong answer is the whole problem), but confirm it
  cannot break the legitimate cases: the acceptance fixture that clones the
  repo to a temp dir, and any deliberate cross-checkout invocation.

### Phase 2: Build it

- [ ] ⬜ **Task 2.1**: RED — a test proving the check fires when the resolved
  package sits outside the invoking repository root.

- [ ] ⬜ **Task 2.2**: GREEN — the check, with a message that names the
  resolved path, the expected root, and the one-line remedy
  (`./scripts/setup_worktree.sh`).

- [ ] ⬜ **Task 2.3**: Confirm the legitimate cases from Task 1.2 still pass —
  specifically the end-to-end install acceptance fixture, which deliberately
  runs against a clone.

### Phase 3: Close the dispatch gap

- [ ] ⬜ **Task 3.1**: Make the remedy discoverable at the moment it is needed.
  The `worktree_create` advisory already fires on worktree creation; adding the
  `setup_worktree.sh` step to what an agent is told there costs nothing and
  addresses gap 3 directly. This is belt-and-braces to the Phase 2 check, not a
  substitute for it — advice is not a check.

## Success Criteria

- [ ] A test run whose package resolves outside the invoking repository root
  fails, naming both paths
- [ ] The end-to-end install acceptance fixture (which legitimately runs
  against a clone) still passes
- [ ] The remedy is stated where a worktree is created, not only in
  `CLAUDE/Worktree.md`

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00358-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed from a live incident: a sub-agent's correct fix appeared as 15 test
  failures, and the symlink chain was traced on disk rather than guessed.
