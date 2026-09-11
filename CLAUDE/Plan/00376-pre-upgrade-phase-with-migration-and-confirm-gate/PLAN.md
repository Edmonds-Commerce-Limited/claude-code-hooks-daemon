# Plan 00376: pre upgrade phase with migration and confirm gate

**Status**: Not Started
**Created**: 2026-09-11
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A pre-upgrade phase already exists — Plan 00062 built it — but it validates
only the user's CONFIG, and the confirmation gate it added never fires for an
agent. So an upgrade still tells a project what its SOURCE must change only
after the change has landed, and no agent ever reaches a decision point. This
plan extends that phase rather than inventing one.

**Prior art, and the reason this is an extension**: Plan 00062 ("Breaking
Changes Lifecycle", Complete) delivered `install/upgrade_compatibility.py`
(its Phase 4) and the "confirm you have read the breaking-change docs" gate
(its goal 6). Its Non-Goal — "Automatic config migration (too risky — user
confirmation required)" — is upheld here: detection and proposal, never silent
rewriting.

**The bootstrapping constraint does NOT apply, verified.** It is natural to
assume pre-upgrade instructions cannot be read before install because they ship
with the incoming version. That is false here: `scripts/upgrade.sh` Step 6
("Land the daemon dir on the target version FIRST (before Layer 2)") checks out
the target, and Step 8 then delegates to `$DAEMON_DIR/scripts/upgrade_version.sh`
— the NEW version's script. The whole incoming tree, including its upgrade
manifests, is readable before anything is deployed; the existing compat check
already relies on this, reading the new `CHANGELOG.md` from `$DAEMON_DIR`.
"Pre-upgrade" here means pre-DEPLOY, not pre-fetch.

Three measured facts drive the remaining work:

- **The one confirmation gate that exists is dead for agents.** Step 5a of
  `scripts/upgrade_version.sh:733-861` prints "REQUIRED READING" and asks
  yes/no — but `:808` tests `[ ! -t 0 ]` and, on any non-interactive stdin,
  falls through at `:814` to "Review upgrade guides after upgrade". Every
  agent-driven upgrade takes that branch. The gate protects humans at a
  terminal and nobody else.
- **It would not be pre-install even if it fired.** Layer 1 checks the new
  version out at `scripts/upgrade.sh:550`, then delegates to Layer 2 at
  `:608-629`. By the time Step 5a runs, the new code is already on disk.
- **`post-upgrade-tasks/` is a dead letter box.** Its own README states
  (`CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/README.md:20`) "There is no
  runner. Nothing executes these tasks automatically." Nothing in the upgrade
  path reads it, `.claude/skills/hooks-daemon/upgrade.md` never mentions it,
  and unlike `release-notes/` it has no schema test. Plans are required to
  write tasks there as part of their definition of done; those tasks are then
  read by nobody.

The motivating change is Plan 00375, which renames a public CLI JSON key. The
owner's ruling is that deprecation windows are not the answer — they are delay,
they make the defect correct by policy for a release, and they do not avoid the
break. The alternative is that the upgrade **migrates the consumer** instead of
announcing to it, which this system is uniquely placed to do: the daemon is
installed inside the consumer's repository and upgraded by an agent with full
read/write access to it. That is a codemod, except the migrator can read intent
rather than only matching syntax.

## Goals

- A pre-upgrade phase that runs BEFORE the new version is on disk, and states
  what the incoming version will change.
- Migration tasks that are **detected and applied**, not announced: scan the
  target project for affected call sites and report them with file:line.
- An explicit proceed/abort gate that works for an AGENT (non-interactive), not
  only for a human at a TTY, with escalation to the owner when the change
  warrants it.
- Proper semver: a breaking change is declared MAJOR and carries its migration,
  rather than being softened into a window.

## Non-Goals

- Auto-applying migrations without the gate. Detection and proposal come first;
  silent rewriting of a user's repository is exactly the failure mode this must
  not introduce.
- Replacing `post-upgrade-tasks/`. Some work genuinely can only happen after
  install; that surface stays, and is fixed separately rather than merged in.
