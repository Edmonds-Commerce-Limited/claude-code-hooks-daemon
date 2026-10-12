# Plan 00510: docs qa edit stage skips nested and ignored checkouts

**Status**: Complete
**Created**: 2026-10-12
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #80

## Overview

`docs_qa/corpus.py` `is_lintable_path` decides what the docs QA EDIT stage
lints. Both the `docs_qa_edit` handler and `docs-qa --lint` use it. After the
`daemon.exclude_paths` check, it admits any module-scoped `CLAUDE.md`. That
includes a `CLAUDE.md` inside a nested, separately versioned git checkout, or
in a gitignored directory. Such a file is then judged against the outer
project's module-doc budget, and a large one could be denied. The SWEEP stage
already drops gitignored paths (`iter_corpus_paths`), so the two stages
disagree.

Coordinator ruling (the triage is in #80):

- A path inside a nested separate checkout is out of EDIT scope. That covers a
  clone, a submodule, or a linked worktree of another repository. This
  repository's own worktrees stay in scope. The boundary is the one Plan 00509
  gave the markdown formatter (`nested_git_checkout_root`,
  `is_worktree_of_repo`).
- A gitignored path is also out of EDIT scope, matching the sweep. The check
  must stay cheap: one path, not a whole-tree listing per Write.

## Goals

- The issue's reproduction draws no module-doc-budget finding, from either the
  handler or `docs-qa --lint`.
- A gitignored module `CLAUDE.md` is not linted at edit time.
- An ordinary tracked or untracked-but-not-ignored module `CLAUDE.md`, including
  one in this repository's own worktree, is still linted.

## Non-Goals

- Changing the sweep, or the module-doc budget itself.

## Tasks

### Phase 1: Fix

- [x] ✅ **Task 1.1**: RED. Write tests for `is_lintable_path` and for the
  `docs-qa --lint` CLI covering:
  - a nested clone;
  - a submodule-style `.git` file;
  - a foreign linked worktree;
  - this repository's own worktree, which stays linted;
  - a gitignored directory;
  - an ordinary module doc, which stays linted.
- [x] ✅ **Task 1.2**: GREEN. Implement in `is_lintable_path`, reusing the
  Plan 00509 helpers and an existing cheap ignore check if one exists. Measure
  the per-call cost.
- [x] ✅ **Task 1.3**: Update the handler guidance or the docs that state the
  edit-stage scope, and add a release note in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

### Phase 2: Land

- [x] ✅ **Task 2.1**: Review, coordinator checks, merge; comment on and close #80.
  Merged `5a963a367` with no rework. The boundary applies to every admitting
  arm, not only module docs, so the edit stage matches the sweep (a
  coordinator ruling).

## Success Criteria

- [x] The edit stage and the sweep agree on nested and ignored paths.
- [x] The release-bound consequence, a narrower edit scope, is in the
  pending-release holding area as release note 033 in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Delivery & Milestones

- Issue #80 triaged and claimed.
- Merged `5a963a367`; the range QA was green in substance.
