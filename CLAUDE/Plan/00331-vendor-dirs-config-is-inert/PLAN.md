# Plan 00331: vendor dirs config is inert

**Status**: Not Started
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
  `ProjectLayout.is_vendored_path()` instead of the raw constant. Establish
  which of the current readers are genuinely project-scoped (so should honour
  a declaration) and which are language-convention literals that should not.
- [ ] ⬜ **Task 1.2**: Give docs QA a route to the declaration. Today
  `DocumentationPolicy` has no vendor field, so `corpus._is_excluded` could
  not honour one even if asked. This decides whether the policy grows a field
  or the corpus takes the layout facade.
- [ ] ⬜ **Task 1.3**: Resolve layout PER PROJECT, not from the root block. A
  project's `layout:` never inherits the top-level one (Plan 00300 —
  "the ROOT project's layout only, not a global fallback"), so a monorepo
  sub-project's `vendor_dirs` would otherwise be ignored the same way every
  declaration is ignored today.
- [ ] ⬜ **Task 1.4**: A test that a DECLARED vendor dir excludes a tree.
  Its absence is why this shipped inert: the field, the merge and the facade
  are all covered, and nothing asserted that declaring one changes any
  consumer's behaviour.

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

- [ ] Declaring `layout.vendor_dirs: [roles]` stops docs QA reporting inside
  an ansible-galaxy role tree — the client's case, end to end.
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
