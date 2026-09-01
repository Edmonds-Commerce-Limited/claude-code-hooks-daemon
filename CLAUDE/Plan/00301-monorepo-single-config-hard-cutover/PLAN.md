# Plan 00301: monorepo single config hard cutover

**Status**: In Progress
**Created**: 2026-09-01
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plan 00296 delivered the top-level `projects:` config block as the single
source of project boundaries, but left two dual-path residuals: the
`markdown_organization.monorepo_subproject_patterns` regex alias (unioned
alongside `projects:`), and `tdd_enforcement`'s `test_path_map`, which
resolved a relative `test_dir` against TWO candidates (workspace-anchored
AND project-root-anchored). Owner ruling, verbatim: "those residuals
actually sounds like exactly the places that need fixing. Its not residual -
its half finished and that leaves us with 2 config paths to support -
complexity doubles, everything is painful. we should push properly into
monorepo support and ensure the upgrade system is smooth and easy and
ensure it all works. no fallback or backwards compat - the backwards compat
is dont upgrade to this version."

This plan removes both dual paths outright (no deprecation period, no
runtime fallback), and separately implements a follow-on owner ruling that
`layout.source_dirs` and its siblings are PER-PROJECT config: a declared
`projects:` entry may carry its own `layout:` block, and any handler needing
the union across every project gets DRY aggregation helpers on
`ProjectRegistry` rather than hand-rolling the loop. Single-project,
zero-config behaviour (no `projects:` declared) is required to stay
byte-identical throughout — pinned by tests, including against this repo's
own dogfood `.claude/hooks-daemon.yaml`.

Originally requested as "Plan 00300"; the git plan-number counter had
already advanced past 300 by the time this plan's folder was scaffolded
(`mkplan.bash`), so this folder is 00301. All in-flight code comments,
tests and upgrade-manifest entries already reference "Plan 00300" as the
identifying label for this body of work — that label is kept for
consistency across the diff rather than renumbered, per the counter being
authoritative for the FOLDER number only.

## Goals

- Remove `markdown_organization.monorepo_subproject_patterns` outright;
  its presence in config is a hard config-validation error at startup,
  printing a paste-ready `projects:` migration block.
- `tdd_enforcement.test_path_map`'s relative `test_dir` anchors against the
  file's declared workspace ONLY — remove the second, project-root-anchored
  candidate.
- `layout.source_dirs`/`test_dirs`/`config_dirs`/`vendor_dirs` become
  per-project config (a `projects:` entry may declare its own `layout:`),
  with DRY aggregation helpers (`ProjectRegistry.layout_for`,
  `iter_layouts`, `all_source_dirs`) so no handler hand-rolls project
  iteration.
- Zero-config, single-project behaviour (no `projects:` block) is
  byte-identical before and after every change in this plan.
- Upgrade-manifest entries (config-changes, truth-changes, a post-upgrade
  task) staged in `CLAUDE/UPGRADES/UNRELEASED/` so the next release carries
  the full cutover in one manifest.

## Non-Goals

- Cutting an actual release (version bump, RELEASES/ note, CHANGELOG entry).
- A compatibility shim, deprecation warning period, or config auto-migration
  script — the owner ruling is explicit that there is no fallback.
- Rewiring every remaining `_project_layout` consumer to per-project
  resolution in this pass; `tdd_enforcement` is wired as the flagship
  per-file consumer, and the DRY helpers exist for the rest to adopt
  incrementally without further design work.

## Tasks

### Phase 1: Remove the `monorepo_subproject_patterns` alias

- [x] ✅ **Task 1.1**: Delete `strip_monorepo_prefix`/`_monorepo_subproject_patterns` from `markdown_organization.py`; `matches()` uses only the declared `projects:` resolution.
- [x] ✅ **Task 1.2**: Hard config-validation error in `ConfigValidator._validate_removed_monorepo_patterns_option`, printing a mechanically-derived `projects:` block for literal patterns and a manual-translation note for wildcard patterns.
- [x] ✅ **Task 1.3**: Update `get_claude_md`/handler docs (`docs/guides/handlers/markdown_organization.md`, `docs/guides/CONFIGURATION.md`, `CLAUDE/Code/WorkspaceResolution.md`, `.claude/hooks-daemon.yaml.example`, `.claude/skills/configure/invoke.sh`).
- [x] ✅ **Task 1.4**: Rewrite alias/union tests into declared-`projects:` tests and hard-error-pinning tests.

### Phase 2: Single `test_dir` anchoring semantics

- [x] ✅ **Task 2.1**: `tdd_enforcement._map_declared_test_paths` returns one workspace-anchored candidate per mapping; remove the project-root-anchored second candidate.
- [x] ✅ **Task 2.2**: Confirm existing `TestDeclaredTestPathMapWorkspaceAnchoring` tests pin the new single-candidate behaviour (all pre-existing tests passed unchanged).

### Phase 3: Per-project `layout:` (owner follow-up ruling)

- [x] ✅ **Task 3.1**: `ProjectConfig.layout: LayoutConfig | None` — a declared project's own layout, never inherited from the root.
- [x] ✅ **Task 3.2**: `ProjectLayout.for_project`/`built_in_default`/`_dirs_from_layout_config` — per-project layout composition, DRY with the root's `from_config`.
- [x] ✅ **Task 3.3**: `ProjectRegistry.root_layout`, `layout_for`, `iter_layouts`, `all_source_dirs`, `_nearest_project`; module-level `resolve_layout` mirroring `resolve_workspace`.
- [x] ✅ **Task 3.4**: Wire `tdd_enforcement.matches()` through `resolve_layout` as the flagship per-file consumer.
- [x] ✅ **Task 3.5**: Tests: byte-identical single-project acceptance test (pins the dogfood config shape), per-project isolation (no leaking), aggregation helpers, `tdd_enforcement` routing.
- [x] ✅ **Task 3.6**: Docs: `CLAUDE/Code/WorkspaceResolution.md`, `docs/guides/CONFIGURATION.md` `projects:` section.

### Phase 4: Upgrade system

- [x] ✅ **Task 4.1**: `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.58.0.yaml` — `removed` entry for the alias, `changed` entry for `test_path_map` anchoring, `added` entry for per-project `layout`.
- [x] ✅ **Task 4.2**: `CLAUDE/UPGRADES/UNRELEASED/truth-changes/v3.58.0.yaml` — two truth-change entries.
- [x] ✅ **Task 4.3**: `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/03-migrate-monorepo-subproject-patterns.md` + task-index row.

### Phase 5: QA

- [x] ✅ **Task 5.1**: Full unit suite green.
- [x] ✅ **Task 5.2**: `mypy --strict` clean on every changed source file.
- [x] ✅ **Task 5.3**: `black -l 100`, `ruff check` clean on every changed file.

## Success Criteria

- [x] `monorepo_subproject_patterns` in config is a hard startup error with a migration message; the alias code path no longer exists.
- [x] A relative `test_path_map` `test_dir` resolves to exactly one candidate per declared project.
- [x] A `projects:` entry's own `layout:` never leaks into a sibling or the root, and vice versa.
- [x] The dogfood config (`.claude/hooks-daemon.yaml`, top-level `layout:`, no `projects:`) needs zero edits and resolves byte-identically — pinned by test.
- [x] Upgrade manifests staged for the next release, covering all three changes in one manifest.
- [x] Full unit suite, mypy --strict, black, ruff all green on touched files.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00301-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Phases 1-5 delivered in this worktree branch; see JOURNAL/00301-Journal-26-09-01.md and commit history for detail.
