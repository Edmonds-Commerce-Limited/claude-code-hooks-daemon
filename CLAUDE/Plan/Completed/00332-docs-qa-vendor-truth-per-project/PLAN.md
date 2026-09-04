# Plan 00332: docs qa vendor truth per project

**Status**: Complete
**Created**: 2026-09-04
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

A monorepo sub-project can declare `projects[].layout.vendor_dirs` and docs QA
never sees it. The declaration parses, `ProjectConfig.layout` holds it, and
`ProjectLayout.for_project()` resolves it correctly — but docs QA is handed
ONE flat vendored set taken from the ROOT `layout:` block, so a sub-project's
declaration is silently inert. Measured, not inferred:

```
sub-project declared vendor_dirs : ['roles']   <- parses fine
ROOT layout contains 'roles'     : False       <- never merges upward
docs QA policy contains 'roles'  : False       <- so docs QA never sees it
```

This is the same defect shape Plan 00331 fixed at the root — a config field
that is real, documented and reachable by the facade, with no consumer on the
path that matters — reappearing one axis over. Plan 00331 closed the root case
(verified end to end from real YAML) and closed the handler case via
`Handler.layout_for()`; it recorded the docs-QA case as out of scope on
reasoning that does not survive inspection, which is why this plan exists
rather than a note.

**The reasoning being corrected.** Plan 00331's Task 1.3 argued that unioning
every declared project's `vendor_dirs` would let project A silently hide
project B's documentation, and treated that as ruling the work out. The
argument is sound about UNION and says nothing about the correct design.
Per-path resolution — ask which project owns this path, use that project's
vendor set — has none of the cited problems: no cross-project leakage, no
precedence rule to invent, no import cycle.

## Goals

- A monorepo sub-project's declared `layout.vendor_dirs` and
  `layout.vendor_exceptions` govern docs QA for paths under that project, and
  only for those paths.
- One resolution rule shared by the corpus and both pruning walkers, so the
  three cannot drift the way parallel vendor copies did before Plan 00331.
- Zero-config and single-project behaviour byte-identical to today.

## Non-Goals

- Making the docs CORPUS per-project. It stays one repo-wide index with one
  set of doc trees; `docs_qa_sweep` keeps `WorkspaceScope.REPO`. Only the
  vendored-path PREDICATE becomes path-aware — a per-path exclusion test
  applied while building one corpus is not per-project corpus resolution, and
  conflating the two is what made this look bigger than it is.
- Per-project `documentation:` config (trees, check modes, allowlists). That
  is a genuinely larger change and nothing has asked for it.
- Touching the 23 per-language strategy literals (Plan 00331's Non-Goal,
  unchanged).

## Tasks

### Phase 1: One path-aware vendor answer

- [x] ✅ **Task 1.1**: A `VendorScope` value and a longest-root resolver in
  `utils/vendor_paths.py` — the module that already exists precisely because
  the facade and docs QA both need this answer and neither may import the
  other (`core.project_layout` imports `docs_qa.corpus`, so the reverse
  closes a cycle).

  `VendorScope(root, vendor_dirs, vendor_exceptions)` where `root` is the
  repo-relative project root (`""` for the root project). Resolution is
  LONGEST matching root, not first: a sub-project declared under another
  project's tree must win over its ancestor, and first-match would make the
  answer depend on declaration order in the YAML.

  A path matching no scope is judged by the root scope, so a repo with no
  `projects:` block resolves exactly as today.

- [x] ✅ **Task 1.2**: Scope-aware `is_vendored_path_in_scopes` and
  `may_contain_vendor_exception_in_scopes`. The second is the prune-safety
  question and needs the same care Plan 00331 Task 3.2 established: a walker
  that prunes a directory never descends into it, so an exception beneath it
  becomes unreachable. Per-scope resolution adds a second way to get this
  wrong — a directory that is an ANCESTOR of a declared project must never be
  pruned on the root scope's say-so, because the owning project's exceptions
  live below it. Resolved by asking EVERY scope and letting any "yes" win.

### Phase 2: Route the three consumers through it

