# Plan 00454: not installed message steers to destructive reinstall

**Status**: Complete
**Created**: 2026-09-23
**Owner**: dev
**GitHub Issue**: #53
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration (worktree, TDD)

## Overview

When a daemon clone is present but no venv is usable from the current project
path — the normal state the first time a bind-mounted project is opened from a
second view, host versus container — every hook injects `HOOKS DAEMON: Not installed` and points at the skill install. Following that advice **deletes
the other view's venv**:

1. `init.sh` decides installed-ness with one boolean AND (`_is_daemon_installed`:
   directory present **and** venv interpreter present), so "nothing installed"
   and "clone present, venv missing for this path" are one state.
2. The skill's `_installation_is_healthy` probe cannot pass here — the other
   view's venv either points at an interpreter this view lacks, or its
   editable-install path points at the other view's source tree.
3. On a failed probe the skill escalates to `--force` by itself
   (`skills/hooks-daemon/scripts/install.sh:149`), without asking.
4. The installer's force path runs `rm -rf "$DAEMON_DIR"` (`install.sh:72`).
   Venvs live inside it, so the other view's venv goes with it.

Because it compounds, moving between two views makes each destroy the other's
venv on every switch. The message is what steers a reader onto that path, so
it is the part to fix first.

**The safe command already exists and was built for this case.** A same-version
upgrade takes the idempotent path at `scripts/upgrade_version.sh:336`, whose
first action is `ensure_venv` — commented "concurrent environments (container
vs host, different Pythons) don't clobber each other". It deletes nothing, and
the skill's `upgrade.sh` is a shim that needs no resolved venv to run. Pinning
the upgrade to the clone's own version keeps it on that path, so it builds the
missing venv and changes nothing else.

## Goals

- `init.sh` distinguishes **clone present, venv missing for this path** from
  **nothing installed**, as its own diagnosis in the existing most-specific-first
  ladder.
- That state's message says the clone is present, names the version-pinned
  upgrade as the fix, and **explicitly warns against the install/force path**
  and why.
- `NOT_INSTALLED` keeps its current meaning and message for a genuinely absent
  clone.

## Non-Goals

- **Auto-bootstrapping a venv from a hook.** That is Plan 00100's dormant
  residue, and scheduling it is the owner's decision.
- **The `repair` gate** (`bin/hooks-daemon:93-97` resolves the venv before
  parsing any subcommand). A separate slice of #53.
- **Making the skill's force-escalation safe.** Worth doing; out of this
  slice. Recorded as a follow-up, not silently dropped.

## Tasks

### Phase 1: TDD in a worktree

- [x] ✅ **Task 1.1**: RED — integration tests, modelled on
  `tests/integration/test_init_sh_stale_clone_version.py`, driving `init.sh`
  with (a) a clone directory present and no venv, (b) no clone at all. Assert
  (a) gets the new message and NOT `Not installed`; (b) still gets
  `Not installed` unchanged. Quote the failure output.
- [x] ✅ **Task 1.2**: GREEN — add the state to the diagnosis ladder between
  `_detect_stale_clone` and `_is_daemon_installed`, and its branch in
  `emit_hook_error`, following the existing `REPO_UNCONFIGURED` /
  `VERSION_MISMATCH` pattern. Version from `_clone_version()`, which needs no
  venv.
- [x] ✅ **Task 1.3**: Cover the version-unreadable case — a clone whose
  `version.py` cannot be parsed must still get a safe message, never a blank
  version or a fall-through to the install advice.
- [x] ✅ **Task 1.4**: Full QA green; release note in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

### Phase 2: Deliver

- [x] ✅ **Task 2.1**: Merge `--no-ff`, verify ancestry and CI.
- [x] ✅ **Task 2.2**: Comment on #53 with what shipped; leave it OPEN — the
  `repair` gate and auto-bootstrap remain.

## Success Criteria

- [x] A clone-present-venv-missing checkout never shows `Not installed` and
  never names the install skill as its fix.
- [x] Its message names the version-pinned upgrade and says why install is
  unsafe here.
- [x] A genuinely absent clone is unchanged.
- [x] An unreadable clone version still yields a safe message.
- [x] Full QA passes and CI is green.
- [x] Every release-bound consequence is in the pending-release holding
  area: `UNRELEASED/release-notes/01-the-not-installed-message-no-longer-points-at-rm-rf-when-a-clone-shares-a-mount.md`

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00454-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- **Delivered**: merge `f299681f` (branch `c58cca62` → `a951f210` →
  `8c101380`), CI run 35920960803 green on all five jobs.
- **Follow-ups, still on #53**: the `repair` gate; auto-bootstrap (Plan 00100
  residue, owner's scheduling call); making the skill's force escalation safe.
