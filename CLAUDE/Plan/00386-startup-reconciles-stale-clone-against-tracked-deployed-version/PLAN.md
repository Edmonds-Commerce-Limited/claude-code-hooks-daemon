# Plan 00386: startup reconciles stale clone against tracked deployed version

**Status**: Not Started
**GitHub Issue**: #38
**Created**: 2026-09-12
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Direct

## Overview

`.claude/hooks-daemon/` is gitignored, so the daemon clone is per-checkout. The
assets it deploys — `.claude/init.sh`, `.claude/hooks/*`, `.claude/settings.json`,
`.claude/skills/hooks-daemon/`, `.claude/hooks-daemon.yaml` and the `CLAUDE.md`
block — are TRACKED. Nothing compares the two at startup, so a stale clone loses
to committed assets from a much newer version and the daemon simply refuses to
start.

**The consequence is the reason this is High.** In the reported case a v3.15.1
clone met tracked assets deployed at v3.60.0, and every hook event for the whole
session returned `daemon_startup_failed`. Every safety handler was inactive, in
`--dangerously-skip-permissions` mode, until a human noticed. A guard that fails
silent-open is worse than no guard, because the project believes it is protected.

Three existing signals were all present and none helped, which is the part worth
keeping:

- The failure message names `logs` and `restart`. A restart cannot fix a version
  mismatch, so the advice loops forever.
- `version_check` compares the clone against the LATEST GITHUB RELEASE
  (`_get_latest_version` shells out to `git ls-remote`). It structurally cannot
  see that this project is ahead of its own clone.
- `hooks-daemon upgrade` took `from_version` from the clone, so
  `check-truth-changes --from 3.15.1` emitted 73 entries of already-reconciled
  history instead of the true 5.

**The reporter's stated blocker does not exist, and that materially shrinks the
work.** They concluded there is "no tracked marker of the version the deployed
assets came from", having grepped for `DAEMON_VERSION|daemon_version|installed_version`.
The marker is there, spelled as prose rather than as a key. `docs_generator.py`
writes this line into the tracked `.claude/HOOKS-DAEMON.md`, and `generate-docs`
runs on the upgrade path:

```text
> Generated on 2026-09-11 (v3.63.0) by `generate-docs`. Regenerate: ...
```

A parser for that exact line already ships too, in the docs-QA check that
detects hand-edits of generated documents — with the version in a capture group:

```python
r"> Generated on \d{4}-\d{2}-\d{2} \(v(\d+\.\d+\.\d+)\) by"
```

So steps 2, 4 and 5 below are implementable today with no new file format.

**The marker being TRACKED in client installs — the load-bearing assumption —
was checked rather than assumed.** `.claude/.gitignore` excludes the clone
(`/hooks-daemon/`), backups, env files, sockets, PIDs, `reports/`, caches and
venvs. `HOOKS-DAEMON.md` appears nowhere in it, so it is a tracked deployed
asset like the rest. The reporter confirms it from the other side, describing it
as "tracked but records no version either". That matters because if clients
ignored the file this approach would collapse at implementation time instead of
here.

## The open question — this is why the plan is Not Started

The issue asks for the clone to **self-update automatically** at startup. That is
an owner decision, not an implementation detail, and it is deliberately not being
taken by the triage loop:

- It has the daemon mutate its own installed version with no human in the loop,
  on a signal (a tracked marker) that any commit can change. A malicious or
  mistaken commit to `.claude/HOOKS-DAEMON.md` would become an instruction to
  check out a different daemon version.
- It runs at the one moment the project is least protected — before the daemon
  is up — so a failure mid-update leaves neither the old nor the new clone.
- The safe subset (detect, refuse, say exactly what is wrong and what to run) is
  most of the value with none of that risk. The reporter says so themselves:
  "Point 4 alone would have turned a whole unprotected session into a 30-second
  fix."

**Decision needed**: ship the loud-failure subset only, or also the self-update.

## Goals

- Startup compares the clone's version against the version the project's tracked
  assets were generated from, and never fails generically when they differ.
- A mismatch is reported with BOTH versions and the exact remedy, not `logs` /
  `restart` advice that cannot work.
- `upgrade` derives `from_version` from the tracked marker, so truth-changes and
  config-migration ranges are honest.

## Non-Goals

- Inventing a new tracked version file. One exists; use it.
- Changing what `version_check` does. Comparing against the latest GitHub release
  is a different, legitimate question — this plan adds a second comparison rather
  than repurposing the first.
- Self-updating the clone, unless the owner rules for it above.

## Tasks

### Phase 1: Owner decision

- [ ] ⬜ **Task 1.1**: Owner rules on self-update vs loud-failure-only. Nothing
  below is started until this is answered, because it decides whether Phase 3
  exists at all.

### Phase 2: Detect and report (independent of the ruling)

- [ ] ⬜ **Task 2.1**: A reusable reader for the tracked deployed version, built
  on the existing `generated_doc_hand_edit` regex rather than a second parser —
  two parsers for one line is how they drift apart.
- [ ] ⬜ **Task 2.2**: Startup compares clone version against it, and a mismatch
  produces a specific failure naming both versions and the exact command. Pinned
  by a test that asserts the message contains both versions, since a generic
  message is the defect.
- [ ] ⬜ **Task 2.3**: `upgrade` takes `from_version` from the tracked marker
  when it is present and newer than the clone, falling back to the clone
  otherwise. Covered both ways.

### Phase 3: Self-update — ONLY if the owner rules for it

- [ ] ⬜ **Task 3.1**: Scope to be written after Task 1.1. Left deliberately
  empty rather than speculatively designed.

## Success Criteria

- [ ] A clone older than the tracked deployed version produces a failure naming
  both versions and the remedy — verified by driving the real startup path, not
  only a unit test.
- [ ] `upgrade` on a stale clone computes its range from the tracked marker.
- [ ] No new tracked file format is introduced.
- [ ] Every release-bound consequence is in the pending-release holding area, or
  the plan records why it has none.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Filed from GitHub issue #38, triaged by the Plan 00384 issue-SDLC loop and
  labelled `agent-needs-human` because the headline ask is an owner decision.
- The reporter's "no tracked marker" blocker was checked and found not to hold;
  the marker and a parser for it both already exist.
