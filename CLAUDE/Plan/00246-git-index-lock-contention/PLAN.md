# Plan 00246: The Daemon Takes The Git Index Lock It Does Not Need

**Status**: In Progress
**Created**: 2026-08-17
**Owner**: Claude (Opus 5)
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Reported from dogfooding: the daemon's CLAUDE.md auto-commit is causing stale
`.git/index.lock` problems. Investigation found the auto-commit is real but the
smallest part — the daemon acquires the git index lock in the user's working tree
on three separate paths, one of them per-prompt and one per-status-refresh, and
**every one of those acquisitions is avoidable**.

`git status` does not just read. It refreshes the index and writes it back, which
takes `.git/index.lock`. Proven on a throwaway repo by comparing `.git/index`
inode+mtime across a run: invoked as the daemon invokes it, the index is
REWRITTEN; with `GIT_OPTIONAL_LOCKS=0` it is not. `GIT_OPTIONAL_LOCKS` appears
**zero times** in `src/` or `scripts/`.

So the daemon contends for the index lock with the agent working in the same
tree, and nothing anywhere detects or reports that contention — the failure
surfaces as a stale lock file or a mystifying "Unable to create
'.git/index.lock'" from an unrelated command.

## Goals

- No read-only git invocation the daemon makes takes the index lock.
- The one genuine writer (the CLAUDE.md auto-commit) holds the lock for the
  shortest possible window, is bounded by a timeout, and reports contention
  visibly instead of at `debug`.
- Route git invocations through the single bounded home the project already
  declared (`utils/git_repo.py`, Plan 00113), so the next call site cannot
  reintroduce this — a guard, not 30 hand-fixes.

## Non-Goals

- Changing WHAT the auto-commit commits, or whether it commits at all. Its
  purpose (stop an agent seeing a dirty CLAUDE.md and trying to revert it) is
  sound and unchanged.
- Clearing stale locks automatically. A daemon deleting another process's lock
  file is how you corrupt an index; detection and a clear diagnostic is the
  correct scope.
- Reducing the NUMBER of git spawns — Plan 00238 already did that for the status
  line (192 → 44 per 115 renders). This plan is about what each spawn LOCKS.

## Context & Background

### The three lock-taking paths

| Path                                                      | Runs                 | Lock taken                  |
| --------------------------------------------------------- | -------------------- | --------------------------- |
| `handlers/user_prompt_submit/git_context_injector.py:118` | every user prompt    | `git status`                |
| `handlers/status_line/git_branch.py:471`                  | every status refresh | `git status --porcelain=v2` |
| `core/claude_md_injector.py:331,343,353`                  | every daemon start   | `status` + `add` + `commit` |

### The auto-commit's own defects

`_auto_commit_if_dirty` is the least careful git caller in the codebase:

- **A `git add` that is only sometimes needed.** `git commit --only <file>`
  scopes the commit to that path irrespective of the index, so for a TRACKED
  CLAUDE.md the preceding `git add` is a second lock acquisition for nothing.
  It is NOT redundant when CLAUDE.md is untracked: tested, and
  `commit --only` then fails with `pathspec … did not match any file(s) known to git`. So the fix is to stage only when the status output says untracked, not to
  delete the call. (This plan asserted "buys nothing" before that was tested —
  see Decision 3.)
- **No `timeout=` on any of its four subprocess calls** (grep count: 0), while
  every other git caller in `src/` uses the `Timeout` constants. A wedged git
  stalls `DaemonController.__init__` indefinitely.
- **Failures logged at `debug`**, so contention is invisible.
- It runs synchronously on the daemon STARTUP path — and restart is mandated
  after every handler change, which is exactly when an agent is also running git
  commands in the same tree.

### Why this is ~30 sites wide instead of one line

`utils/git_repo.py` already states the principle: *"new git operations are added
as methods on `GitRepo`, not by re-implementing `subprocess.run(["git", ...])` in
each caller"*. Fifteen files bypass it. Had that held, the env var and the
timeout would each be a one-line change in one place. This is the DRY /
single-source-of-truth standard failing in a way that turned a one-line fix into
a sweep.

## Tasks

### Phase 1: Make the bounded home actually bound

- [x] ✅ **Task 1.1**: Write failing tests for a git runner that sets
  `GIT_OPTIONAL_LOCKS=0` and always carries a timeout
