# Plan 00360: pending release notes holding area

**Status**: Not Started
**Created**: 2026-09-08
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

The owner ruled that a plan is done when its work is merged into main, and
that a release is never part of a plan's definition of done (now locked into
`CLAUDE/core/PlanWorkflow.core.md`, "Definition of done"). Two plans had sat
`In Progress` for weeks with nothing left but "run `/release`" and "release
notes must mention X"; both closed on the ruling.

The second of those two items exposes a real gap. `CLAUDE/UPGRADES/UNRELEASED/`
is already a pending-release holding area, but only for three shapes:
`post-upgrade-tasks/`, `truth-changes/` and `config-changes/`. There is nowhere
for a plan to leave **release-notes prose** — the "call out the host-a scenario
so operators know the upgrade resolves it" kind of sentence. Today that
sentence is either written at release time from the commit log (and lost if
the releaser does not know the story) or smuggled into a plan as a
release-gated task (which is what the ruling forbids).

The owner's suggestion: a holding area for pending release notes, so that a
plan **completes by writing its note there**, and the release consumes the
area mechanically. This plan adds that fourth shape and wires the release
pipeline to fold it in.

## Goals

- A plan whose change is release-noteworthy can finish by dropping a short
  note into the holding area, as an ordinary merged task.
- The release pipeline folds every pending note into `RELEASES/vX.Y.Z.md`
  and empties the area, in the same BLOCKING style as Step 6 handles
  post-upgrade tasks — a note left behind aborts the release.
- The slate-clean check reports pending notes as information (what this
  release will say), never as a blocker.

## Non-Goals

- **Not** generating release notes from the holding area alone. The changelog
  and commit history stay the primary source; the notes are the human-written
  callouts that the log cannot supply.
- **Not** retro-filling notes for already-released versions.
- **Not** a new handler. This is a directory convention, a README schema and
  two pipeline steps.

## Tasks

### Phase 1: The holding area

- [ ] ⬜ **Task 1.1**: Create `CLAUDE/UPGRADES/UNRELEASED/release-notes/` with
  a README defining the file schema: one `NN-<slug>.md` per note, a `Plan:`
  and `Audience:` header (operators / handler authors / client projects), and
  a body of one to three sentences written in the voice of the release notes.
  Update `UNRELEASED/README.md` to name the fourth directory.

- [ ] ⬜ **Task 1.2**: Seed the first note from Plan 00110's struck Task 7.2
  (the host-a scenario), so the area is exercised on the very next release.

### Phase 2: The release consumes it

- [ ] ⬜ **Task 2.1**: RELEASING.md Step 5 (Release Notes Creation): the agent
  reads every note in the area and folds each into the notes under a
  "Highlights" (or audience-matching) section. Step 6 gains a sibling
  BLOCKING check: the directory must hold only its README once the notes are
  written, moved with `git mv` into the versioned upgrade guide beside the
  post-upgrade tasks so provenance survives.

- [ ] ⬜ **Task 2.2**: The release agent definition and the release skill's
  `invoke.sh` name the new directory where they name `post-upgrade-tasks/`,
  so the procedure is not only in RELEASING.md.

- [ ] ⬜ **Task 2.3**: `release-slate-check` prints the pending notes under
  an informational heading ("This release will say"), with no effect on the
  exit code.

### Phase 3: Verify

- [ ] ⬜ **Task 3.1**: A test asserts the release-notes directory holds only
  its README on main after a release (the same shape as the post-upgrade-tasks
  check), and the slate-check test covers the informational listing.

- [ ] ⬜ **Task 3.2**: Full QA green, daemon restart RUNNING.

## Success Criteria

- [ ] A plan can close with a note in the holding area and nothing waiting on
  a release
- [ ] A release with a pending note cannot complete without folding it in
- [ ] The slate check shows pending notes without changing its verdict

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00360-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed from the owner's suggestion during the plan clean-up that followed
  the definition-of-done ruling.
