# Plan 00112: Git-Anchored Plan Numbering

**Status**: Complete
**Created**: 2026-05-27
**Owner**: Claude (Opus 4.7)
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Single-Threaded (one developer, tightly-coupled handler changes)

## Overview

The plan-workflow handlers compute the "next plan number" by scanning the
filesystem (`CLAUDE/Plan/` plus organisational subfolders like `Completed/`)
for the highest `NNNNN-` prefix. That filesystem scan has two failure modes
in real use:

1. **Branch traversal**: the highest plan number depends on which branch is
   checked out. A plan folder created on branch A is invisible from branch B,
   so the scan on branch B re-issues a number already used on A. When the
   branches later merge, two different plans collide on the same number. There
   is no way to know the true high-water mark without traversing every branch.

2. **Vendor / nested-repo interception**: when working inside a first-party
   vendor library that has its **own** git repo and its **own** `CLAUDE/Plan/`,
   the daemon still resolves the plan root from the **outer** project
   (`ProjectContext.project_root()`, fixed once at daemon startup). The
   handlers compute a number against the wrong repo's plans and force an
   incorrect number for the vendor lib's plan.

Both stem from the same root cause: the "latest plan number" is derived from
branch-and-location-dependent filesystem state, when it should be derived from
a stable, per-repository record.

## Goals

- Persist the latest allocated plan number as a **per-repository** record in
  that repo's git metadata (`git config --local`), so it is stable across
  branch switches.
- Resolve the relevant repo from the **target file's location** (nearest
  enclosing git repo), so a plan created under a vendor subdir uses that
  subdir's own repo, counter, and `CLAUDE/Plan/`.
- Trust the stored counter as the authoritative source for the next number;
  only fall back to a filesystem scan to **bootstrap** the counter the first
  time (or self-heal if it is ever deleted).
- Consolidate the duplicate plan-scan logic (`validate_plan_number` has its own
  copy) onto a single canonical helper (DRY).

## Non-Goals

- No change to plan-folder naming convention (`NNNNN-description/`, 5-digit).
- No committing of the counter into version control — it lives in `.git/config`
  precisely because it must NOT be branch-tracked.
- No cross-clone synchronisation. The counter is local to a working copy. Two
  independent clones each keep their own high-water mark; that is acceptable
  and out of scope (git merge of plan folders is a human concern).
- No new handler. This reworks the internals of the three existing
  plan-number call sites.

## Context & Background

Three handlers currently compute plan numbers, all against the global
project root (`self._workspace_root / self._track_plans_in_project`):

| Handler                 | File                                             | Call site                                                     | Role                                                                  |
| ----------------------- | ------------------------------------------------ | ------------------------------------------------------------- | --------------------------------------------------------------------- |
| `plan_number_helper`    | `handlers/pre_tool_use/plan_number_helper.py`    | `:140` `get_next_plan_number(plan_base)`                      | Blocks broken discovery commands, injects correct next number         |
| `validate_plan_number`  | `handlers/pre_tool_use/validate_plan_number.py`  | `:138` `_get_highest_plan_number()` (own duplicate at `:183`) | Advisory warning when a created plan's number is not sequential       |
| `markdown_organization` | `handlers/pre_tool_use/markdown_organization.py` | `:503` `get_next_plan_number(plan_base)`                      | Redirects Claude Code planning-mode flat writes into numbered folders |

The single scan primitive is `handlers/utils/plan_numbering.py::get_next_plan_number`
(scans active + non-numbered organisational subfolders, returns `max + 1` as a
5-digit string). `validate_plan_number._get_highest_plan_number` is a parallel
re-implementation of the same logic — a DRY violation folded in by this plan.

Git facts confirmed in this repo:

- `git config --local --get hooksdaemon.latestPlanNumber` exits non-zero (clean
  "absent" signal) when unset.
- `git -C <subdir> rev-parse --show-toplevel` resolves the nearest enclosing
  repo — so a vendor lib's own `.git` is reachable from its path.
- `git config --local` is stored in the shared `.git/config`, which is NOT
  branch-tracked and is shared across worktrees of the same repo — exactly the
  stability property required.

## Counter Semantics (the core design)

