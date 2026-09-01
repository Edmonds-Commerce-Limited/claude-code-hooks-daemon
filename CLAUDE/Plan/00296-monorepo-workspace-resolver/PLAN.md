# Plan 00296: monorepo workspace resolver

**Status**: In Progress
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

- A top-level `projects:` config block that models a project as a
  first-class concept and is the **only** source of project boundaries.
  Omitted means one project at the repo root — exactly today's behaviour.
  A monorepo is expressed by changing config structure.
- **Projects are declared, never derived.** Resolution has two layers only:
  declared `projects:`, else the repo root. Silently inferring a boundary is
  the same failure class as the defect this plan fixes — a wrong boundary
  leaves enforcement looking healthy while pointing at the wrong tree, with
  nothing saying so.
- A shared `Workspace` type as the single handler-facing API for "which
  project is this file in", carrying root, kind, manifest and tool bin dirs.
  Within a declared project, `kind` and `bin_dirs` still default by
  convention — that is convention inside a boundary the user drew.
- A **detector that advises, never decides**: when a repo looks like a
  monorepo (manifests below the root, none at it), say so and print the
  `projects:` block to paste. This is where the manifest walk-up lives.
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

- Requiring (or recommending) a root-level manifest **in the repository** —
  the report is explicit that a manifest existing purely to satisfy tooling
  is a bodge (it would declare dependencies the repo does not have and create
  a lockfile nobody installs). Declaring projects in
  `.claude/hooks-daemon.yaml` is NOT this: it tells the daemon where the
  projects are without putting a fake manifest in the repo.
- Making `projects:` mandatory. Zero-config single-project behaviour must
  stay byte-identical: an unconfigured repo resolves one project at the root.
- Automatic project resolution of any kind. An unconfigured monorepo keeps
  today's behaviour and gets a loud advisory — it does NOT get a guess.
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

### Phase 1: Shared `Workspace` type

- [x] ✅ **Task 1.1**: TDD `Workspace` in core (kind + bin_dirs per
  ecosystem, project-root fallback). Its manifest walk-up is **repositioned
  by Phase 3** from resolution to detection — same code, advisory role.
- [x] ✅ **Task 1.2**: Config surface review and documentation in the agent
  tree. Canonical doc:
  [../../Code/WorkspaceResolution.md](../../Code/WorkspaceResolution.md).
  Its "no new override knob" conclusion is **SUPERSEDED by Phase 3** (owner
  ruling): projects are declared config, not inferred.

### Phase 2: Route handlers through it

- [x] ✅ **Task 2.1**: `has_llm_commands_in_package_json()` takes the
  workspace root; `npm_command` evaluates per invocation. Resolves from a
  leading `cd <dir> &&` first, then the hook's `cwd` — cwd alone leaves the
  reported symptom in place, since a monorepo npm command runs from the repo
  root and cds into the workspace.
- [x] ✅ **Task 2.2**: `lint_on_edit` working dir + executable resolution
  via workspace bin dirs. Ansible kept its `ansible.cfg` working directory:
  `_MODULE_ROOT_MARKERS` is consulted FIRST and the workspace root is the
  fallback, since `ansible.cfg` is not a manifest. Return-None-not-guess is
  unchanged; the "not found" advisory now names the bin dirs it searched.
- [x] ✅ **Task 2.3**: `validate_eslint_on_write` per-file workspace — cwd,
  PATH and the mode probe all derive from the authored file's workspace; an
  explicit `workspace_root` still pins every file (test seam preserved).
- [x] ✅ **Task 2.4**: `tdd_enforcement` workspace-relative `test_path_map`
  and removal of the hardcoded `/workspace` fallback.
- [x] ✅ **Task 2.5**: `markdown_organization` automatic resolution with
  `monorepo_subproject_patterns` as override.

### Phase 3: `projects:` config is the only source of boundaries

Ordered after Phase 2 because `Workspace` is already the type every handler
consumes: this changes where a `Workspace` COMES FROM, not what consumes it.

- [x] ✅ **Task 3.1**: Top-level `projects:` schema + models
  (`name`, `root`, optional `kind`, optional `bin_dirs`), validated and
  defaulting to a single project at the repo root when omitted. A declared
  project needs no manifest (the report's `infra/`). Owner ruling enforced:
  **zero absolute paths** — `root` AND every `bin_dirs` entry must be
  repo-relative, non-escaping; duplicates of name or root rejected.
- [x] ✅ **Task 3.2**: `ProjectRegistry` resolves from declared projects,
  else the repo root — the manifest walk left the resolution path entirely
  and survives only as convention inside a declared root. Nearest declared
  root wins when projects nest, independent of config order.
- [x] ✅ **Task 3.3**: Handlers resolve via the injected `_project_registry`
  (wiring mirrors `ProjectLayout`); Phase 2 handler tests re-pointed at
  `projects:`-declared fixtures, each with an anti-inference pin.
- [x] ✅ **Task 3.4**: Monorepo DETECTOR + advisory: manifests below the root
  with none at it means "this looks like a monorepo" — name the workspaces
  found and print the `projects:` block to paste. Advises, never decides.
- [x] ✅ **Task 3.5**: `markdown_organization`'s `monorepo_subproject_patterns`
  re-expressed as `projects:` entries, keeping the option working as a
  deprecated alias rather than a parallel mechanism.
- [x] ✅ **Task 3.6**: Document `projects:` in the config reference and
  rewrite [../../Code/WorkspaceResolution.md](../../Code/WorkspaceResolution.md)
  around declared-or-root, with the manifest walk described as detection.

### Phase 4: Degradation visibility

- [x] ✅ **Task 4.1**: Surface downgraded enforcement modes and unresolved
  tools in `handlers` and `check` output.

## Success Criteria

- [ ] In a fixture monorepo declaring `projects:` (Node workspace + PHP
  workspace + a manifest-less `infra/`, no root manifest), `npm_command`
  enforces `llm:` wrappers, `lint_on_edit` finds workspace-installed
  linters, and `tdd_enforcement` honours a workspace-relative test dir —
  including for `infra/`, which has no manifest to infer from.
- [ ] The SAME fixture with `projects:` absent behaves exactly as a
  single-project repo (no guessing) and emits the monorepo advisory naming
  the workspaces it found.
- [ ] Single-project repositories show byte-identical handler behaviour with
  no added configuration and no advisory.
- [x] A silently-downgraded handler mode is visible in `check` output.

## Delivery & Milestones

- <!-- milestone or delivery commit hash -->