- [x] ✅ **Task 2.1**: `DocumentationPolicy.vendor_scopes` replaces the flat
  `vendor_dirs` / `vendor_exceptions` pair. Replaced rather than added
  alongside: keeping both would leave two vendor truths on one object, which
  is the distributed-source-of-truth failure the owner ruled against during
  Plan 00331 Phase 2.

  `policy_from_config` takes `vendor_scopes`; `None` keeps the canonical
  single-scope default.

- [x] ✅ **Task 2.2**: Move the five consumer sites onto the scopes —
  `corpus._is_excluded`, `module_doc_budget` (the per-file test and the
  prune), `source_tree_markdown` (the per-file test and the prune). These are
  the same three files Plan 00331 Task 1.2 moved off the raw constant; they
  now move off the flat pair. Both walkers needed an extracted `_walk_into`
  helper: per-scope resolution needs the directory's PATH, where the flat
  pair only ever needed its NAME.

- [x] ✅ **Task 2.3**: Build the scopes at both entry points — the handler
  registry (`handlers/registry.py`) and the `docs-qa` CLI (`daemon/cli.py`).
  Both were done: the CLI sweep is the surface a human runs by hand, and
  honouring a declaration only at dispatch time would report findings the
  edit-time check already skips (the same split Plan 00331 closed for the
  root case).

  Built from `ProjectRegistry.vendor_scopes()` rather than
  `iter_layouts()` as this task originally specified. `iter_layouts()` yields
  the project NAME, and a name cannot be matched against a path; the registry
  is the one place that knows both the declared ROOT and the resolved layout,
  so it is the only place that can produce the scopes as plain values.

### Phase 3: Prove it end to end

- [x] ✅ **Task 3.1**: A real-YAML end-to-end test through the production
  chain (`Config.load_or_default` -> `ProjectRegistry.from_config` ->
  `vendor_scopes` -> `policy_from_config` -> the consumers) against a tree
  where `apps/api` declares `roles` vendored and `apps/web` does not, holding
  an identically-shaped doc under each —
  `tests/integration/test_docs_qa_vendor_scopes_e2e.py`.

  The SIBLING is the discriminating half. A test that only asserts the
  declaring project's tree is skipped passes on a root-wide union too, which
  is the design this plan rejects — so without the sibling the test cannot
  tell the correct implementation from the one that hides project B's docs.

  Retargeted from `run_stage(SWEEP)` to `_iter_module_doc_paths` and
  `build_and_save_corpus`: the corpus indexes only configured doc trees plus
  the root README, so a fixture CLAUDE.md in an arbitrary sub-folder never
  entered it. Those two ARE the places a vendored path is decided, which is
  the axis this plan changed.

- [x] ✅ **Task 3.2**: Verified RED on the pre-fix tree — the probe in the
  Overview is that run. It shows the declaration parsing correctly AND the
  policy not carrying it, which is the diagnosis in one run and is what
  distinguishes "no consumer" from "broken facade".

## Success Criteria

- [x] A sub-project's declared `vendor_dirs` silences docs QA inside that
  sub-project's vendored tree, verified end to end from real YAML.
- [x] A SIBLING sub-project that declares nothing is still reported, in the
  same run — proving the declaration did not leak repo-wide.
- [x] `layout.vendor_exceptions` declared by a sub-project re-includes a
  first-party library inside that project's vendored tree, and the pruning
  walkers still reach it.
- [x] Zero-config and single-project repos behave identically to before,
  pinned by the existing Plan 00331 tests continuing to pass unchanged.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00332-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Milestone A — one path-aware vendor answer exists and is shared.
  Delivered `116207c7`.
- Milestone B — docs QA honours a sub-project's declaration, and only within
  that sub-project. Delivered `116207c7`.

**A regression this plan caused and caught.** Routing docs QA through the
registry silently dropped the ROOT declaration for the
`register_all(project_layout=..., project_registry=None)` call shape,
reintroducing Plan 00331's inert-config bug as a fallback path. QA found it;
`_vendor_scopes_for_policy` names the fallback explicitly and both shapes are
now pinned by tests. Worth recording because the failure mode is this plan's
own subject reappearing inside its own fix — the shape recurs precisely
because each new indirection is a new chance for a config field to lose its
consumer.
