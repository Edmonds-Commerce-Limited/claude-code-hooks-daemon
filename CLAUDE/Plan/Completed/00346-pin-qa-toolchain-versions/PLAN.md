# Plan 00346: the QA venv ignores uv.lock

**Status**: Complete
**Created**: 2026-09-08
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

This repository already solved dependency reproducibility: `uv.lock` is
committed, CI-gates itself via `uv lock --check` in
`scripts/qa/run_dependency_check.sh`, and `CONTRIBUTING.md` describes it as one
of the files "the same ones `scripts/qa/` uses".

`scripts/qa/` does not use it. `scripts/qa/run_tests.sh` sources
`scripts/venv-include.bash`, calls `ensure_venv`, then runs `venv_tool pytest`;
`install_deps` provisions that venv with `pip install -e ".[dev]"`, which never
consults the lockfile and resolves `pyproject.toml`'s lower bounds to whatever
is newest on PyPI that day. So the toolchain that decides whether this project
passes is not the toolchain the lockfile records.

The consequence is measured, not predicted: two venvs coexist in this checkout
with two different toolchains, and the one that runs the tests is the one that
is off-lock — by a whole major version in mypy's case.

This is not a new class of bug here. `.pre-commit-config.yaml`'s header
documents the identical failure: pinning tools in pre-commit mirror repos gave
the project "a SECOND version source that drifts from `uv.lock`", it drifted
for "two years of silent rot", and the fix was to delete the second source
rather than to keep it in sync. That fix was applied to pre-commit. The QA venv
path still has the second source.

The formatter is the sharpest instance, because `scripts/qa/run_format_check.sh`
**auto-fixes**. A black release that wraps differently does not fail the build;
it rewrites the tree and reports success, so it arrives as hundreds of unrelated
modified files in someone's next diff.

## Goals

- The tools that decide whether QA passes are the versions `uv.lock` records.
- One version source, not two — matching the resolution `.pre-commit-config.yaml`
  already reached and documented.
- `CONTRIBUTING.md`'s claim about what `scripts/qa/` uses becomes true.

## Non-Goals

- Upgrading or downgrading any tool. Both toolchains pass QA today; this is
  about which one is authoritative, not about moving versions.
- Pinning runtime dependencies, or changing `pyproject.toml`'s bounds for their
  own sake. Bounds express compatibility; the lockfile expresses reproducibility,
  and it is the lockfile that is being bypassed.
- Giving client projects the QA toolchain. `scripts/install/venv.sh` has two
  provisioning functions: `create_venv_at_path` runs `uv sync --project` and
  `install_package_editable` runs `uv pip install -e <dir>`. Neither passes
  `--all-extras`, so no client project receives these tools. (An earlier
  revision of this line cited only the second function and drew the right
  conclusion from the wrong premise. The lockfile-integrity gap the first one
  turned out to have is Task 2.3, which is in scope.)

## Evidence

`uv.lock` versus the two venvs in this checkout. `.venv` matches the lock
exactly; the workspace venv — the one `venv_tool` selects and therefore the one
that ran the 25/25 QA pass — does not.

| Tool    | `uv.lock` | `.venv` | workspace venv (runs QA) |
| ------- | --------- | ------- | ------------------------ |
| black   | 26.3.1    | 26.3.1  | **26.5.1**               |
| mypy    | 1.20.2    | 1.20.2  | **2.3.0**                |
| pytest  | 9.0.3     | 9.0.3   | **9.1.1**                |
| ruff    | 0.15.11   | 0.15.11 | **0.15.22**              |
| bandit  | 1.9.4     | 1.9.4   | 1.9.4                    |
| semgrep | 1.172.0   | 1.172.0 | 1.172.0                  |

Two aggravating details:

- `run_tests.sh:25` auto-provisions on a missing `pytest`, so the off-lock
  toolchain installs itself silently, without anyone choosing it.
- `pyproject.toml:192` records ruff 0.14 newly enforcing TC002/TC003 across 30
  findings in 24 files — a toolchain change that arrived unbidden and was
  answered with ignores. That is what a bypassed lock costs when it bites.

## Tasks

### Phase 1: Make the QA venv obey the lock

- [x] ✅ **Task 1.1**: Change `install_deps` in `scripts/venv-include.bash` to
  install from `uv.lock` rather than resolving `pyproject.toml`. Establish
  what happens when `uv` is absent — degrade loudly, never silently back to
  `pip install -e ".[dev]"`, because a silent fallback reinstates exactly
  the drift this removes.
