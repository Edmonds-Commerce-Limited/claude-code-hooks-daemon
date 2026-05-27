# Plan 00113: First-Class GitRepo Utility

**Status**: Complete
**Created**: 2026-05-27
**Owner**: Claude (Opus 4.7)
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Single-Threaded

## Overview

Plan 00112 introduced per-repo git-config access (resolve repo root, read/write
`hooksdaemon.latestPlanNumber`) but bolted it onto `handlers/utils/plan_numbering.py`:
the subprocess wrapper (`_git_output`) and resolver are private to that module,
and `read_plan_counter`/`write_plan_counter` hardcode the plan key. Meanwhile
`handlers/session_start/git_filemode_checker.py` independently hand-rolls the
same "read a `git config --local` value" pattern with its own subprocess block.

This plan extracts a **first-class, reusable `GitRepo` utility** that owns git
repository access, and migrates the two config consumers onto it. It is a pure
refactor — no behavioural change.

## Goals

- A single, bounded place for the git subprocess calls these features need:
  resolve the enclosing repo of a path, read a local config value, write a
  local config value.
- `plan_numbering` and `git_filemode_checker` delegate to it instead of each
  owning subprocess boilerplate.
- Open for extension (new git ops = new methods) without callers re-touching
  subprocess details.

## Non-Goals

- NOT migrating every git subprocess site in the codebase. `project_context`
  (`rev-parse`/`remote get-url`), `git_context_injector` (`status`),
  `git_branch` (`status`/`symbolic-ref`) keep their existing, working helpers.
  They could adopt `GitRepo` later if it earns more methods — out of scope here
  to avoid scope creep (YAGNI). The two *config* consumers are the concrete,
  present-day duplication this plan removes.
- No new git capability — same operations, same behaviour, one home.

## SOLID Rationale

- **Single Responsibility**: `GitRepo`'s only job is talking to git. Callers
  express intent (resolve / read / write config); they no longer own argv,
  timeouts, or the None-on-failure convention.
- **Open/Closed**: new git operations are added as methods on `GitRepo`, not by
  re-implementing `subprocess.run(["git", ...])` in each new caller.
- **Dependency Inversion**: handlers/utilities depend on `GitRepo`'s typed
  surface, not on subprocess internals. `plan_numbering` layers its
  plan-specific typed facade (`read_plan_counter` → int, the counter key) on
  top of the generic `read_config` → `str | None`.
- **Interface Segregation**: `GitRepo` exposes only the small, cohesive set of
  operations consumers actually use (resolve, read_config, write_config).

## Design

`src/claude_code_hooks_daemon/utils/git_repo.py`:

```python
@dataclass(frozen=True)
class GitRepo:
    root: Path

    @classmethod
    def resolve_for(cls, path: Path) -> "GitRepo | None":
        """Nearest enclosing repo of path (which need not exist yet)."""

    def read_config(self, key: str) -> str | None:
        """git config --local --get <key>, or None when unset/unavailable."""

    def write_config(self, key: str, value: str) -> None:
        """git config --local <key> <value>. FAIL FAST: raises on git error."""
```

- Private `_git_output(cwd, *args) -> str | None`: one bounded
  (`Timeout.GIT_CONTEXT`) subprocess wrapper; returns None on OSError /
  SubprocessError / non-zero exit / empty stdout. This None is
  feature-detection ("not a repo" / "key absent" IS the answer), the same
  explicitly-non-fatal contract as `project_context._get_git_toplevel`.
- Reads are non-fatal (None); writes are FAIL FAST (raise) — callers that need
  resilience wrap the write (e.g. `validate_plan_number._record_allocation`).

`plan_numbering.py` after migration:

- Delete its private `_git_output`.
- `resolve_plan_repo_root(target)` → `GitRepo.resolve_for(target).root or None`.
- `read_plan_counter(repo_root)` → `GitRepo(repo_root).read_config(KEY)` + int parse.
- `write_plan_counter(repo_root, value)` → `GitRepo(repo_root).write_config(KEY, str(value))`.
- Counter key constant + int semantics stay here (plan-specific).

