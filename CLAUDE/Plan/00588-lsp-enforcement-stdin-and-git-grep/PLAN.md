# Plan 00588: lsp_enforcement leaves stdin greps and git grep alone

**Status**: In Progress
**Created**: 2026-11-09
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #169

## Overview

`lsp_enforcement` (R-LSP-SYMBOL-LOOKUP) steers symbol LOOKUPS to the LSP tool; its own guidance says grep stays
right for text patterns and log searching. Two shapes that no language server can answer are judged as lookups.
Both reproduced on `main` at triage:

1. **A grep reading stdin.** `printf … | grep -v resolve_venv` was denied (the session's `block_once` denial). It
   searches no file: it filters another command's output. The handler treats "no target" as "the whole project".
2. **`git grep`.** `git grep -lF <identifier> HEAD -- <a markdown-only directory>` is judged an LSP-answerable
   lookup suggesting `workspaceSymbol` (an advisory only because the session's denial was spent). Content at a
   commit is nothing a language server sees, and the grep-word match picks up the `git` subcommand. With a `*.md`
   glob it advises installing a markdown language server, which is noise for this shape too.

Dedupe scout (70 live plans): no plan covers it. Prior art: Plan 00075 (the handler), Plan 00567 (coverage from a
named target's suffix, with "covered" as the fallback for targets that cannot be judged).

## Goals

- A grep with no file or directory target that reads stdin (a later pipeline stage, or a here-string or redirect
  into it) is not a symbol lookup: no deny, no advisory.
- `git grep` is not judged as a workspace symbol lookup: no deny; at most nothing (a ref makes it historical
  content, and git grep's own pathspecs are not the handler's file targets).
- Real lookups stay enforced: `grep -rn some_identifier src/`, `rg some_identifier`, `grep -n def foo src/x.py`,
  and the Grep tool.

## Non-Goals

- No change to which patterns look like identifiers, to the modes, or to the coverage rules for named targets.

## Tasks

### Phase 1: Fix

- [ ] ⬜ **Task 1.1**: RED tests: a stdin grep in a later pipeline stage (with and without `-v`), `git grep` with and
  without a ref, over code paths and markdown paths, are not lookups; the listed real lookups still are
- [ ] ⬜ **Task 1.2**: GREEN in `handlers/pre_tool_use/lsp_enforcement.py`, reusing the existing command parsing
- [ ] ⬜ **Task 1.3**: release-notes callout, and the handler guidance if it describes these shapes

### Phase 2: Delivery

- [ ] ⬜ **Task 2.1**: targeted QA, merge, verify CI, close #169

## Success Criteria

- [ ] The new tests failed before the fix and pass after it, in both directions
- [ ] Release-bound consequence recorded: a callout in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`
- [ ] Merged to main with green CI; #169 closed

## Delivery & Milestones

- (pending)
