# Plan 00521: tdd_enforcement treats a Write over an existing file as an edit

**Status**: In Progress
**Created**: 2026-10-14
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #114

## Overview

`tdd_enforcement`'s contract covers creating a production file. The class
docstring, the rule summary, the deny message ("Cannot create … source file")
and the guidance all say "creating" or "creation". The handler never checks
whether the `Write` target already exists, though, so a `Write` that overwrites
an existing source file with no test is denied as if it created one. An `Edit`
to the same file is allowed, and an `Edit` can rewrite the file entirely, so the
denial protects nothing and only steers the agent to the other tool.

Related prior art: Plan 00261 (`R-WRITE-CLOBBER`, read-before-overwrite) is a
separate guard. It still applies to an overwrite and is unaffected.

## Goals

- A `Write` whose target is an existing regular file is outside the gate, as an
  `Edit` is.
- A `Write` that creates a new file is judged exactly as before.

## Non-Goals

- Changing how `Edit` is treated, or any test-path resolution.
- Changing `R-WRITE-CLOBBER`.

## Tasks

### Phase 1: Fix

- [ ] ⬜ **Task 1.1**: RED: a test that a `Write` over an existing production
  file with no test is allowed, and that a `Write` creating the same path is
  still denied. A symlink, a directory or a dangling path at the target counts
  as not existing.
- [ ] ⬜ **Task 1.2**: GREEN: the existence check, resolved the same way as
  the handler's other path handling (relative to the payload's working
  directory when the path is relative).
- [ ] ⬜ **Task 1.3**: Guidance (`get_claude_md`, the rule summary) says a
  `Write` that creates a file; add a release note.

## Success Criteria

- [ ] An overwrite is allowed and a creation is denied, both proven by tests
  that failed first.
- [ ] The release-bound consequence (a narrower gate) is recorded as a release
  note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00521-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed by the issue-sdlc loop from #114.
