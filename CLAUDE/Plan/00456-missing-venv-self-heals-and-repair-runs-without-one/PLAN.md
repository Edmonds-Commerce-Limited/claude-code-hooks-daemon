# Plan 00456: missing venv self heals and repair runs without one

**Status**: In Progress
**Created**: 2026-09-24
**Owner**: dev
**GitHub Issue**: #53
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration (worktree, TDD)

## Overview

Sometimes the daemon clone is present but has no venv for the current project
path, for example on a host and a container that share one mount. #53
reported the first session in a new environment in that state. Plan 00454
fixed the misleading message. Three defects remain, and each one leaves the
user with no safe way forward:

1. **`repair` cannot run without a venv.** `bin/hooks-daemon` resolves the
   venv before it parses any subcommand, so every verb exits 5 when there is
   no venv. That includes `repair`, the verb whose whole job is to fix this.
2. **The documented self-heal was never wired.** `SELF_INSTALL.md` promises
   that the daemon "auto-detects stamp mismatches and rebuilds on first use
   in a new environment". Nothing on the hook path builds a venv. The design
   and the owner directive already exist: Plan 00100 Decision 9 (bootstrap
   automatically when the five `can_inline_bootstrap` conditions hold,
   otherwise give guided advice). That plan's Phase 3.5 was left as residue.
   The check function exists (`daemon/paths.py`), and so does the lock it
   depends on (Phase 4, `acquire_venv_lock` in `scripts/install/venv.sh`).
3. **The skill destroys the other environment's venv.** When its health
   probe fails, the hooks-daemon skill's `install.sh` escalates to `--force`
   on its own ("Repairing now (equivalent to --force)"). The force path
   deletes the whole daemon directory, including every other environment's
   `untracked/venv-*`. In the state #53 describes, the probe cannot pass, so
   following the advice has each environment wipe the other's venv every
   time the user switches between them.

**The build runs in the background, not in the hook.** Plan 00100 specified
an inline build with a 180s ceiling. `PreToolUse` and `PostToolUse` hooks
here have a 60s timeout, so a build inside the hook would be killed partway
through. So the hook starts `ensure_venv` detached, holding the existing
venv lock (a second concurrent hook finds the lock held and does not start
another build). It then returns immediately, saying a build is in progress
and naming its log. When the build finishes, the next hook starts the daemon
as normal.

## Goals

- In the #53 state, with the five conditions met, hooks start a single
  background build for this path. Once it finishes, the daemon starts with
  no manual step and no other environment's venv touched.
- With any condition unmet, nothing is changed, and the message names each
  failed condition and how to fix it.
- `bin/hooks-daemon repair` builds the missing venv for this path before
  any venv is resolved, then continues to the normal repair.
- The skill never escalates to `--force` by itself. In the #53 state it
  repairs the venv in place. An explicit `--force` keeps every other
  environment's `untracked/venv-*`.
- `SELF_INSTALL.md`'s self-heal claim is true.

## Non-Goals

- Plan 00100's other residue: Phase 5 (an end-to-end upgrade-cycle
  acceptance test) and Phase 6. Those are test infrastructure and
  documentation, not defects. They stay in 00100.
- Changing the "nothing installed" path. With no clone, the install advice
  is still the right advice.

## Tasks

### Phase 1: TDD in a worktree

- [x] ✅ **Task 1.1**: `repair` works before venv resolution in
  `bin/hooks-daemon`. With no venv for this path, it runs `ensure_venv`
  (under the lock), then continues to the Python repair. With a venv
  present, nothing changes. Precedent: Plan 00431 moved a preflight ahead of
  venv resolution.
- [x] ✅ **Task 1.2**: Background bootstrap from `init.sh`'s venv-missing
  branch, gated on the five conditions. A detached build under the venv
  lock; while the lock is held, no second build starts. The hook returns
  within its timeout with a "building, log at …" message. On a failed
  build, the next hook reports the failure and its log rather than
  retrying in a loop.
- [x] ✅ **Task 1.3**: Guided fallback when any condition fails, with zero
  changes made. Each failed condition is named with its fix, extending the
  existing venv-missing message rather than adding a second one. Decide
  whether Plan 00100's separate SessionStart `venv_missing_advisor` handler
  is still needed, given that this message already reaches the session, and
  record the decision.
- [x] ✅ **Task 1.4**: The skill's `install.sh` stops escalating to
  `--force` by itself. With a clone present and a readable version, it
  repairs the venv in place. An explicit `--force` keeps other
  environments' `untracked/venv-*`. The same change goes in the deployed
  copy (`.claude/skills/hooks-daemon/scripts/install.sh`) and its template
  (`src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/install.sh`).
- [x] ✅ **Task 1.5**: Docs: `SELF_INSTALL.md`'s self-heal claim, the
  venv-missing guidance, and a release note. Full QA green.

### Phase 2: Deliver

- [ ] ⬜ **Task 2.1**: Merge `--no-ff`, verify ancestry and CI, restart the
  daemon.
- [ ] ⬜ **Task 2.2**: Mark Plan 00100's Phase 3.5 as carried here, comment
  on #53 and close it.

## Success Criteria

- [x] Integration test: a clone with no venv for the path, a fake `uv`,
  and all five conditions met. A hook starts exactly one build, even with
  concurrent hooks. The next hook after it finishes starts the daemon. A
  second environment's `venv-*` is byte-for-byte untouched.
  (`tests/integration/test_init_sh_venv_self_heal.py`,
  `tests/integration/test_venv_bootstrap_driver.py`)
- [x] Integration test: with `uv` missing, a hook changes nothing, names
  the missing condition, and never suggests install or `--force`.
- [x] Integration test: `bin/hooks-daemon repair` with no venv builds one
  and does not exit 5.
  (`tests/integration/test_bin_hooks_daemon_repair_without_venv.py`)
- [x] Test: the skill's `install.sh` never escalates to `--force` without
  the flag, and a flagged `--force` keeps another environment's `venv-*`.
  (`tests/integration/test_skill_install_never_auto_forces.py`)
- [x] Full QA passes and CI is green. (`llm_qa.py all` gave 36/36 on the
  merged branch head `17024e79`; the branch CI is confirmed at the Task 2.1
  merge.)
- [x] Every release-bound consequence is in the pending-release holding
  area: `UNRELEASED/release-notes/06-a-missing-venv-now-builds-itself-and-repair-works-without-one.md`
  (no post-upgrade task: nothing an upgrading client must act on).

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00456-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Not yet delivered.
