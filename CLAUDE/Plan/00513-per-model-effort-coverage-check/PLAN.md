# Plan 00513: per model effort coverage check

**Status**: Not Started
**Created**: 2026-10-12
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #87

## Overview

Claude Code sets effort per model in `settings.json` under `modelSettings`. An entry names ONE canonical model ID; there
is no family, prefix or wildcard key. A model with no entry therefore runs at its own default effort, and those defaults
differ between releases. This was established as the effort mechanism in ledger 00466 N47 and the v3.67.0 truth-change,
which supersede the older statement in Plan 00278's Decision 4 that no per-model effort setting exists.

The `Effort Source` check in `optimal_config_checker` looks only for PINS (`CLAUDE_CODE_EFFORT_LEVEL`, or a top-level
`effortLevel` in the project or local settings file). It has no notion of which models are covered, so an owner who
lists some point releases, or none, gets no signal that the rest run at their defaults. That bites when Claude Code moves
a session onto a model the owner did not list: a fallback, a downgrade, or a newly released version.

Issue #87 proposes a presence-only coverage check: list every effort-capable model with no explicit level, by canonical
ID, with the JSON to add, and never recommend a level. That needs a maintained table of effort-capable model IDs, which
is the cost this plan exists to decide on. The separate defect #87 also reported, that the check's OK text claims
`modelSettings` provides levels without reading it, is not part of this plan: it is ledger 00474 N439, fixed on its own.

## Owner Decisions Needed

The issue-sdlc runbook treats a feature request as needing a human decision. The coordinator has not ruled on these.

1. **Build it at all?** The check is only as good as its model table. Every model release then needs a table update,
   which falls to whoever cuts a release. The alternative is to do nothing beyond N439's truthful OK text.
2. **Where the model table comes from.** It could be a hand-maintained table in the daemon, updated through release
   notes, or a list derived from a source Claude Code itself publishes, if one exists (not yet verified).
3. **Scope options.** These are the version floor (#87 suggests the current and previous major generations, or an
   explicit `min_version`), family include/exclude, and extra IDs for gateway-only models.
4. **Surface.** It could appear in `hooks-daemon check` only, or also as a SessionStart advisory, which costs a line of
   context in every session.
5. **The v3.66-to-v3.67 post-upgrade task 03** lists three fixed `modelSettings` entries for ccy supervisor effort.
   Should it point at the coverage report instead?

## Goals

- An owner can see, in one place, which effort-capable models have no explicit level.
- The check states presence only and never recommends a level, keeping the existing stance.

## Non-Goals

- Recommending, setting or injecting any effort level (the ccy supervisor injects none, per release note 067 of v3.67.0).
- Fixing the Effort Source OK text (ledger 00474 N439).

## Tasks

### Phase 0: Owner decisions

- [ ] ⬜ **Task 0.1**: The owner answers the questions under Owner Decisions Needed.

### Phase 1: Coverage check (only if Task 0.1 says build it)

- [ ] ⬜ **Task 1.1**: Model table per the owner's answer to question 2, with tests.
- [ ] ⬜ **Task 1.2**: Coverage check over project, local and user settings `modelSettings` plus a non-pinning top-level
  `effortLevel`, with tests written red first.
- [ ] ⬜ **Task 1.3**: Surface it per question 4; update post-upgrade guidance per question 5.

## Success Criteria

- [ ] The owner's decisions are recorded in this plan's JOURNAL/.
- [ ] If built: with no `modelSettings`, the check names every in-scope effort-capable model; with a partial
  `modelSettings`, it names exactly the uncovered ones.
- [ ] Release-bound consequences are in the UNRELEASED holding area (a release note for the new check), or this plan
  records that it has none because the owner declined it.

## Delivery & Milestones

- Filed from GitHub #87 by the coordinator; awaiting owner decisions.
