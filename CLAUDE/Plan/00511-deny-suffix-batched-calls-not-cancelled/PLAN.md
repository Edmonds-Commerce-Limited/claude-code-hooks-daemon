# Plan 00511: deny suffix batched calls not cancelled

**Status**: In Progress
**Created**: 2026-10-12
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #81

## Overview

Every PreToolUse DENY reason ends with `_DENY_CONTINUATION_SUFFIX`
(`core/hook_result.py`). The suffix says that tool calls batched with the
denied one "were CANCELLED", and tells the agent to re-issue them. Plan 00115
wrote that wording after observing cancellation. Claude Code 2.1.161 changed
the harness: parallel tool calls now return their results independently (see
the vendored changelog in `remote-docs/`).

The suffix is now false, and acting on it does harm. In the reported case, a
`git commit` batched with a denied Write ran with a stale message and was
pushed, while the agent planned to re-issue it. Triage on current `main`
reproduced the defect: a denied Write's sibling Bash call ran.

The daemon answers each PreToolUse call on its own. It can neither cancel a
sibling call nor see one, so no text it emits may assert what happened to
siblings. The same claim appears in three more places:

- the `lint_on_edit` guidance;
- the `validate_eslint_on_write` guidance;
- the handler-guidance rule in `CLAUDE/HANDLER_DEVELOPMENT.md`.

## Goals

- The DENY suffix no longer says siblings were cancelled. Instead it says they
  may already have run, so check their results before re-issuing anything. It
  keeps Plan 00115's still-valid advice: do not batch a dependent call with a
  blockable one, then adapt and continue.
- No other daemon text claims that a denial cancels sibling calls.

## Non-Goals

- Detecting or counting sibling calls; the daemon cannot see them.
- Changing which calls are denied.

## Tasks

### Phase 1: Fix

- [ ] ⬜ **Task 1.1**: RED. Write tests that fail on the current text:
  - the DENY suffix must not claim cancellation;
  - the suffix must say siblings may have run;
  - the `lint_on_edit` and `validate_eslint_on_write` guidance must make no
    cancellation claim.
- [ ] ⬜ **Task 1.2**: GREEN. Rewrite the suffix and the two handlers' guidance,
  keeping the suffix under the existing 250-character bound. Correct
  `CLAUDE/HANDLER_DEVELOPMENT.md`, regenerate the generated docs, and add a
  release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

### Phase 2: Land

- [ ] ⬜ **Task 2.1**: Review, coordinator checks, merge; comment on and close #81.

## Success Criteria

- [ ] The issue's reproduction yields a deny reason that does not claim
  cancellation.
- [ ] The release-bound consequence, the changed deny text, is in the
  pending-release holding area as a release note in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Delivery & Milestones

- Issue #81 triaged and claimed; reproduced on `main`.
