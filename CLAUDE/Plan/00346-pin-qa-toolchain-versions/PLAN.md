# Plan 00346: the QA venv ignores uv.lock

**Status**: Not Started
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
- Changing the client install path. `scripts/install/venv.sh` runs
  `uv pip install -e <dir>` with no `[dev]` extra, so no client project receives
  these tools.

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

- [ ] ⬜ **Task 1.1**: Change `install_deps` in `scripts/venv-include.bash` to
  install from `uv.lock` rather than resolving `pyproject.toml`. Establish
  what happens when `uv` is absent — degrade loudly, never silently back to
  `pip install -e ".[dev]"`, because a silent fallback reinstates exactly
  the drift this removes.
- [ ] ⬜ **Task 1.2**: Decide what happens to the existing off-lock workspace
  venv. It cannot simply be left: it is what `venv_tool` selects today, so
  until it is rebuilt or invalidated the change has no effect.

### Phase 2: Make the drift visible if it returns

- [ ] ⬜ **Task 2.1**: Add a check that the venv running QA matches the lock.
  `uv lock --check` proves the lock agrees with `pyproject.toml`; nothing
  proves the INSTALLED tools agree with the lock, which is the gap that let
  this run for as long as it has.

### Phase 3: Correct the documentation

- [ ] ⬜ **Task 3.1**: `CONTRIBUTING.md:73` states that `uv.lock` and
  `pyproject.toml` are "the same ones `scripts/qa/` uses". Make it true, or
  make it accurate — but not before Phase 1, so the doc describes the fixed
  behaviour rather than a second aspiration.

## Success Criteria

- [ ] The tools that run QA are the versions `uv.lock` records, verified by
  comparing an actual venv against the lock rather than by assertion.
- [ ] A toolchain that drifts from the lock fails a check instead of passing
  quietly.
- [ ] No provisioning path installs QA tools without consulting the lock.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00346-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Not yet started.
