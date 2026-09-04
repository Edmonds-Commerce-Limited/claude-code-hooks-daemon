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

### Phase 2: One vendor truth, referenced explicitly

**Superseded by the owner's SSoT ruling (2026-09-04).** The original Phase 2
was "make docs QA and plan QA consult `daemon.exclude_paths`". That is now
NOT the plan, and the reasoning matters more than the outcome.

`daemon.exclude_paths` is a DIFFERENT key with a different purpose: projects
set it broadly to exempt deliberately-bad FIXTURE trees from the CONTENT
blockers. Absorbing it into docs QA would make those trees silently stop
producing documentation findings — a coverage loss with no signal, in a key
the project set for unrelated reasons. Recorded as the argument for docs QA
having its own narrower `scope_exclude_globs` in the first place (Plan 00330
Task 1.4).

The owner's objection was the real one: every exclusion list that wants to
skip vendored paths currently has to RESTATE the vendor set by hand, which is
a distributed source of truth. The fix is not to make one key implicitly
absorb another; it is to let any exclusion list REFERENCE the single vendor
truth.

- [x] ✅ **Task 2.1**: A `{vendor-dirs}` token usable in any exclusion list
  (`daemon.exclude_paths`, a per-handler `exclude_paths`,
  `documentation.qa.scope_exclude_globs`). Resolved as a PREDICATE
  REFERENCE, not a glob expansion: it matches exactly when
  `ProjectLayout.is_vendored_path()` is true.

  Predicate rather than expansion is the load-bearing choice. Expanding to
  `**/<name>/**` globs would put the vendor NAMES into each list — the
  distributed truth again, one indirection later — and could not express the
  exceptions of Task 3.1 without `!` negation and a cross-key precedence
  rule. A reference has neither problem.

- [x] ✅ **Task 2.2**: Confirm a list mixing `{vendor-dirs}` with ordinary
  globs composes additively, and that the token is inert (never an error)
  where a consumer already skips vendored content by its own policy.

  The scope check changed the answer. The token is wired into
  `handler_excludes_path` — so `daemon.exclude_paths` and every per-handler
  `exclude_paths` — and deliberately NOT into
  `documentation.qa.scope_exclude_globs`: docs QA already skips every
  vendored path by its own policy, so the token is inert there and adding it
  would ship config surface that does nothing.

  Caught by the test, not by inspection: the `scope_exclude_globs` token
  test passed on its FIRST run with no token support in that path at all.
  A green test before the implementation is evidence the test is not
  measuring the implementation.

  One real defect surfaced while wiring it. Both the absolute and the
  project-relative form of a path are matching candidates and both contain
  the vendored segment, so asking whether ANY candidate is vendored let the
  absolute form answer first — and since an exception can only match the
  RELATIVE form, a declared carve-out became silently unreachable. Resolved
  on the first (most-relative) candidate only, with a regression test that
  fails on the `any` version.

### Phase 3: Re-include a first-party library inside a vendor tree

**Design note (owner, 2026-09-04).** An earlier draft of this phase used
gitignore-style `!` negation in `utils/path_exclusion`. Dropped: negation
spans several independent config keys with no inherent ordering, so it forces
an invented cross-key precedence rule (the old Task 3.3), and the vendor axis
is now wired end-to-end so a layout-scoped answer reaches every consumer for
free.

The two keys use DIFFERENT dialects, deliberately, and this must be
documented rather than left to inference — it read as an inconsistency on
first sight, which is a fair verdict on an undocumented asymmetry:

- `vendor_dirs` holds directory NAMES, matched against any path segment. A
  name is a CONVENTION: `node_modules` is vendored wherever it appears.

- `vendor_exceptions` holds repo-relative path GLOBS. An exception is a
  SPECIFIC thing the project owns — there is exactly one
  `infra/ansible/roles/our-own-role` — so a bare basename would be wrong
  precisely because it would match at any depth.

- [x] ✅ **Task 3.1**: `layout.vendor_exceptions` — repo-relative path globs
  that are NOT vendored even when they sit under a `vendor_dirs` name.
  Validated with the existing `_repo_relative_path` rule (absolute paths and
  `..` escapes rejected), so it inherits the portability guarantee the rest
  of the config already has.

- [x] ✅ **Task 3.2**: Make the directory-PRUNING walkers exception-aware.
  This is the constraint that will silently defeat the feature if missed: git
  itself cannot re-include a file whose parent directory is excluded, because
  it never descends. `docs_qa/checks/module_doc_budget.py` and
  `source_tree_markdown.py` both prune directories from `os.walk`, so a
  pruned `roles/` makes an exception beneath it unreachable and the
  first-party tree stays invisible. A pruning walker must not prune a
  directory that could CONTAIN an exception.

  Delivered with a DISCRIMINATING test pair rather than a single assertion:
  the same tree and the same `vendor_dirs`, differing only in whether an
  exception is declared, must yield the doc versus nothing. A lone
  "the exception is reported" test would pass just as well against a walker
  that had stopped pruning altogether.

  Needed at the point of USE as well as at the prune, because descending is
  not including: a sibling reached only because its parent had to be walked
  for an exception is still vendored, so both walkers re-test each file.

- [x] ✅ **Task 3.3**: Document the two dialects at the config surface, since
  the asymmetry is inherent rather than accidental (see the design note).
  Stated on `LayoutConfig`, on `ProjectLayout.vendor_exceptions` and in
  `utils/vendor_paths`' module docstring, and PINNED by a test that a bare
  `ours/**` does NOT match `infra/roles/ours/` — the dialect difference
  asserted rather than only described.

  `utils/vendor_paths` exists because BOTH the facade and docs QA need the
  same answer and neither may import the other: `core.project_layout`
  already imports `docs_qa.corpus`, so a `docs_qa` → `core` import would
  close a cycle. One implementation both read, rather than the parallel
  copies that made `vendor_dirs` inert to begin with.

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
- [x] A first-party library vendored inside a vendor directory is still
  checked when re-included by `layout.vendor_exceptions`. Verified end to
  end from a real YAML against a tree holding BOTH a third-party role and one
  the project maintains: the third-party doc is silent, the project's own is
  reported.
- [ ] A monorepo sub-project's declared `vendor_dirs` is honoured.
- [x] A project can exclude vendored paths from `daemon.exclude_paths` and
  any per-handler `exclude_paths` by REFERENCING the vendor truth
  (`{vendor-dirs}`) rather than restating the directory names. This replaces
  the original criterion — "a path excluded via `daemon.exclude_paths` is
  invisible to docs QA and plan QA" — which was withdrawn with its Phase 2
  (see the Phase 2 note: that key means something different, and absorbing
  it would silently drop doc findings in fixture trees).

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00331-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Milestone A — a declared `vendor_dirs` changes behaviour, root and
  per-project.
- Milestone B — `daemon.exclude_paths` reaches docs QA and plan QA.
- Milestone C — a first-party library inside a vendor tree can be re-included
  without the pruning walkers hiding it.
