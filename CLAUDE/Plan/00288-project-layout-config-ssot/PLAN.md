# Plan 00288: Project-layout config SSoT

**Status**: In Progress
**Created**: 2026-08-29
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Directory truths — which dir is source, test, human docs, agent docs, plans,
vendor/build — are today declared in dozens of independent places: two config
homes that some consumers bypass (`documentation.trees` is ignored by
`markdown_organization`, which hardcodes `CLAUDE/`+`docs/` and would BLOCK a
project that configured different tree names; `plan_workflow.directory` is
ignored by three handlers that regex-hardcode `CLAUDE/Plan/`), plus four-plus
conflicting hardcoded vendored/build-dir sets and no config home at all for
source/test dir names. The full cited inventory is in
[DESIGN-layout-ssot.md](DESIGN-layout-ssot.md) §1.

This plan gives the project ONE layout surface: a new top-level `layout:`
config block for the truths that have no home, and a `ProjectLayout` runtime
facade composing it with the existing homes so every handler reads one API and
none re-declares a truth. It is Core Standard 10 and DocumentationStrategy R5
applied to config, a follow-on in the Plan 00284 docs-SSoT programme. It also
adds the owner-directed enforcement: markdown already on disk under source/test
dirs must follow the SSoT pattern (collocated `CLAUDE.md` allowed as module
docs), delivered as a sweep-only `docs_qa` check that cannot double-report with
`markdown_organization`'s write-time gate.

Backwards compatibility is non-negotiable: with no `layout:` block configured,
behaviour is byte-identical to today, pinned by tests.

## Goals

- One top-level `layout:` block (source_dirs, test_dirs, config_dirs,
  vendor_dirs; `mode: additive|replace`) with empty, behaviour-preserving
  defaults.
- A `ProjectLayout` facade as the single handler-facing API over layout truths,
  composing the new block with `documentation.trees`,
  `plan_workflow.directory` and the plan archive dirs — those keys stay where
  they are (facade over migration; see DESIGN §2a and decision D2).
- Consumption refactors C1–C8 (DESIGN §5): every ≥2-consumer directory truth
  read from the facade or one canonical constant; the
  `markdown_organization`-vs-`documentation.trees` conflict dissolved.
- One reviewed canonical vendored/build dir core constant, swapped in per
  consumer against a measured before/after diff table (DESIGN §3).
- New sweep-only `docs_qa` check `source-tree-markdown` flagging
  non-`CLAUDE.md` markdown in source/test dirs to point/promote (DESIGN §4).
- Client upgrade impact: nothing changes until a project adopts the block
  (DESIGN §7); `config-changes` and truth-changes manifest entries staged.

## Non-Goals

- Moving `documentation.trees` / `plan_workflow.directory` under `layout:`
  (unless the human picks Option B at the design gate).
- Filesystem sniffing to infer layout at startup.
- Self-install marker consolidation (daemon identity, not project layout).
- Ansible playbook-segment conventions (ecosystem-defined, not project layout).
- Per-language TDD/qa_suppression `_SKIP_DIRECTORIES` pair consolidation
  (single-domain DRY fix, no config involvement — recorded so it is not
  re-derived).
- Unifying `markdown_organization`'s regex option dialect with the glob
  dialect (breaking change to existing option values).