Counter key: `hooksdaemon.latestPlanNumber` in the target repo's `--local`
git config. Value = **highest plan number ever allocated in this repo**
(a monotonic high-water mark).

**Read path** (answering "what is the next number?"):

```
C = read_plan_counter(repo)
if C is present:
    next = C + 1                      # TRUST the counter (authoritative)
else:                                  # bootstrap: counter never seeded
    scan_max = filesystem scan of repo's CLAUDE/Plan (active + Completed/)
    next = scan_max + 1
    write_plan_counter(repo, scan_max) # seed the high-water mark
return zero-pad(next, 5)
```

**Write path** (on a real plan-folder creation event):

```
record_plan_allocation(repo, N):
    C = read_plan_counter(repo) or 0
    write_plan_counter(repo, max(C, N))
```

The read path purely trusts the counter (no scan when present), which is what
makes it immune to the branch-traversal and vendor problems. The write path
advances the high-water mark to whatever was actually created, so it
**self-heals** if a higher-numbered plan ever appears (manual creation, counter
deletion) without ever lowering the next number — preserving trust in the
counter.

**Repo resolution**: every call resolves the repo from the **target path**
(the file/dir being written or `mkdir`-ed), via
`git -C <dirname(target)> rev-parse --show-toplevel`. If the target is not
inside any git repo, fall back to `ProjectContext.project_root()` so behaviour
in non-git contexts (and existing tests) is unchanged. The plan subfolder name
(`CLAUDE/Plan`, from `_track_plans_in_project`) is joined onto the resolved repo
root.

### Decision 1: Trust the counter on read (do not reconcile with a scan)

**Context**: Whether the read path should be `counter + 1` (trust) or
`max(counter, scan) + 1` (reconcile).

**Decision**: Trust the counter (`counter + 1`) when present. Per the user:
if the counter is not authoritative, the exercise is pointless — the branch and
sub-repo problems both re-enter through the scan. The scan is used ONLY to
bootstrap an absent counter. Drift (filesystem ahead of counter) is handled on
the **write** path via the `max(counter, N)` high-water mark, not by
re-scanning on read. Because the counter lives in `.git/config` (one per repo,
shared across branches/worktrees), every allocation goes through the same
counter, so the drift case effectively only arises from counter deletion or
out-of-band manual folder creation — both healed by the write path or
re-bootstrap.

**Date**: 2026-05-27

### Decision 2: `git config --local`, not a file in `.git/`