- [x] ✅ **Task 1.2**: Implement `run_git` in `utils/git_repo.py`, preserving the
  existing `None`-on-failure convention; route `_git_output` and `write_config`
  through it so no spawn remains outside the one bounded home
- [x] ✅ **Task 1.3**: Prove the lock is no longer taken — assert `.git/index` is
  not rewritten by a read through the runner, plus a control test proving the
  scenario would otherwise rewrite it (without which the assertion is vacuous)

### Phase 2: Fix the three lock-taking paths

- [x] ✅ **Task 2.1**: `git_context_injector` (per prompt) onto the runner
- [x] ✅ **Task 2.2**: `git_branch` status call (per refresh) onto the runner
- [x] ✅ **Task 2.3**: `claude_md_injector` — all four calls (`rev-parse`,
  `status`, `show`, `commit`) onto the runner
- [x] ✅ **Task 2.4**: Stage only when CLAUDE.md is untracked, so the tracked
  case takes one lock instead of two — and pin the untracked case in a test
- [x] ✅ **Task 2.5**: Bound the `commit` with `Timeout.GIT_COMMIT` (new, and
  deliberately generous) and log contention at WARNING with git's stderr
- [x] ✅ **Task 2.6**: Verify on the REAL repository — a daemon restart rewrites
  `.git/index` zero times and leaves no lock behind

### Phase 3: The guard (DBF — this is the real deliverable)

- [x] ✅ **Task 3.1**: Write a failing check that finds direct
  `subprocess.run(["git", ...])` outside the bounded home — landed as
  `tests/integration/test_git_spawns_are_bounded.py`, which found 17 spawns
  across 10 files
- [x] ✅ **Task 3.2**: Allowlist shape — an `_EXEMPT` dict keyed by path, whose
  value IS the reason, so an entry cannot be added without justifying itself
- [x] ✅ **Task 3.3**: No wiring needed — see Decision 4 (a test is binding by
  construction; a checker has to be wired into two runners and can publish its
  verdict where nothing reads it)
- [x] ✅ **Task 3.4**: Migrate the remaining callers until the check is green —
  all 17 spawns across 10 files, so `_EXEMPT` holds only the runner itself
- [x] ✅ **Task 3.5**: Clear the exclusions the migration made stale — removing
  the now-dead `try/except` blocks left 9 entries in
  `error_hiding_exclusions.json` matching no finding, and
  `test_audit_error_hiding.py` named every one

### Phase 4: Verify

- [ ] ⬜ **Task 4.1**: Daemon restart verification — RUNNING, no errors in log
- [ ] ⬜ **Task 4.2**: Full QA suite green
- [ ] ⬜ **Task 4.3**: Confirm by measurement that a daemon start and a prompt no
  longer rewrite `.git/index`

## Dependencies

- Related: Plan 00113 (GitRepo facade, Complete) — this plan makes its stated
  principle enforceable instead of aspirational.
- Related: Plan 00238 (handler cost tuning, Complete) — reduced git spawn COUNT;
  orthogonal to what each spawn locks.

## Technical Decisions

### Decision 1: set `GIT_OPTIONAL_LOCKS=0` rather than serialise access

**Context**: The daemon and the agent both run git in one working tree.

**Options Considered**:

1. A daemon-side mutex around git calls — serialises the daemon against itself
   but not against the agent, which is the actual collision. Solves nothing.
2. Retry-with-backoff on lock contention — makes the symptom rarer while leaving
   a pure read taking a write lock, and adds latency to a hook path.
3. Stop taking the lock at all for reads.

**Decision**: Option 3. A dirty-check has no business writing to the index; the
refresh is an optimisation git performs on our behalf and `GIT_OPTIONAL_LOCKS=0`
is the documented way to decline it. Contention then only exists around the one
real writer, where it belongs.

**Date**: 2026-08-17

### Decision 2: one runner for ALL git calls, with no read/write classification

**Context**: The first design had `run_git` accept only read-only verbs, so a
write could never be handed a "read-only" runner. Classifying by verb is
unsound anyway — `config --get` reads while `config k v` writes, `branch --show-current` reads while `branch -d` deletes — so the classification would
have to inspect sub-verbs and flags.

The premise behind needing it at all was that `GIT_OPTIONAL_LOCKS=0` might be
unsafe on a write. Tested rather than assumed, in a throwaway repo with the
variable exported: `add`, `commit`, `commit --only` and `config --local` all
succeeded, two commits were recorded and the worktree ended clean. Git declines
only OPTIONAL locks; a lock a command genuinely requires is still taken.