`git_filemode_checker._get_filemode_setting`:

- Replace the subprocess block with `GitRepo(root).read_config("core.fileMode")`,
  keeping its existing ProjectContext-root / cwd-fallback selection.

## Tasks

### Phase 1: Plan

- [x] **Task 1.1**: Confirm the two config consumers + scope (done in review)
- [x] **Task 1.2**: Author this PLAN.md

### Phase 2: TDD GitRepo

- [x] **Task 2.1**: RED — `tests/unit/utils/test_git_repo.py`: resolve_for
  (inside repo, nested/vendor repo, non-git, not-yet-existing target),
  read_config (absent → None, roundtrip, branch-independence, non-int passthrough),
  write_config (roundtrip, overwrite, raises on bad repo), git-unavailable → None
- [x] **Task 2.2**: GREEN — implement `utils/git_repo.py`
- [x] **Task 2.3**: 100% coverage on the new module

### Phase 3: Migrate consumers

- [x] **Task 3.1**: `plan_numbering` delegates to `GitRepo`; delete its `_git_output`
- [x] **Task 3.2**: `git_filemode_checker._get_filemode_setting` uses `GitRepo.read_config`
- [x] **Task 3.3**: Update `error_hiding_exclusions.json` (move `_git_output` entry to
  `utils/git_repo.py`; drop entries that no longer apply)
- [x] **Task 3.4**: Keep all existing tests green (update mocks/patch targets)

### Phase 4: QA + close

- [x] **Task 4.1**: `./scripts/qa/llm_qa.py all` — 13/13, coverage ≥ 95%
- [x] **Task 4.2**: Restart daemon, verify RUNNING
- [x] **Task 4.3**: Mark complete with commit hashes, archive to `Completed/`, update README

## Success Criteria

- [x] `GitRepo` is the single home for resolve / read_config / write_config.
- [x] `plan_numbering` and `git_filemode_checker` both delegate to it; neither
  hand-rolls a `git config` subprocess any more.
- [x] No behavioural change — all existing plan-number and filemode tests pass.
- [x] QA 13/13, coverage ≥ 95%, daemon restarts RUNNING.

## Risks & Mitigations

| Risk                                                   | Impact | Probability | Mitigation                                                              |
| ------------------------------------------------------ | ------ | ----------- | ----------------------------------------------------------------------- |
| Behaviour drift in filemode read (`--get` vs bare key) | Low    | Low         | Equivalent for single-valued keys; covered by existing filemode tests   |
| Mock/patch targets in existing tests break             | Low    | Med         | Update patch targets to the new module; run full suite                  |
| Over-extraction (scope creep)                          | Low    | Low         | Scoped to the two config consumers only; other git sites explicitly out |

## Notes & Updates

### 2026-05-27

- Plan created off the back of Plan 00112. User asked whether the git-config
  access was a first-class service or coupled to plan numbering — it was
  coupled; this extracts it properly (SOLID) with the two present-day consumers
  as the justification (not speculative reuse).
- **Delivered** (not yet released — release deferred by user):
  - `59b06f1` — plan document
  - `9acf120` — `utils/git_repo.py` (`GitRepo` value object: `resolve_for`,
    `read_config`, `write_config`; private `_git_output` bounded wrapper);
    migrated `plan_numbering` (deleted its `_git_output`; the three delegators
    now call `GitRepo`) and `git_filemode_checker._get_filemode_setting`;
    relocated the `_git_output` error-hiding exclusion, dropped the obsolete
    `git_filemode` one
- 14 new `GitRepo` tests (100% module coverage); 283 consumer tests green; QA
  13/13, coverage 95.1%; daemon restarted RUNNING with no import errors. Pure
  refactor — no behavioural change.
