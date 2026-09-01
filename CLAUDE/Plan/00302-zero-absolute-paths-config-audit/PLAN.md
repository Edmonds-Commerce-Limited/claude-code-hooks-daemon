# Plan 00302: zero absolute paths config audit

**Status**: Complete
**Created**: 2026-09-01
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Owner ruling: config carries ZERO absolute paths — a repository is mounted at
different places on different machines (container bind mount, developer home
directory, CI checkout), so an absolute path in committed config is correct
on exactly one of them and silently wrong everywhere else. Plans 00296/00300
already enforced this on `projects[].root`/`bin_dirs`, per-project `layout:`,
and `tdd_enforcement.options.test_path_map`'s `test_dir`. This plan sweeps
every REMAINING path-typed config surface in `config/models.py` and the
handler options that resolve a path at runtime, applying the same rule where
the surface's contract can bear a hard error, a fail-open degrade where the
surface is already advisory/best-effort, or a documented exemption where an
absolute path is a genuine, tested feature (external code loading, daemon
runtime state, a system binary override).

One shared implementation does the validation everywhere:
`utils/repo_relative_path.normalise_repo_relative_path` — pydantic-free so
both a `field_validator` (hard error) and a runtime resolver (catch
`ValueError`, log, degrade) can reuse it without duplicating the rule.
`config/models.py`'s existing `_repo_relative_path` (Plan 00296) now delegates
to it.

## Goals

- Audit every path-typed field in `config/models.py` plus the handler options
  identified in scope (plugins/loader.py, sensitive_content's
  `secret_word_list_path`, model_fallback_detector's `snapshot_dir`,
  `payload_capture.dir`, `documentation.trees`, `plan_workflow` paths).
- For each: enforce repo-relative-only (hard error), degrade-on-absolute
  (fail-open advisory surfaces), or document an explicit exemption with
  rationale.
- One shared validator implementation, reused by every call site.
- Upgrade-manifest entries (config-changes + truth-changes) for every
  newly-rejected/degraded shape, plus a `docs/guides/CONFIGURATION.md` update.

## Non-Goals

- Re-doing `projects[].root`/`bin_dirs`/`layout:` or `test_path_map.test_dir`
  (Plans 00296/00300 — already done).