**Decision**: one `run_git` for every invocation, no classification. This
deletes the misclassification risk instead of mitigating it, and makes the Phase
3 guard trivially checkable — "no `subprocess.run(["git", …])` outside this
module" needs no verb knowledge at all.

**Date**: 2026-08-17

### Decision 3: the `git add` stays, gated on the file being untracked

**Context**: This plan was filed asserting the `git add` before
`git commit --only` "buys nothing". That was reasoning from the flag's
documentation, not from a test.

Tested: `git commit --only <path>` on an UNTRACKED path fails with
`error: pathspec '<path>' did not match any file(s) known to git`. On a tracked
modified path it succeeds. So the `git add` is load-bearing for exactly one case
— a CLAUDE.md that does not yet exist in git, which is what a first install has.

**Decision**: keep the call, gated on the porcelain status reporting the file as
untracked. The tracked case (every subsequent daemon start) then takes one lock
instead of two, and the untracked case keeps working. Deleting the call outright
would have broken CLAUDE.md creation on first install — a regression that no
existing test covered, since the fixtures all commit a CLAUDE.md first.

**Date**: 2026-08-17

### Decision 4: the guard is a test, not a `scripts/qa/` checker

**Context**: Every other repo-wide invariant here is a `scripts/qa/check_*.py`
wired into `run_all.sh` and `llm_qa.py`, so that was the default shape.

**Options Considered**:

1. A QA checker script, matching the existing family.
2. An integration test, matching `test_claude_md_guidance_coverage.py` and
   `test_repo_hygiene_check.py`.

**Decision**: Option 2. A checker is only as binding as its wiring: it must be
registered in two runners, and Plan 00244 shipped one whose verdict was published
under a key neither consumer read — 60 passed / 1 failed would have printed
PASSED. A test is binding by construction, runs in the QA suite and in CI with no
registration step, and cannot report a verdict nobody reads.

It carries its own control tests, for the same reason: `assert violations == []`
is exactly what a scanner that silently matches nothing also produces, so one
test proves the scanner detects the shape and another proves it ignores non-git
subprocesses.

**Date**: 2026-08-17

### Decision 5: declining the lock does not change what git reports

**Context**: The highest-severity risk on this plan was that declining the index
refresh might change `git status` OUTPUT. That would be worse than the bug: the
auto-commit's dirty check and the status line's icons both parse that output, so
a false "modified" would make the daemon commit CLAUDE.md on every single start.

Measured on a throwaway repo across the three shapes the daemon parses:

- stat-dirty but content-identical (exactly what the refresh exists to resolve):
  both report clean
- genuinely modified: both report ` M f.txt`
- `--porcelain=v2 --branch` with an untracked file: byte-identical

**Decision**: the risk is retired, not mitigated. Git still performs the
comparison in memory; `GIT_OPTIONAL_LOCKS=0` only stops it PERSISTING the
refreshed index. The cost is that the next command redoes the stat comparison,
which is the trade being made deliberately: a little repeated work in the daemon
in exchange for never taking a lock in the agent's tree.

**Date**: 2026-08-17

## Success Criteria

- [ ] A daemon start with a clean CLAUDE.md rewrites `.git/index` zero times
- [ ] A user prompt and a status refresh each rewrite `.git/index` zero times
- [ ] The auto-commit's four subprocess calls all carry a timeout
- [ ] Lock contention produces a WARNING naming git's stderr
- [ ] A guard fails if a new direct git invocation bypasses the bounded home
- [ ] `llm_qa.py all` green; daemon restarts RUNNING

## Risks & Mitigations

| Risk                                              | Impact | Probability | Mitigation                                                                     |
| ------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------------------------ |
| ~~`GIT_OPTIONAL_LOCKS=0` changes output~~         | —      | —           | RETIRED — measured byte-identical, see Decision 5                              |
| ~~A write verb is misclassified as read-only~~    | —      | —           | VOID — Decision 2 removed classification after verifying writes are unaffected |
| The migration is broad enough to regress a caller | Medium | Medium      | One caller per commit, tests per caller, daemon restart between                |
| The guard's allowlist becomes a dumping ground    | Medium | Medium      | Each entry carries its reason inline; the check prints them                    |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow log lives in JOURNAL/. -->

- Filed at the commit that adds this plan.