- [x] ✅ **Task 1.2**: Decide what happens to the existing off-lock workspace
  venv. It cannot simply be left: it is what `venv_tool` selects today, so
  until it is rebuilt or invalidated the change has no effect.

### Phase 2: Make the drift visible if it returns

- [x] ✅ **Task 2.1**: Add a check that the venv running QA matches the lock.
  `uv lock --check` proves the lock agrees with `pyproject.toml`; nothing
  proves the INSTALLED tools agree with the lock, which is the gap that let
  this run for as long as it has.
- [x] ✅ **Task 2.2**: `.github/workflows/qa.yml` provisioned CI with
  `pip install -e ".[dev]"`, so the workflow gating merges was off-lock on
  every run across three interpreters. (This task was first written claiming
  the Task 2.1 gate would fail CI and so had to land alongside it. That was
  wrong: CI invokes `black`/`ruff`/`mypy`/`pytest`/`bandit`/`deptry` directly
  and never runs a `scripts/qa/*.sh` wrapper, so the gate does not execute
  there at all. The real relationship is worse than a coupling — CI both
  provisions off-lock AND bypasses the only place a gate could catch it.)
- [x] ✅ **Task 2.3**: `create_venv_at_path` in `scripts/install/venv.sh` runs
  `uv sync` without `--frozen`, so a checkout whose `pyproject.toml` and
  `uv.lock` disagree gets its lockfile rewritten and re-resolved against PyPI
  instead of an error. All three sync call sites now pass it.
- [x] ✅ **Task 2.4**: Three `venv.sh` test files put their stub directory on
  `PATH` *before* sourcing the script, which prepends its own tool directory
  and shadows them — so the real `uv`, `stat` and `uname` ran and the
  filesystem/link-mode assertions proved nothing. Found because Task 2.3's
  `--frozen` made the real `uv` fail where the stub would not have.

### Phase 3: Correct the documentation

- [x] ✅ **Task 3.1**: `CONTRIBUTING.md:73` states that `uv.lock` and
  `pyproject.toml` are "the same ones `scripts/qa/` uses". Make it true, or
  make it accurate — but not before Phase 1, so the doc describes the fixed
  behaviour rather than a second aspiration. (Phase 1 made it true. The same
  file's own **setup instructions** were a live instance of the bypass,
  telling every contributor to run `pip install -e ".[dev]"`, and listing
  "pip and venv" as the prerequisites — so those are rewritten too.)

## Success Criteria

- [x] The tools that run QA are the versions `uv.lock` records, verified by
  comparing an actual venv against the lock rather than by assertion.
  `assert_venv_matches_lock` runs `uv sync --frozen --all-extras --check`
  against the resolved venv on every QA run.
- [x] A toolchain that drifts from the lock fails a check instead of passing
  quietly — and the check is tested against a venv that genuinely drifts, not
  only against one that matches.
- [x] No provisioning path installs QA tools without consulting the lock:
  `install_deps` (T1.1), both CI jobs (T2.2) and `create_venv_at_path` (T2.3)
  all sync `--frozen`. `install_package_editable` still runs
  `uv pip install -e <dir>`, which reads no lock — it installs the daemon
  package alone with no `dev` extra, so it provisions no QA tools.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00346-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- **Phase 3** — `CONTRIBUTING.md` now documents the uv/lockfile setup, and its
  claim about what `scripts/qa/` uses is true.
- **Phase 2** — `d3978800` (T2.1 `assert_venv_matches_lock` gates every QA run
  on the INSTALLED packages matching the lock; T2.2 both CI jobs provision with
  `uv sync --frozen --all-extras`) and `f8e852a1` (T2.3 `--frozen` on all three
  `create_venv_at_path` sync branches; T2.4 three test files whose stubs were
  shadowed by a PATH export placed before the script was sourced, so the real
  `uv`/`stat`/`uname` ran and the assertions proved nothing).
- **Phase 1 complete** — `2de920a3` (`install_deps` syncs from `uv.lock`,
  `--frozen`, loud failure absent `uv`) and `0de54287` (an empty `VENV_DIR`
  built a venv in the caller's cwd and reported success; found while writing
  the Phase 1 RED). The workspace venv is synced and the whole suite passes on
  the locked toolchain: 25/25, 18507 tests, 95.2% coverage.