- Editing `goal_injection`/`auto_continue_stop`/`recovery_cron_advisor`/the
  ccy supervisor — owned by a concurrently-running agent; any path option
  found there is recorded as a follow-on task instead (none was found on
  inspection of `config/models.py`'s surfaces).

## Audit Table

| Surface                                                                           | Path-typed?      | Decision          | Action                                                                                                                                                                  |
| --------------------------------------------------------------------------------- | ---------------- | ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `plan_workflow.directory`                                                         | yes              | Hard error        | `field_validator` added (shared `_repo_relative_path`)                                                                                                                  |
| `plan_workflow.workflow_docs`                                                     | yes              | Hard error        | same validator                                                                                                                                                          |
| `documentation.trees.agent` / `.human`                                            | yes (tree roots) | Hard error        | `field_validator` added                                                                                                                                                 |
| `handlers.pre_tool_use.sensitive_content.options.secret_word_list_path`           | yes              | Fail-open degrade | `resolve_secret_word_list_path` catches `ValueError`, logs, falls back to default                                                                                       |
| `daemon.payload_capture.dir`                                                      | yes              | Fail-open degrade | `resolve_capture_dir` catches `ValueError`, logs, falls back to default; relative values now explicitly joined to the untracked dir (previously ambiguous CWD-relative) |
| `handlers.session_start.model_fallback_detector.options.snapshot_dir`             | yes              | Fail-open degrade | `_resolve_snapshot_dir` catches `ValueError`, logs, falls back to default                                                                                               |
| `plugins.paths` / `plugins.plugins[].path`                                        | yes              | **Exempt**        | Loads external code that may live outside the repo; `tests/unit/test_plugin_loader.py` explicitly tests the absolute case. Documented in the field description.         |
| `project_handlers.path`                                                           | yes              | **Exempt**        | Same reasoning; `tests/unit/daemon/test_controller_project_handlers.py::test_load_project_handlers_uses_absolute_path_as_is` pins the absolute case.                    |
| `daemon.socket_path` / `pid_file_path`                                            | yes              | **Exempt**        | AF_UNIX runtime state, not a repo artefact; often needs `/tmp` to stay under the platform socket-path length limit.                                                     |
| `transport.relay_binary`                                                          | yes              | **Exempt**        | System-binary-style override, analogous to a `$PATH` executable — may legitimately live outside the repo.                                                               |
| `plan_workflow.qa.completed_dir` / `cancelled_dir`                                | no               | N/A               | Single-segment directory NAME nested inside the plan dir, not a standalone path — no portability issue.                                                                 |
| `daemon.exclude_paths` / per-handler `exclude_paths`                              | no               | N/A               | Gitignore-style GLOB patterns, not literal filesystem paths — `..`/absolute-prefix semantics don't apply the same way; left unchanged.                                  |
| `plugins/loader.py` internals                                                     | n/a              | No change         | Reads `PluginConfig.path`/`PluginsConfig.paths` as-is; absolute-path resolution logic already there is the exempted feature, not a bug.                                 |
| `model_fallback_detector`/`goal_injection`/`recovery_cron_advisor`/ccy supervisor | —                | Out of scope      | Owned by a concurrent agent; inspected `config/models.py` and found no additional path option belonging to those handlers beyond `snapshot_dir` (handled above).        |

## Tasks

### Phase 1: shared validator

- [x] ✅ **Task 1.1**: extract `config/models.py`'s `_repo_relative_path` body
  into a pydantic-free `utils/repo_relative_path.normalise_repo_relative_path`
  (TDD: `tests/unit/utils/test_repo_relative_path.py` first); `_repo_relative_path`
  delegates to it.

### Phase 2: hard-error surfaces

- [x] ✅ **Task 2.1**: `plan_workflow.directory`/`workflow_docs` — `field_validator`.
- [x] ✅ **Task 2.2**: `documentation.trees.agent`/`human` — `field_validator`.

### Phase 3: fail-open degrade surfaces

- [x] ✅ **Task 3.1**: `sensitive_content.secret_word_list_path` (`utils/secret_redaction.py`).
- [x] ✅ **Task 3.2**: `daemon.payload_capture.dir` (`daemon/payload_capture.py`).
- [x] ✅ **Task 3.3**: `model_fallback_detector.snapshot_dir`.

### Phase 4: documented exemptions

- [x] ✅ **Task 4.1**: `plugins.paths`/`plugins.plugins[].path`, `project_handlers.path`,
  `daemon.socket_path`/`pid_file_path`, `transport.relay_binary` — field
  description updated to state the exemption and cite the pinning test.

### Phase 5: manifests + docs

- [x] ✅ **Task 5.1**: `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.58.0.yaml` —
  entries for every newly-rejected/degraded shape.
- [x] ✅ **Task 5.2**: `CLAUDE/UPGRADES/UNRELEASED/truth-changes/v3.58.0.yaml` —
  summary entry.
- [x] ✅ **Task 5.3**: `docs/guides/CONFIGURATION.md` updated with a pointer.

### Phase 6: extension — `{REPO_ROOT}` canonical path notation

- [x] ✅ **Task 6.1**: owner ruling extension. `utils/repo_relative_path.py`:
  `REPO_ROOT_TOKEN` constant + `normalise_repo_relative_path` support (TDD
  first); `expand_repo_root_token(value, project_root)` shared helper for
  the two exempted absolute-allowed surfaces (`plugins/loader.py`,
  `daemon/controller.py` + `daemon/cli.py` project-handler call sites);
  `config/models.py` field descriptions updated; canonical notation defined
  in `CLAUDE/Code/WorkspaceResolution.md`, cross-linked + examples updated
  in `docs/guides/CONFIGURATION.md`; upgrade manifest entry added.

## Success Criteria

- [x] Every surface in the audit table has an explicit decision + action.
- [x] One shared validator implementation; no per-surface copies.
- [x] Full affected test suites green (`tests/unit/config/`, `tests/config/`,
  `tests/unit/utils/`, `tests/unit/daemon/`, plugin/project-handler suites,
  `tests/unit/handlers/session_start/test_model_fallback_detector.py`,
  `tests/unit/handlers/pre_tool_use/test_sensitive_content.py`) — 1711 passed.
- [x] `mypy --strict`, `black -l 100`, `ruff check` clean on every changed file.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00302-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Shared validator, hard-error surfaces, fail-open degrades, documented
  exemptions, and manifests delivered in one worktree branch.