- Covering consumers outside the upgraded repository. A local scan cannot see
  them; release notes remain their only channel and that is accepted.

## Tasks

### Phase 1: Establish where the phase runs

- [ ] ⬜ **Task 1.1**: Site the phase alongside the existing compat check in
  Layer 2 (`scripts/upgrade_version.sh`, around the pre-install checks at
  `:511` and compat at `:536-603`), which is already after checkout and before
  any deploy. No new fetch mechanism is required — see the Overview.
- [ ] ⬜ **Task 1.2**: Characterise what "abort" must undo at that point. The
  daemon dir is ALREADY on the target checkout (`upgrade.sh:550`) while nothing
  has been deployed — so an abort is not free, and the plan must define whether
  it restores the previous ref or documents the daemon dir as intentionally
  moved.

### Phase 2: The `pre-upgrade-tasks/` surface

- [ ] ⬜ **Task 2.1**: Add `CLAUDE/UPGRADES/UNRELEASED/pre-upgrade-tasks/` as a
  peer of `post-upgrade-tasks/`, with a README stating the schema.
- [ ] ⬜ **Task 2.2**: Give it a **detection contract** — a task declares how
  to find affected call sites (a pattern to scan for), not only prose. This is
  what makes it silent when a project is unaffected, which is the property that
  keeps agents reading it rather than skimming it.
- [ ] ⬜ **Task 2.3**: A schema test over the real holding area, mirroring
  `tests/integration/test_pending_release_notes_holding_area.py`, so a
  malformed task fails CI at the plan's commit rather than at upgrade time.
- [ ] ⬜ **Task 2.4**: Wire it into the release skill's UNRELEASED move, which
  currently handles four shapes and must handle five.

### Phase 3: The gate that works for agents

- [ ] ⬜ **Task 3.1**: Replace the TTY-only gate. A non-interactive caller must
  get a real decision point, not a silent fall-through — the current `[ ! -t 0 ]`
  branch at `upgrade_version.sh:808` is the bug to fix, not the pattern to copy.
- [ ] ⬜ **Task 3.2**: Define escalation: which changes an agent may accept on
  its own, and which require the owner. Breaking/MAJOR is the obvious
  escalation trigger. Reuse the existing one-shot approval-marker mechanism
  (`utils/one_shot_approval`, as used by `approve-plan-close` and
  `approve-merge`) rather than inventing a second idiom.
- [ ] ⬜ **Task 3.3**: An abort must leave the install in a state the next run
  can proceed from, per Task 1.2 — the checkout has already happened, so
  "untouched" is not achievable without an explicit restore.

### Phase 4: Fix what the survey exposed

- [ ] ⬜ **Task 4.1**: `post-upgrade-tasks/` has no runner and no schema test.
  Either give it both or stop requiring plans to write into it; a surface that
  plans are obliged to feed and nothing reads is worse than no surface.
- [ ] ⬜ **Task 4.2**: `install/upgrade_compatibility.py:351-373` scans only
  `CLAUDE/UPGRADES/v{major}/` and never `UNRELEASED/`, so unreleased breaking
  changes are invisible to compatibility checking.
- [ ] ⬜ **Task 4.3**: `.claude/skills/hooks-daemon/upgrade.md` never mentions
  post-upgrade tasks; the agent-facing upgrade procedure omits the step.

### Phase 5: Prove it on Plan 00375

- [ ] ⬜ **Task 5.1**: Ship 00375's `level` → `severity` rename as the first
  real pre-upgrade migration: detect call sites, propose the rewrite, gate on
  approval because it is MAJOR.

## Success Criteria

- [ ] An agent upgrading to a version with breaking changes is told what will
  break BEFORE anything is installed.
- [ ] A project with no affected call sites hears nothing — silence is the
  default, so the signal stays worth reading.
- [ ] A project WITH affected call sites gets them named at file:line.
- [ ] The proceed/abort gate fires for a non-interactive agent, and aborting
  leaves no partial install.
- [ ] Plan 00375's rename ships through this path rather than through a
  deprecation window.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Motivated by Plan 00375 and the owner's ruling against deprecation windows:
  "i dont like delay - its over complex".
