# Plan 00462: php lsp advice keeps composer dependencies indexed

**Status**: In Progress
**Created**: 2026-09-24
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration (worktree, TDD)
**GitHub Issue**: #56

## Overview

`lsp_noise_checker` gives advice (R-LSP-CONFIG-EXCLUDE) that, followed
exactly, breaks PHP type resolution. `required_excludes()` puts
`**/<name>` for every name in `CORE_VENDORED_BUILD_DIR_NAMES`, `vendor`
included, into the set it gives EVERY language strategy.
`PhpLspNoiseStrategy.exclude_finding()` then reports a project-scope
intelephense plugin as incomplete unless it excludes all of `vendor/`.

intelephense's `files.exclude` removes files from its index, not just from
its diagnostics. Composer installs every dependency into `vendor/`, so
excluding it leaves `PHPUnit\Framework\TestCase`, Doctrine and Symfony types
undefined, and every PHP file reports "Undefined type". That is the
opposite of the handler's goal that "a diagnostic that survives both is
real". intelephense's own default exclude list removes only vendor's
nested test trees (`**/vendor/**/{Tests,tests}/**`) and nested vendor
trees (`**/vendor/**/vendor/**`).

Verified against the source (not taken from the issue): the lines are
`handlers/session_start/lsp_noise_checker.py` `required_excludes()` and
`strategies/lsp_noise/php_strategy.py` `exclude_finding()`, whose `missing`
list is computed from the full shared set.

The other strategies are not affected the same way, for the reason recorded
in Task 1.1. Pyright's `exclude` and tsconfig's `exclude` only choose which
files are checked as project roots. Imports still resolve into `.venv` and
`node_modules`. Go and Rust never ask for the any-depth names. Task 1.1
confirms this with sources rather than by assumption.

## Goals

- The PHP strategy never asks for an exclude that removes a dependency
  directory intelephense resolves types from. For `vendor` it asks for
  intelephense's own nested excludes (`**/vendor/**/{Tests,tests}/**` and
  `**/vendor/**/vendor/**`).
- An existing override that excludes the whole of `**/vendor` is reported
  as harmful, with the fix: remove it and keep the nested entries.
- Every other required tree (untracked/, plan dir, remote docs, the ccy
  plugin tree, the other vendored/build names) is still required for PHP.

## Non-Goals

- Changing `CORE_VENDORED_BUILD_DIR_NAMES`, which a dozen other consumers
  rely on to skip vendored content.
- Changing the advice for any other language unless Task 1.1 finds the same
  defect there.

## Tasks

### Phase 1: TDD in a worktree

- [x] ✅ **Task 1.1**: For each strategy, record with sources whether that
  server's exclude setting removes files from import/type resolution or
  only from checking. Record it in the journal. If another language has the
  same defect, add it to this plan's scope.
- [x] ✅ **Task 1.2**: RED tests.
  - The PHP no-override snippet contains no bare `**/vendor`, and does
    contain the nested entries.
  - An override with intelephense's defaults plus the plain trees gives no
    finding.
  - An override excluding `**/vendor` gets the harmful-entry finding.
  - A test checks that the `**/vendor` substitution is keyed to that
    language's dependency directory and is not a hard-coded string
    special case.
- [x] ✅ **Task 1.3**: Implementation. The language strategy decides which
  shared required names are dependency roots it must keep indexed (the
  handler stays language-free, per the module's CLAUDE.md). Update the
  PHP strategy docstring, handler guidance and `explain-handler` text.
  Write a release note that tells a PHP project to remove `**/vendor` from
  an override that followed the old advice.
- [x] ✅ **Task 1.4**: Full QA green. Restart the worktree daemon first.

### Phase 2: Deliver

- [ ] ⬜ **Task 2.1**: Merge `--no-ff`, verify ancestry and CI, and restart
  the daemon.
- [ ] ⬜ **Task 2.2**: Comment on #56 with the fix and the client action,
  and close it.

## Success Criteria

- [ ] Following the PHP advice exactly leaves `vendor/` indexed, apart from
  its nested test and vendor trees.
- [ ] An override excluding the whole of `vendor/` is flagged, and the flag
  names the fix.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00462-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Not yet delivered.
