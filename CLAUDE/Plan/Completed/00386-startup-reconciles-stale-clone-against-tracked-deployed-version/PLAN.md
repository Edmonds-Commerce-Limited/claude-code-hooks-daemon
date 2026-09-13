# Plan 00386: startup reconciles stale clone against tracked deployed version

**Status**: Complete
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

### RULED — detect and advise, never self-update

The owner ruled directly: **advise loudly and name the exact command; do not
auto-upgrade or auto-restart.** So the self-update in the issue's point 3 is out
of scope, and points 1, 2, 4 and 5 — a tracked marker, the comparison, a specific
failure naming both versions, and an honest `from_version` — are the whole plan.

The owner also widened the scope in the same breath: reconciliation must run in
**both directions**. Inbound, the stale clone is brought up to the version the
tracked assets declare. Outbound, once the installed version changes, the
deployed TRACKED artefacts go stale and their regenerated diff must be surfaced
for commit rather than left drifting. The outbound half is what stops a repo
whose committed assets no longer describe the daemon actually installed.

A second trigger arrived with the ruling and is tracked separately in Plan 00389:
a `git pull` is the moment this mismatch is CREATED, so it is the cheapest place
to catch it. This plan keeps the startup detection; 00389 adds the post-pull one.
They share the tracked-marker reader, which is why Task 2.1 stays here.

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
- Self-updating the clone, or self-restarting the daemon. Ruled out by the owner
  in Task 1.1, not merely unscoped.
- Committing the regenerated tracked artefacts automatically. Phase 4 surfaces
  the diff; a human commits it.
- The post-pull trigger, which is Plan 00389. This plan owns the startup
  trigger and the shared tracked-marker reader.

## Tasks

### Phase 1: Owner decision

- [x] ✅ **Task 1.1**: RULED by the owner — detect and advise loudly naming the
  exact command; never auto-upgrade and never auto-restart. Phase 3 is therefore
  cancelled rather than scoped, and reconciliation runs in both directions (see
  the ruling above).

### Phase 2: Detect and report (independent of the ruling)

- [x] ✅ **Task 2.1**: A reusable reader for the tracked deployed version, built
  on the existing `generated_doc_hand_edit` regex rather than a second parser —
  two parsers for one line is how they drift apart.
  → `utils/deployed_version.py`; the docs-QA check now imports the pattern from
  there, and a test pins the identity.
- [x] ✅ **Task 2.2**: Startup compares clone version against it, and a mismatch
  produces a specific failure naming both versions and the exact command. Pinned
  by a test that asserts the message contains both versions, since a generic
  message is the defect.
  → `init.sh`. The check had to live in bash: the daemon cannot report its own
  absence, and a clone stale enough to fail startup often cannot resolve a venv,
  so nothing here may import the package. That forces a SECOND copy of the
  marker pattern, held to the Python one by a test that feeds both the same
  header line. Ordered BEFORE `_is_daemon_installed`, because that check needs a
  resolved interpreter and the real field case would otherwise be misreported as
  "not installed".
- [x] ✅ **Task 2.3**: `upgrade` takes `from_version` from the tracked marker
  when it is present and newer than the clone, falling back to the clone
  otherwise. Covered both ways.
  → The marker is now read first and unconditionally, not only on the
  freshly-cloned branch (which the reported case never took). The preference is
  one-directional, so it can only shrink a range a stale clone inflated. This is
  the THIRD reader of the header; a parametrised test asserts all three agree.

### Phase 3: Self-update — CANCELLED by the Task 1.1 ruling

Not deferred, cancelled. The owner ruled against a daemon that upgrades or
restarts itself, so there is nothing here to scope later. Left visible rather
than deleted so a future reader sees the option was considered and rejected,
and does not re-propose it as an obvious missing feature.

### Phase 4: Outbound — the tracked assets must not drift from what is installed

- [x] ✅ **Task 4.1**: When the installed version changes, the deployed TRACKED
  artefacts are regenerated and the resulting diff is SURFACED for commit. Not
  committed automatically: the same ruling applies, and a commit is a bigger
  side effect than a restart.
  → Mostly already shipped: `generated-doc-hand-edit`'s SWEEP half already
  detected a marker that had fallen behind the running daemon and named the
  regenerate command — verified live before changing anything. The gap was that
  it never said the result must be COMMITTED, which for a tracked artefact is
  the load-bearing half: the committed copy is what the next install deploys
  from. Trackedness is asked of git rather than inferred, so the extra sentence
  is never shown to a project whose generated doc is gitignored.
- [x] ✅ **Task 4.2**: Silent when nothing drifted. An outbound check that
  speaks on every operation is one that gets ignored, which is how the original
  `daemon_startup_failed` message failed the reporter.
  → Needed no work: the sweep already skips a doc whose marker matches and one
  with no marker at all, both pinned by pre-existing tests. Recorded as verified
  rather than ticked on assumption.

## Success Criteria

- [x] A clone older than the tracked deployed version produces a failure naming
  both versions and the remedy — verified by driving the real startup path, not
  only a unit test. A client-shaped fixture with a genuinely unresolvable venv,
  run through a real generated forwarder, reproduced the reporter's exact
  versions; the matching-version control still produced the pre-existing
  diagnosis unchanged.
- [x] `upgrade` on a stale clone computes its range from the tracked marker.
- [x] No new tracked file format is introduced.
- [x] The outbound half is covered: an installed-version change surfaces the
  regenerated tracked-asset diff, and says nothing when nothing drifted.
- [x] Nothing in this plan upgrades, restarts or commits on its own — the Task
  1.1 ruling is pinned by test, not just by prose.
- [x] Every release-bound consequence is in the pending-release holding area, or
  the plan records why it has none.
- [x] Full QA passes and CI is green — 29/29 locally, CI green at `b06cfa0a`.

## Delivery & Milestones

- Filed from GitHub issue #38, triaged by the Plan 00384 issue-SDLC loop and
  labelled `agent-needs-human` because the headline ask is an owner decision.
- The reporter's "no tracked marker" blocker was checked and found not to hold;
  the marker and a parser for it both already exist.
- Delivered at `d47ef80a` (Task 2.1, the shared reader), `d8fbe390` (Task 2.2,
  startup names both versions), `2d8d3b66` (Task 2.3, honest `from_version`) and
  `df3670d0` (Phase 4, the outbound commit instruction).
- Closed by the agent that completed it, per this project's actual policy. An
  earlier revision of this section claimed the close was gated on a human by
  `plan_workflow.close_requires_human_approval`. **That was wrong**: the key is
  `false` here and `plan_close_approval`'s `matches()` returns False before
  anything else when it is, so no status flip was ever going to be denied. The
  plan sat finished-but-open on a gate that does not exist. The misleading
  source — a generated `CLAUDE.md` rule row asserting the gate as project fact
  while it is inert — is recorded as Plan 00390 N2 rather than absorbed here.
- **Issue #38 is closed with the plan**, not before it: the reporter's
  point 3 (self-update) was deliberately NOT built, so the closing comment has
  to say so rather than imply the issue was implemented as filed.
- A PROGRESS comment is already posted on #38 (`issuecomment-5649476544`)
  covering what shipped, what was ruled out and why, and the two things found
  that the reporter did not report. It exists so the reporter is not left
  waiting on delivered work — the failure IssueSdlc.md check 5 records. Do not
  repost it; the close still needs its own comment.
