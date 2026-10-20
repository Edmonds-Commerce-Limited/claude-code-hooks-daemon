# Plan 00541: stale key advisory names orphaned transcripts dir

**Status**: In Progress
**Created**: 2026-10-20
**Owner**: dev
**Priority**: Medium
**GitHub Issue**: #52
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Issue #52, part 1 only. The `transcript_archiver` handler was removed in Plan 00233 (v3.53.0). It left
`untracked/transcripts/` on disk, and nothing prunes it. The disk-reclaim action is documented in
`docs/guides/HANDLER_REFERENCE.md` and in the v3.53.0 upgrade manifests. But a project that crosses
v3.53.0 later, as part of a larger version jump, never reads those manifests. It sees only the
stale-key advisory, which fires on every migration check while the key stays in the config. That
advisory (the `transcript_archiver` entry in `src/claude_code_hooks_daemon/constants/handlers.py`)
ends "Safe to delete this key from your config.", so it reads as nothing to do.

The fix puts the reclaim fact on the surface that keeps firing. The advisory text names
`untracked/transcripts/` and tells the user to delete it to reclaim the disk, matching the
HANDLER_REFERENCE wording.

An owner was absent, so the stand-in chose to proceed on this part, which the loop had already
triaged as actionable on 2026-09-22. The ruling is in this plan's JOURNAL/.

## Goals

- The `transcript_archiver` stale-key advisory names `untracked/transcripts/`, says those archives
  are copies of transcripts the user still has, and says to delete the directory to reclaim the disk.

## Non-Goals

- Part 2 of #52, where the upgrader reports the directory's size and file count. That makes a config
  check stat the filesystem, a design call left to the owner; #52 keeps `agent-needs-human` for it.
- Pruning `untracked/transcripts/` automatically.

## Tasks

### Phase 1: Fix

- [x] ✅ **Task 1.1**: A red test that the advisory text names `untracked/transcripts/` and the delete
  action. Then the text change.

### Phase 2: Close out

- [x] ✅ **Task 2.1**: A release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Success Criteria

- [ ] The new test failed before the change and passes after it.
- [ ] The release note is in the pending-release holding area
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.
- [ ] Targeted QA is green on the merged head, and CI is green.

## Delivery & Milestones

- <!-- delivery commit hashes -->