- A "every major source dir must HAVE a CLAUDE.md" presence check (decision
  D3 — deferred pending the owner's reading of their own direction).

## Context & Background

- [DESIGN-layout-ssot.md](DESIGN-layout-ssot.md) — the full analysis: cited
  inventory, schema proposal, additive/replace semantics, check design,
  decisions D1–D4, client-impact argument.
- Plan 00284 (`Completed/00284-documentation-ssot-enforcement/`) — the
  programme this extends; `documentation:` block and `docs_qa` package are the
  structural precedent, as `plan_workflow:` was for it.
- Plan 00287 F3 — introduced `COMMON_VENDORED_BUILD_DIR_NAMES` and the
  vendored-daemon corpus exclusion this plan generalises.

## Tasks

### Phase 1: Design approval gate (BLOCKING — no implementation before it)

- [x] ✅ **Task 1.1**: Rulings recorded (see Technical Decisions). The owner's
  landing mandate ("coordinate this work, land both plans") delegated the gate
  to the coordinator, which adopted every DESIGN recommendation as the
  conservative default; each ruling is reversible pre-release if the owner
  overrules.

## Technical Decisions

- **D1 — block name `layout:`** (adopted as recommended): named for exactly
  what it holds, matching `documentation:`/`plan_workflow:` style.
- **D2 — Option A, facade** (adopted as recommended): existing keys stay
  canonical; `ProjectLayout` unifies ACCESS, no alias/migration machinery.
- **D3 — enforce shape (i), defer presence (ii)** (adopted as recommended):
  markdown that IS present in source/test dirs must follow the SSoT pattern; a
  "major dirs must HAVE a CLAUDE.md" presence check stays a recorded non-goal.
- **D4 — `README.md` allowed in place under source dirs** (adopted as
  recommended): conventional package entry point; flagging it would be noise.
- **D5 — shipped directory-role rules** (owner mandate, post-design): the
  release ships `.claude/rules/` pointer files, paths-glob scoped per directory
  role (source, tests, human docs, agent docs, skills, sub-agents, plans), each
  ≤15 lines per R7a, pointing at ONE canonical directory-roles document in the
  agent tree. Every directory gets a clear role and a clear rule; the rule
  bodies are SSoT docs, the `.claude/rules` files only route. Deployed by the
  installer alongside the existing shipped assets; upgrade path via the Plan
  00279 md5-ledger mechanism so client edits are never clobbered.

### Phase 2: Schema + facade (TDD)

- [x] ✅ **Task 2.1**: `LayoutConfig` pydantic model (tests first: defaults,
  `extra="forbid"`, mode literal), wired as `Config.layout`.
- [x] ✅ **Task 2.2**: `ProjectLayout` frozen facade + builder from `Config`
  (tests: zero-config composition equals today's built-ins; additive and
  replace semantics; membership helpers).
- [x] ✅ **Task 2.3**: Registry injection (`self._project_layout`, mirroring
  `_project_exclude_paths`) + plumbing into the `plan_qa`/`docs_qa` contexts.

### Phase 3: Canonical vendored/build core (measured)

- [x] ✅ **Task 3.1**: Produce the per-consumer before/after diff table for
  the proposed core set; accept or keep-as-domain-extra each delta. See
  [MEASUREMENT-vendored-dirs.md](MEASUREMENT-vendored-dirs.md) — 11-name core,
  21 ACCEPT deltas, 0 KEEP-LOCAL deltas, 13 retained domain extras; eslint
  matcher fix is a Task 3.2 precondition.
- [x] ✅ **Task 3.2**: Ship the core constant and swap the four whole-project
  consumers onto it (C2), with regression tests per consumer.

### Phase 4: Consumption refactors (each with before/after pin tests)

- [x] ✅ **Task 4.1**: C3 — `markdown_organization` reads the facade for doc
  trees, plan dir, archive dirs.
- [x] ✅ **Task 4.2**: C4 — plan-dir regex handlers (`goal_injection`,
  `recovery_cron_advisor`, `plan_workflow`, `plan_number_helper`) read the
  facade.
- [x] ✅ **Task 4.3**: C5 — main-repo code dirs from the facade
  (`worktree_file_copy`, `same_commit_plan_doc`, `path_existence`).
- [x] ✅ **Task 4.4**: C6 — `tdd_enforcement` consults declared
  source/test dirs before per-language inference; `test_path_map` unchanged.
- [x] ✅ **Task 4.5**: C7 — `british_english` docs dirs from the facade.
- [x] ✅ **Task 4.6**: C8 drive-bys — worktree regex derived from its
  constant; dead `ProjectPath` client-layout members removed or re-scoped;
  stale "eight callers" count de-numbered; phantom default-exclude guidance
  in `comment_size`/`comment_changelog`/`security_antipattern` fixed
  (implement or reword).

### Phase 5: source-tree-markdown check

- [x] ✅ **Task 5.1**: New sweep-only `docs_qa` check per DESIGN §4b (TDD:
  fixtures for flagged/allowed/fixture/grandfathered cases), ADVISE severity,
  scope from the facade.
- [x] ✅ **Task 5.2**: Handler guidance + `docs-qa` CLI coverage +
  HANDLER_REFERENCE entry; confirm no double-report with
  `markdown_organization` via an integration test.

### Phase 5b: Shipped directory-role rules (D5)

- [x] ✅ **Task 5b.1**: Canonical directory-roles doc in the agent tree
  (each directory role: what belongs there, what does not, where the depth
  lives) — the single SSoT body the rules point at.
- [x] ✅ **Task 5b.2**: Shipped `.claude/rules/` pointer files (R7a-compliant,
  paths-glob scoped: `src/**/*.md`, `tests/**/*.md`, human tree, agent tree,
  `.claude/skills/**`, `.claude/agents/**`, plan dir) deployed by the
  installer with md5-ledger upgrade semantics; globs derived from the
  project's configured layout at deploy time, not hardcoded.
- [x] ✅ **Task 5b.3**: Dogfood the rules in this repo; verify deploy +
  upgrade in the dummy client fixture.

### Phase 6: Docs, manifests, dogfood

- [x] ✅ **Task 6.1**: Stage `UNRELEASED/config-changes/` entry (`layout`
  added) and a truth-changes entry for the Shape-A behaviour fixes.
- [x] ✅ **Task 6.2**: Document the block (HANDLER_REFERENCE / agent tree),
  regenerate generated docs.
- [ ] ⬜ **Task 6.3**: Dogfood: declare this repo's own layout in
  `.claude/hooks-daemon.yaml`, full QA, daemon restart verification, and a
  client-mode check via `scripts/dummy-client-repo.sh` (config paths
  changed).

## Success Criteria

- [ ] With no `layout:` block, every refactored consumer's behaviour is
  pinned unchanged by tests.
- [ ] No handler or check package re-declares a ≥2-consumer directory truth;
  grep evidence recorded for the C1–C7 truths.
- [ ] A project configuring non-default `documentation.trees` is treated
  consistently by `markdown_organization` and `docs_qa`.
- [ ] `source-tree-markdown` reports on-disk violations in sweep and never
  fires at edit time.
- [ ] Full QA passes; daemon restart verified; client-mode fixture verified.

## Delivery & Milestones

- Design + plan committed (this commit).
