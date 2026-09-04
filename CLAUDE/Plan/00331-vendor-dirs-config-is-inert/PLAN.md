# Plan 00331: vendor dirs config is inert

**Status**: In Progress
**Created**: 2026-09-04
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

A project can declare `layout.vendor_dirs` and it does nothing. The config
field is real, documented ("Extra vendored/build directory names, extending
the canonical set") and carries `additive`/`replace` mode. `ProjectLayout`
merges declared names with the builtin set and exposes `is_vendored_path()`
for the check. **`is_vendored_path` has zero production consumers** — its
definition and two tests, nothing else.

Every consumer instead reads the raw `CORE_VENDORED_BUILD_DIR_NAMES` constant,
which is the BUILTIN half only. So a declared vendor directory is silently
inert everywhere. `docs_qa/corpus.py:200` tests membership of the raw
frozenset, and `DocumentationPolicy` carries no vendor field at all, so there
is no route by which a project's declaration could reach docs QA.

This is what a client hit: an ansible-galaxy role tree
(`infra/ansible/roles/`) is vendored third-party code, but its directory name
is not in the conservative builtin set — and the config that exists to say so
is not consulted. Plan 00329's sibling fix
(`documentation.qa.scope_exclude_globs`, `0054105b`) gave them a workaround;
it did not fix the mechanism they should have been able to use.

The defect shape is the one that produced two bugs on 2026-09-04 already: a
check reaching for a raw constant instead of the configured facade.

## Scope note

The vendor AXIS is not missing and must not be re-invented (owner discussion,
2026-09-04). Plan 00288 built it; Plan 00300/00301 made `layout:` per-project.
A second top-level "vendor paths" block would be a second spelling of an
existing config whose `mode` semantics are already settled. This plan WIRES
what exists.

## Goals

- A declared `layout.vendor_dirs` actually excludes that tree, in docs QA and
  every other consumer of the canonical set.
- A project can re-include a first-party library vendored INSIDE a vendor
  directory.
- `daemon.exclude_paths` is honoured by docs QA and plan QA, answering the
  decision gate recorded as Plan 00330 Task 1.4.

## Non-Goals

- **Not** a new top-level vendor config block (see Scope note).
- **Not** widening `CORE_VENDORED_BUILD_DIR_NAMES` itself. Its inclusion
  criterion is deliberately conservative — a name only qualifies when no
  consumer skipping vendored content could ever be wrong to skip it
  (`CLAUDE/Plan/00288-.../MEASUREMENT-vendored-dirs.md` section 2). A
  project-specific name like `roles` cannot meet that bar, which is exactly
  why the CONFIG axis exists.
- **Not** changing per-language strategy literals (`vendor/` for Go/PHP) where
  the language convention genuinely differs from the shared set.

## Tasks

### Phase 1: Wire the facade

- [ ] ⬜ **Task 1.1**: Route the canonical-set consumers through
  `ProjectLayout.is_vendored_path()` instead of the raw constant. Established
  by measurement, so this starts from data rather than a fresh survey — of 44
  modules carrying a vendor notion:

  | Category                                   | Count |
  | ------------------------------------------ | ----- |
  | routed through the canonical set only      | 5     |
  | canonical set AND a bare literal           | 8     |
  | bare literal only, of which:               | 31    |
  | — per-language strategies (`strategies/*`) | 23    |
  | — **not** a language strategy              | **8** |

  The 23 language-strategy literals are legitimately per-language (a Go
  project's `vendor/` is not a JS project's `node_modules`) and are the
  Non-Goal above. The actionable set is the 8 non-strategy literal-only
  modules — `config.models`, `core.workspace`, `lint_on_edit`,
  `markdown_organization`, `qa_suppression`, `security_antipattern`,
  `tdd_enforcement`, `secret_file_hygiene_checker` — plus the 8 that use BOTH
  the canonical set and a bare literal, which need a reason for carrying each.

  Three of the canonical-set consumers were routed under Task 1.2, since
  their fix WAS the docs-QA route: `docs_qa/corpus.py`,
  `docs_qa/checks/module_doc_budget.py` and
  `docs_qa/checks/source_tree_markdown.py`.

- [x] ✅ **Task 1.2**: Give docs QA a route to the declaration. Resolved by
  growing `DocumentationPolicy` a `vendor_dirs` field, NOT by handing the
  corpus a `ProjectLayout`: `core.project_layout` already imports
  `docs_qa.corpus`, so the facade route would close an import cycle, and it
  would break the package's deliberate plain-values decoupling. The merge
  stays in `ProjectLayout` (it owns `additive`/`replace`); what travels is
  the EFFECTIVE set, used verbatim — re-unioning it with the canonical
  constant on arrival would have silently defeated `mode: replace`.

  Wired at both entry points: the registry (`policy_from_config` now takes
  the injected `project_layout`'s dirs) and the `docs-qa` CLI. Three readers
  moved off the raw constant — `corpus._is_excluded`, and the two checks
  that run their OWN pruned `os.walk` rather than reading the corpus
  (`module_doc_budget`, `source_tree_markdown`), each of which had frozen the
  built-in names into a module-scope frozenset.

- [ ] ⬜ **Task 1.3**: Resolve layout PER PROJECT, not from the root block. A
  project's `layout:` never inherits the top-level one (Plan 00300 —
  "the ROOT project's layout only, not a global fallback"), so a monorepo
  sub-project's `vendor_dirs` would otherwise be ignored the same way every
  declaration is ignored today.

  **Blocked on a scope decision, and deliberately not done on sight.** docs
  QA has NO per-project concept at all: zero references to `project_registry`
  anywhere in the package, against 8 handlers that resolve per-project via
  `resolve_workspace`. Its corpus is one project-root-wide index and its doc
  trees are single root-level directories, so "this sub-project's vendor
  dirs" has nowhere to attach. Introducing per-project resolution into docs
  QA is a substantially larger change than wiring the vendor axis, and the
  cheap-looking middle ground — unioning every declared project's
  `vendor_dirs` — is worse than doing nothing: project A declaring `roles`
  would silently hide project B's `roles/` documentation, which is the
  hiding-without-telling failure this plan exists to end.

- [x] ✅ **Task 1.4**: A test that a DECLARED vendor dir excludes a tree.
  Its absence is why this shipped inert: the field, the merge and the facade
  are all covered, and nothing asserted that declaring one changes any
  consumer's behaviour.

  16 tests. Each behaviour test is paired with a guard asserting that an
  UNDECLARED directory of the same name is still reported — without it the
  suite would pass equally well if `roles` were quietly added to the
  canonical set, which is this plan's Non-Goal. `roles` is used throughout
  for the same reason: a test written against `vendor/` or `node_modules`
  passes without the fix.

### Phase 2: Honour daemon.exclude_paths

- [ ] ⬜ **Task 2.1**: Make docs QA and plan QA consult
  `daemon.exclude_paths` via `utils/path_exclusion` (pure stdlib, so it does
  not break docs_qa's deliberate daemon/pydantic decoupling). Verified: zero
  references in either package against 12 handler modules that honour it,
  while the shipped guidance offers it as the project-wide exemption.
- [ ] ⬜ **Task 2.2**: Confirm the interaction with `scope_exclude_globs`
  is additive and that neither key silently overrides the other, matching how
  `daemon.exclude_paths` composes elsewhere.

### Phase 3: Re-include a first-party library inside a vendor tree

- [ ] ⬜ **Task 3.1**: Add gitignore-style `!` negation to
  `utils/path_exclusion`. The module already advertises a "gitignore-style
  subset", so this makes it MORE conventional rather than inventing an idiom.
- [ ] ⬜ **Task 3.2**: Make the directory-PRUNING walkers negation-aware.
  This is the constraint that will silently defeat the feature if missed: git
  itself cannot re-include a file whose parent directory is excluded, because
  it never descends. `docs_qa/checks/module_doc_budget.py` prunes directories
  from `os.walk` (including via `_dir_is_scope_excluded`), so a pruned
  `vendor/` makes `!vendor/our-lib/**` unreachable and the first-party tree
  stays invisible. A pruning walker must not prune a directory that could
  contain a re-inclusion.
- [ ] ⬜ **Task 3.3**: Decide precedence when a path matches both an
  exclusion and a negation across DIFFERENT config keys (a `vendor_dirs`
  entry and a `daemon.exclude_paths` negation). Within one gitignore file
  last-match-wins; across independent keys there is no inherent order, so one
  must be chosen and documented.

## Success Criteria

- [x] Declaring `layout.vendor_dirs: [roles]` stops docs QA reporting inside
  an ansible-galaxy role tree — the client's case, end to end. Verified
  against a real on-disk YAML driving the production chain
  (`Config.load_or_default` → `ProjectLayout.from_config` →
  `policy_from_config` → `build_and_save_corpus` → `run_stage(SWEEP)`), and
  verified RED on the pre-fix tree: there the config parsed and
  `ProjectLayout` merged `roles` into `vendor_dirs` CORRECTLY, and the sweep
  reported the finding anyway. That is the diagnosis in one run — the facade
  was never broken, it simply had no consumer.
- [ ] A first-party library vendored inside a vendor directory is still
  checked when re-included by negation.
- [ ] A monorepo sub-project's declared `vendor_dirs` is honoured.
- [ ] A path excluded via `daemon.exclude_paths` is invisible to docs QA and
  plan QA.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00331-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Milestone A — a declared `vendor_dirs` changes behaviour, root and
  per-project.
- Milestone B — `daemon.exclude_paths` reaches docs QA and plan QA.
- Milestone C — a first-party library inside a vendor tree can be re-included
  without the pruning walkers hiding it.
