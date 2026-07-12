# Plan 00153: plan qa extensible root files

**Status**: Complete
**Created**: 2026-07-12
**Owner**: joseph
**Priority**: Low
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

The `structure-archive-dirs` plan-QA check flags any non-plan file at the plan
root that is not one of a hardcoded set (`README.md`, `CLAUDE.md`, `mkplan.bash`,
`_TEMPLATE_.md`). Client projects that place a legitimate, correctly-named shared
file at the plan root — e.g. a sourced shell library `_planlib.bash` used by plan
orchestrator scripts — get a permanent, unsuppressable advisory finding on every
session start and after every commit, with no config knob to allowlist it.

This plan adds an **additive** `plan_workflow.qa.extra_root_files` config field,
mirroring the existing `completed_dir` / `legacy_plan_allowlist` knobs. It layers
on top of the hardcoded defaults, so an empty list (the default) is zero
behaviour change. See `untracked/hooks-daemon-plan-scripts.md` (option A) for the
originating upstream request.

## Goals

- Add `extra_root_files: list[str]` to `PlanWorkflowQaConfig` (`config/models.py`).
- Surface it on the `QaPolicy` protocol and thread it through `CheckContext`.
- Union it with `_EXPECTED_ROOT_FILES` inside `PlanTree.scan()` when classifying
  stray root files.
- Default empty → identical behaviour for every existing install.
- Document the knob in the handler reference.

## Non-Goals

- No glob support (exact filenames are enough for the request).
- No `_`-prefix auto-allow (option B) or lib-subdir (option C) — keep the surface
  minimal and explicit.
- No change to any other plan-QA check.

## Context & Background

- Accepted set: `plan_qa/model.py::_EXPECTED_ROOT_FILES`, consumed in
  `PlanTree.scan()`.
- Finding emitted in `plan_qa/checks/structure_archive_dirs.py` (Level.ADVISE).
- Policy threading: `plan_qa/context.py::QaPolicy` (protocol) →
  `CheckContext` builders; config model in `config/models.py`.

## Tasks

### Phase 1: config model

- [x] ✅ **Task 1.1**: RED — test `PlanWorkflowQaConfig` accepts/defaults
  `extra_root_files` (default `[]`).
- [x] ✅ **Task 1.2**: GREEN — add the field to `config/models.py`.

### Phase 2: policy + scan threading

- [x] ✅ **Task 2.1**: RED — tests: `PlanTree.scan(..., extra_root_files=("_planlib.bash",))`
  does NOT flag that file as stray; still flags a genuinely stray file; default
  (no extra) unchanged. Plus `QaPolicy`/`CheckContext` carry the field.
- [x] ✅ **Task 2.2**: GREEN — add `extra_root_files` to the `QaPolicy` protocol,
  thread it through the `CheckContext` builders in `plan_qa/context.py`, and union
  it into the stray-file classification in `PlanTree.scan()`.

### Phase 3: docs, QA, dogfood

- [x] ✅ **Task 3.1**: Document `extra_root_files` in
  `docs/guides/HANDLER_REFERENCE.md`; staged config-changes manifest
  `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.37.0.yaml`.
- [ ] 🔄 **Task 3.2**: Run full QA (`./scripts/qa/llm_qa.py all`).
- [x] ✅ **Task 3.3**: Restart daemon, verify RUNNING; `plan-qa --sweep` clean.

## Success Criteria

- [x] A configured `extra_root_files` entry suppresses the stray-file advisory for
  that exact filename only.
- [x] Empty/absent config = byte-identical behaviour to today.
- [x] All plan-QA tests pass; coverage ≥ 95%; full QA passes; daemon RUNNING.

## Notes & Updates

### 2026-07-12

- Plan scaffolded from `untracked/hooks-daemon-plan-scripts.md` (option A).
- Delivered in commit `df9262b`. Full QA 13/13, coverage 95.5%; daemon restart
  verified RUNNING; `plan-qa --sweep` clean.
