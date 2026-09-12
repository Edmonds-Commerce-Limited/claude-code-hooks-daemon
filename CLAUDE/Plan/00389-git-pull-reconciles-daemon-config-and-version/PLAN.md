# Plan 00389: git pull reconciles daemon config and version

**Status**: In Progress
**Created**: 2026-09-12
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Direct

## Overview

A `git pull` can bring in someone else's daemon changes, and the running daemon
does not notice. Two distinct failures, both silent:

- **Config or handler code changed.** The daemon caches config at startup and
  imports every handler module once at `initialise()`, never hot-reloading. A
  pull that adds a blocking handler, retunes a priority or changes an option is
  simply not in force, and nothing says so. The project believes it is protected
  by a config that is committed but not loaded.
- **The daemon VERSION changed.** The tracked assets now describe a newer daemon
  than the gitignored `.claude/hooks-daemon/` clone actually installed. That is
  GitHub issue #38's failure, which took a whole session's safety handlers
  offline under `--dangerously-skip-permissions`.

Both are the same shape as the defects this repository keeps finding: a guard
that silently stops applying is worse than no guard, because nobody is looking
for it.

**A pull is the moment the mismatch is created**, which makes it the cheapest
place to catch it — cheaper than startup, because the operation that caused it is
right there in context with the person who ran it.

## The owner's ruling constrains the design

Asked directly, the owner ruled: **advise loudly and name the exact command;
never auto-restart and never auto-upgrade.** Recorded in Plan 00386 Task 1.1 and
binding here.

That ruling is also technically the right one, which is worth stating so it is
not later read as mere caution: the daemon handles the hook request in-process, so
a daemon that restarted itself here would be killing the process that still owes
a response. A lost hook response is a failed hook, and a failed hook can block
the user's tool call — trading a silent staleness bug for a loud breakage.

The owner also asked for reconciliation in **both directions**: inbound, the
clone is brought up to what the tracked assets declare; outbound, once the
installed version changes, the deployed tracked artefacts go stale and their
regenerated diff must be surfaced for commit.

## Prior art this must reuse, not re-invent

`merge_qa_report` (Plan 00373) already solves the hard half. It matches
`git merge|pull|rebase` through `ENV_PREFIX`/`GIT_INVOCATION` with shell
segmentation, then uses `git diff --name-only ORIG_HEAD HEAD` to name exactly
what THIS operation introduced — deliberately, so pre-existing drift is not
re-surfaced on every pull, which is the noise failure that gets an advisory
ignored.

Both handlers need that trigger, so it is EXTRACTED to a shared helper rather
than copied. Two copies of a command-evasion pattern is precisely the drift this
project's docs-SSoT rules exist to prevent, and the security-relevant half
(segment splitting, env-prefix tolerance) is the half that must never diverge.

The version marker also already exists and needs no new file format:
`docs_generator.py` writes `> Generated on {date} (v{version}) by generate-docs`
into the tracked `.claude/HOOKS-DAEMON.md`, and
`docs_qa/checks/generated_doc_hand_edit.py` already carries a regex that captures
that version. Plan 00386 Task 2.1 owns turning that into a shared reader; this
plan consumes it.

## Goals

- A pull that changes daemon config or handler code produces a specific advisory
  naming what changed and the exact restart command.
- A pull that changes the daemon version produces a specific advisory naming BOTH
  versions and the exact upgrade command.
- After a version change, the outbound drift — regenerated tracked artefacts —
  is surfaced for commit.
- Silence when the pull touched nothing the daemon cares about.

## Non-Goals

- Restarting or upgrading anything automatically. Ruled out by the owner.
- Committing the regenerated artefacts. The diff is surfaced; a human commits it.
- Catching a pull run OUTSIDE this session, in another terminal. That needs a
  fingerprint compared per request, which is Plan 00386's startup trigger and a
  different mechanism; this plan owns the in-session operation only. Recorded so
  the gap is known rather than assumed covered.
- Changing what `version_check` does — it compares against the latest GitHub
  release, which is a different question.

## Tasks

### Phase 1: Share the trigger, then advise on config drift

- [x] ✅ **Task 1.1**: Extract the merge/pull/rebase detection and the
  `ORIG_HEAD..HEAD` changed-path query out of `merge_qa_report` into a shared
  helper, with `merge_qa_report` re-pointed at it and its tests still passing
  unchanged. Behaviour-preserving refactor first, new behaviour second.
  → `utils/merge_scope.py`; `merge_qa_report`'s 29 tests passed unchanged, and
  15 new tests pin the boundaries the old ones left implicit (`git pullimaginary`
  is not `git pull`; `project-handlers-old/` is not under `project-handlers`).
- [x] ✅ **Task 1.2**: A new advisory handler matching the same operations,
  reporting when the changed paths include the daemon config or handler code.
  Must name WHICH paths changed — an advisory that says "config changed"
  without saying what is one a reader cannot act on.
  → `handlers/post_tool_use/daemon_sync_after_merge.py`, priority 35.
- [x] ✅ **Task 1.3**: Silent when nothing relevant changed, pinned by test.
  This handler runs on every pull, so the quiet path is the common one.

### Phase 2: Version drift, inbound

- [x] ✅ **Task 2.1**: Consume Plan 00386's tracked-version reader; if the pull
  changed the marker and the tracked version differs from the running one,
  advise with BOTH versions and the upgrade command.
  → `utils/deployed_version.py`. The pattern was already in
  `docs_qa/checks/generated_doc_hand_edit.py`; it MOVED there rather than being
  copied, and a test pins the identity so a re-introduced local copy fails loudly.
- [x] ✅ **Task 2.2**: Do not confuse "marker file changed" with "version
  changed" — a regenerated marker whose version is identical must stay silent.
  The marker is rewritten on every upgrade, so the file changing is the common
  case and conflating the two would advise upgrading to the installed version.

### Phase 3: Version drift, outbound

- [x] ✅ **Task 3.1**: When the installed version changes, surface the
  regenerated tracked-artefact diff for commit, so the repository does not keep
  describing a daemon it no longer has. Carried by the version section's closing
  line rather than a separate advisory: the two directions are one story to the
  reader, and splitting them would produce two messages about one pull.

## Success Criteria

- [x] A pull changing `.claude/hooks-daemon.yaml` advises a restart and names the
  file; a pull changing nothing relevant says nothing.
- [x] A pull changing the tracked version marker to a different version advises
  an upgrade naming both versions; an identical version stays silent.
- [x] Nothing restarts, upgrades or commits automatically — pinned by test, not
  prose (`TestNeverActsOnItsOwn` asserts `subprocess.run` is never called).
- [x] `merge_qa_report`'s existing tests pass unchanged after the extraction,
  proving the refactor was behaviour-preserving.
- [x] Every release-bound consequence is in the pending-release holding area.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Requested by the owner: "when a git pull brings in hooks daemon config changes,
  we should ensure hooks daemon is restarted", and "when git pull brings in new
  hooks daemon version — we need to ensure the tracked repo is updated as well".
- Sibling of Plan 00386, which owns the startup trigger and the shared
  tracked-version reader. Same defect, two moments to catch it.
