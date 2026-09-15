# Plan 00410: gitignore swallows deployed assets

**Status**: Not Started
**Created**: 2026-09-15
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

A `.gitignore` pattern with no leading slash is UNANCHORED: git matches it at
every depth below the file's directory, not just beside it. So
`hooks-daemon/` in `.claude/.gitignore`, written to exclude the installed
clone at `.claude/hooks-daemon/`, also swallows `.claude/skills/hooks-daemon/`
— the DEPLOYED skill tree, which must be tracked. Both directions were
verified with `git check-ignore` rather than reasoned about:

| pattern in `.claude/.gitignore` | `.claude/skills/hooks-daemon/` (deployed, must be tracked) | `.claude/hooks-daemon/` (clone, must be ignored) |
| ------------------------------- | ---------------------------------------------------------- | ------------------------------------------------ |
| `hooks-daemon/`                 | IGNORED — the defect                                       | ignored, as intended                             |
| `/hooks-daemon/`                | not ignored                                                | ignored, as intended                             |

This repository is not affected: `.claude/.gitignore` already carries the
anchored `/hooks-daemon/` with a comment explaining why the slash is
load-bearing. The installer is not affected either — it writes
`hooks-daemon/untracked/` and `.claude/hooks-daemon/`, and an internal slash
anchors a pattern just as a leading one does.

What is missing is DETECTION. A client who hand-wrote the pattern, or who
installed before the fix, still has it and nothing tells them. The failure is
silent by construction: a file git ignores cannot drift visibly, which is
exactly how a deployed `troubleshooting.md` kept a path its source had already
moved off (found by Plan 00336 Task 4.3, diagnosed by Plan 00338). Neither of
those plans built a check, so the class recurs unannounced.

## Goals

- A project is told when any path the daemon DEPLOYS is ignored by git,
  naming the `.gitignore` file, line number and pattern responsible, and the
  anchored form that fixes it.
- The detection asks git (`git check-ignore -v`) rather than parsing
  patterns, so every spelling of the mistake is caught — not just this one.
- It is reachable the two ways a user would meet it: `hooks-daemon check` and
  an upgrade, plus SessionStart where the sibling check already lives.

## Non-Goals

- Editing a project's `.gitignore` automatically. The advisory names the file,
  the line and the replacement; a project's ignore rules are the project's.
  An auto-fix that guessed wrong would un-ignore something deliberately
  hidden, which is the worse failure of the two.

- Re-checking that required paths ARE ignored. `gitignore_safety_checker`
  already does that direction, and this plan adds the reverse to it rather
  than starting a second handler with an overlapping name.

## Tasks

### Phase 1: Detection

- [ ] ⬜ **Task 1.1**: Failing tests first. A fixture repo whose
  `.claude/.gitignore` carries the unanchored pattern must report the deployed
  skill tree as swallowed, with the offending file/line/pattern; the anchored
  spelling must report nothing; a project with no git repository, and one with
  no `.gitignore` at all, must both stay silent rather than error.

- [ ] ⬜ **Task 1.2**: Implement the check against the `client_owned_assets`
  manifest, which already lists every `deployed_to` path and exists to be
  consumed. Use `git check-ignore -v --no-index` over those paths in one batch
  rather than a call per asset.

  A deployed path that is ignored BUT already tracked is a different, weaker
  finding: git tracks it regardless, so today's file is fine and the bite
  comes on a fresh clone or when an upgrade adds a NEW file beside it. Report
  both, worded differently — conflating them would either cry wolf or
  under-state a live hole.

### Phase 2: The three surfaces

- [ ] ⬜ **Task 2.1**: Add the reverse direction to the SessionStart
  `gitignore_safety_checker`, reusing its content-hash cache so the cost stays
  at one check per gitignore change rather than one per session.

- [ ] ⬜ **Task 2.2**: Surface it in `hooks-daemon check`, which already
  reuses the SessionStart handlers' own logic specifically so there is a
  single source of truth.

- [ ] ⬜ **Task 2.3**: Surface it during upgrade, after assets are deployed —
  the moment the daemon has just written files that an ignore rule may be
  hiding.

## Success Criteria

- [ ] ⬜ A project carrying the unanchored pattern is told, by all three
  surfaces, which deployed paths are hidden and which `.gitignore` line hides
  them.

- [ ] ⬜ A correctly anchored project is told nothing, on all three surfaces.

- [ ] ⬜ Full QA passes, the daemon is restarted, and CI is green.

## Delivery & Milestones

- Reported by the owner from a client project, with the mechanism correctly
  diagnosed in the report: the pattern is not anchored to the `.claude`
  folder, so it matches any folder of that name. Confirmed by probe before any
  code was read.

- Prior art, neither of which built detection: Plan 00336 Task 4.3 anchored
  this repository's own pattern; Plan 00338 diagnosed the consequence. A
  dedupe scout over 23 live and 224 archived plans found no overlap.
