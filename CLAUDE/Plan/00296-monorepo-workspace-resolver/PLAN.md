# Plan 00296: monorepo workspace resolver

**Status**: Not Started
**Created**: 2026-08-31
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A client field report ([REPORT-monorepo-client.md](REPORT-monorepo-client.md))
documents that handlers assume a single-project repository: one git root, one
manifest at that root, one tool bin directory. In a repository holding several
sibling workspaces (each with its own manifest, lockfile and
`node_modules/.bin` / `vendor/bin`), the failure mode is silent degradation —
a handler resolves nothing at the root, concludes the project "doesn't have"
that toolchain, and quietly stops enforcing.

The codebase currently holds six mutually incompatible partial notions of
"which sub-tree am I in" (`ProjectContext.project_root()`,
`markdown_organization`'s `monorepo_subproject_patterns` + implicit
vendor/node_modules monorepos, `validate_eslint_on_write`'s testing-only
`workspace_root` scalar, `tdd_enforcement`'s everything-before-`src/`
inference, `lint_on_edit`'s `_MODULE_ROOT_MARKERS`, and the commit gates'
`_is_foreign_repo()`). This plan introduces ONE shared resolver and routes
the affected handlers through it.

## Goals

- A shared `Workspace.for_path(file_path)` resolver: walk up from the file to
  the nearest recognised manifest (`package.json`, `composer.json`,
  `pyproject.toml`, `go.mod`, `Cargo.toml`, ...), stopping at the git root;
  returns root, kind, manifest and tool bin dirs; falls back to the git root
  so single-root repositories see no behaviour change and need no config.
- `npm_command` / `has_llm_commands_in_package_json()`: mode decided per
  workspace, evaluated per invocation rather than once at handler
  construction.
- `lint_on_edit`: run the linter from the edited file's workspace root and
  search the workspace's bin dirs (`node_modules/.bin`, `vendor/bin`) before
  the daemon venv and `PATH`.
- `validate_eslint_on_write`: derive the workspace per edited file; keep the
  `workspace_root` constructor arg as the documented test seam.
- `tdd_enforcement`: resolve a relative `test_path_map` `test_dir` against
  the file's workspace, falling back to project root for compatibility;
  remove the hardcoded `/workspace` default workspace fallback.
- `markdown_organization`: `monorepo_subproject_patterns` becomes a manual
  override of the automatic resolution, not the only way to get one.
- Degradation is surfaced: when a handler's enforcement downgrades (no
  manifest found, linter unresolved), the fact appears in `handlers` /
  `check` output instead of only in the handler's source.

## Non-Goals

- Requiring (or recommending) a root-level manifest in client monorepos —
  the report is explicit that a manifest existing purely to satisfy tooling
  is a bodge, and resolution must derive the workspace from the edited
  file's own path.
- Changing `lint_on_edit`'s return-None-rather-than-guess fallback: a
  missing tool must never block anyone. The defect is the search path, not
  the fallback behaviour.
- Unifying `_is_foreign_repo()` (nested git repositories) into the
  workspace resolver — that is a different concern (a *different* git
  root), listed in the report only to show the count of mechanisms.
- Fixing the two secondary `npm_command` observations (piped-command branch
  denying regardless of mode; `NPX_TOOL_SUGGESTIONS` coverage holes) beyond
  documenting them — they are independent of monorepo support.

## Tasks

### Phase 1: Shared resolver

- [ ] ⬜ **Task 1.1**: TDD `Workspace.for_path()` in core (manifest walk-up,
  git-root stop, git-root fallback, kind + bin_dirs per ecosystem).
- [ ] ⬜ **Task 1.2**: Config surface review — decide whether any override
  knob is needed at all given automatic resolution, and document the
  resolver in the agent tree.

### Phase 2: Route handlers through it

- [ ] ⬜ **Task 2.1**: `has_llm_commands_in_package_json()` takes the
  workspace root; `npm_command` evaluates per invocation.
- [ ] ⬜ **Task 2.2**: `lint_on_edit` working dir + executable resolution
  via workspace bin dirs.
- [ ] ⬜ **Task 2.3**: `validate_eslint_on_write` per-file workspace.
- [ ] ⬜ **Task 2.4**: `tdd_enforcement` workspace-relative `test_path_map`
  and removal of the hardcoded `/workspace` fallback.
- [ ] ⬜ **Task 2.5**: `markdown_organization` automatic resolution with
  `monorepo_subproject_patterns` as override.

### Phase 3: Degradation visibility

- [ ] ⬜ **Task 3.1**: Surface downgraded enforcement modes and unresolved
  tools in `handlers` and `check` output.

## Success Criteria

- [ ] In a fixture monorepo (Node workspace + PHP workspace, no root
  manifest), `npm_command` enforces `llm:` wrappers, `lint_on_edit`
  finds workspace-installed linters, and `tdd_enforcement` honours a
  workspace-relative test dir.
- [ ] Single-root repositories show byte-identical handler behaviour with
  no added configuration.
- [ ] A silently-downgraded handler mode is visible in `check` output.

## Delivery & Milestones

- <!-- milestone or delivery commit hash -->