**Context**: User was indifferent ("git config commands or write files in the
.git folder, don't mind").

**Decision**: Use `git config --local hooksdaemon.latestPlanNumber`. It is
git-native, queryable from any subdir via `git -C`, automatically shared across
worktrees of one repo, and survives branch switches. A bespoke file in the
gitdir would require manual handling of the worktree `.git`-file indirection
(`--git-common-dir`) for no benefit.

**Date**: 2026-05-27

### Decision 3: Nearest enclosing repo of the target (vendor support)

**Context**: Confirmed with the user.

**Decision**: Resolve the repo per-call from the target path, not from the
daemon's global `ProjectContext.project_root()`. Fixes vendor-subdir
interception. Falls back to the global project root when the target is not in a
git repo (keeps non-git tests/behaviour stable).

**Date**: 2026-05-27

## Tasks

### Phase 1: Plan (this document)

- [x] **Task 1.1**: Map existing call sites and scan primitive
- [x] **Task 1.2**: Confirm git config + `git -C` resolution behaviour
- [x] **Task 1.3**: Confirm counter semantics with user (trust counter; nearest repo)
- [x] **Task 1.4**: Author this PLAN.md

### Phase 2: TDD canonical git-anchored helpers

- [x] **Task 2.1**: RED — tests in `tests/unit/handlers/utils/test_plan_numbering.py` for:
  - `resolve_plan_repo_root(target)` → toplevel of nearest repo; `None` when not in a repo
  - `read_plan_counter(repo)` → int when set, `None` when absent
  - `write_plan_counter(repo, value)` → round-trips via `read_plan_counter`
  - `next_plan_number_for_target(...)`: present-counter → `counter+1`; absent → scan+seed
  - `record_plan_allocation(...)`: `max(counter, N)`; never lowers
  - vendor scenario: a nested repo gets its own counter independent of the outer repo
- [x] **Task 2.2**: GREEN — implement the helpers; keep `get_next_plan_number` as the
  pure scan primitive used for bootstrap
- [x] **Task 2.3**: REFACTOR + 95% coverage on the new code

### Phase 3: Wire handlers + consolidate duplicate

- [x] **Task 3.1**: `plan_number_helper` — resolve repo from the bash command's plan path
  (fall back to global root), read counter+1 / bootstrap; update tests
- [x] **Task 3.2**: `validate_plan_number` — resolve repo from `file_path`/mkdir target;
  delete `_get_highest_plan_number` duplicate, use the shared scan for bootstrap;
  call `record_plan_allocation` on real creation; update tests
- [x] **Task 3.3**: `markdown_organization` — `_handle_plan_write` resolves repo from the
  redirect target, uses git-anchored next number; update tests
- [x] **Task 3.4**: Verify all three honour the non-git fallback to project root

### Phase 4: QA + dogfood + close

- [x] **Task 4.1**: `./scripts/qa/llm_qa.py all` — 13/13, coverage ≥ 95%
- [x] **Task 4.2**: Restart daemon, verify RUNNING; check logs for errors
- [x] **Task 4.3**: Dogfood — broken plan-discovery command returns git-anchored number;
  confirm `hooksdaemon.latestPlanNumber` written to `.git/config`
- [x] **Task 4.4**: Mark PLAN.md complete with delivery commit hashes; move to `Completed/`

## Dependencies

- None blocking. Independent of Plan 00110 (just completed).

## Success Criteria

- [x] Next plan number is read from `git config --local hooksdaemon.latestPlanNumber`
  when present (trusted, `counter + 1`), independent of current branch.
- [x] When the counter is absent, it is bootstrapped from a filesystem scan and seeded.
- [x] On real plan creation, the counter advances to `max(counter, N)` (self-heal, never lowers).
- [x] A plan created under a nested git repo (vendor lib) uses THAT repo's counter and
  `CLAUDE/Plan/`, not the outer project's.
- [x] Non-git targets fall back to `ProjectContext.project_root()` (no behaviour change).
- [x] `validate_plan_number`'s duplicate scan is removed; one canonical scan primitive remains.
- [x] All QA checks pass (13/13), coverage ≥ 95%, daemon restarts RUNNING.

## Risks & Mitigations

| Risk                                                               | Impact | Probability | Mitigation                                                          |
| ------------------------------------------------------------------ | ------ | ----------- | ------------------------------------------------------------------- |
| Counter drifts below filesystem (manual folder / counter deletion) | Med    | Low         | Write-path high-water mark + re-bootstrap on absent counter         |
| `git` unavailable / target not in a repo                           | Low    | Low         | Fall back to `ProjectContext.project_root()`                        |
| Subprocess latency on hot path                                     | Low    | Med         | Single `git` call per event; bounded timeout via `Timeout` constant |
| Existing tests assume global-root scan                             | Med    | Med         | Non-git fallback preserves old behaviour; update tests per phase    |

## Notes & Updates

### 2026-05-27

- Plan created. Design confirmed with user: trust the git-stored counter on read
  (scan only to bootstrap); resolve the nearest enclosing repo of the target path
  for vendor-subdir support.
- **Delivered** (not yet released — release deferred by user):
  - `2da5013` — plan document
  - `69fbb21` — Phase 2: git-anchored counter helpers in `plan_numbering.py`
    (`resolve_plan_repo_root`, `read`/`write_plan_counter`,
    `next_plan_number_for_target`, `record_plan_allocation`; `highest_plan_number`
    extracted as the shared scan primitive)
  - `8853f1e` — Phase 3: wired `plan_number_helper`, `validate_plan_number`,
    `markdown_organization` to the git-anchored functions; removed the duplicate
    scan in `validate_plan_number`
  - `87f21db` — Phase 4: QA fixes (Timeout constants in tests, justified
    error_hiding exclusions)
- QA 13/13 green, coverage 95.1%. Daemon restarted RUNNING. Dogfood: the live
  daemon answered "next plan 00113" and seeded `hooksdaemon.latestPlanNumber=112`
  into `.git/config` — branch-stable, git-anchored numbering confirmed end-to-end.
