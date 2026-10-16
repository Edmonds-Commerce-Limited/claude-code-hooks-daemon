# Plan 00477: provision a fresh clone

**Status**: In Progress
**Created**: 2026-09-30
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #78

## Overview

A fresh clone of a project that uses the hooks daemon carries the tracked hook
forwarders, `.claude/init.sh`, `.claude/settings.json` and
`.claude/hooks-daemon.yaml`, but not the daemon itself: `.claude/hooks-daemon/` is
gitignored and per-checkout. Starting a session there leaves every safety handler
off, and the only sign is a `HOOKS DAEMON: Not installed` block added to the
agent's context, which the human does not see. Nothing gets the daemon running.

The route the message offers, `/hooks-daemon install`, has two defects:

1. **It installs the wrong version.** The skill downloads `install.sh` from
   `main`, and `install.sh` clones `DAEMON_BRANCH`, default `main`. The version
   the project expects is already recorded, in the header of the tracked
   `.claude/HOOKS-DAEMON.md` (`_tracked_deployed_version` in `init.sh`), but the
   installer never reads it. So the next session reports a version mismatch.
2. **The verb is wrong.** "Install" reads as adding or updating the daemon.
   What a fresh clone needs is building the local part of a daemon the project
   already uses, at the version it already uses.

**Owner ruling**: the verb is `provision`. The hooks detect when a checkout needs
provisioning and complain very loudly, with clear instructions to run it.
Provision installs the daemon version the config names. Hooks do not fetch
anything themselves: a person or agent runs provision.

## Goals

- The project's config names the daemon version it expects, explicitly.
- A `provision` command installs exactly that version into this checkout and
  starts the daemon, without changing any tracked file.
- Every hook in an unprovisioned checkout says so loudly, where the HUMAN sees it
  as well as the agent, naming the one command to run.
- `install` keeps meaning "add the daemon to a project that does not use it yet",
  and `upgrade` keeps meaning "change version".

## Non-Goals

- Automatic fetching from a hook. The owner ruled that provisioning is run
  deliberately.
- The daemon's own repository (`REPO_UNCONFIGURED`), which keeps
  `scripts/bootstrap-self-install.sh`.
- A clone present with no venv for this path (Plan 00454's state), which keeps
  the same-version upgrade and the venv self-heal. Provision may reuse that code,
  but the message for that state is not changed here.

## Tasks

### Phase 1: The expected version lives in config

- [x] ✅ **Task 1.1**: Decide the key (for example `daemon.expected_version` in
  `.claude/hooks-daemon.yaml`). `install` and `upgrade` write it, config
  validation accepts it, and the config-changes manifest records it.
- [x] ✅ **Task 1.2**: One resolver, in bash (hooks cannot rely on the venv),
  reads the key, falls back to the `.claude/HOOKS-DAEMON.md` header for projects
  that predate it, and reports "unknown" rather than guessing.

### Phase 2: The provision command

- [x] ✅ **Task 2.1**: A deployed `.claude/provision.sh` (tracked in the client,
  so it exists before the daemon does) and a `hooks-daemon` skill verb
  `provision`. It clones the resolved version's tag, never `main`, builds the
  venv through the existing venv-build lock, and starts the daemon.
- [x] ✅ **Task 2.2**: Provision never writes a tracked file. Verify it against a
  configured fixture project: `git status` is clean afterwards. It refuses, and
  explains, when a clone is already present (pointing at `upgrade`, or at the
  Plan 00454 repair for a missing venv), and when the version is unknown.
- [x] ✅ **Task 2.3**: No session restart is needed after provisioning, because
  the hooks are already registered in the tracked `settings.json`. Prove it, and
  say so in the output instead of "restart your session".

### Phase 3: Loud detection

- [x] ✅ **Task 3.1**: `init.sh` names the state `NEEDS_PROVISION`: tracked assets
  present, no clone. The message names the expected version and the exact
  command.
- [x] ✅ **Task 3.2**: The human sees it: a `systemMessage` at SessionStart and on
  every UserPromptSubmit until the checkout is provisioned, and the status line
  shows it.
- [x] ✅ **Task 3.3**: Owner ruling: whether an unprovisioned checkout blocks
  tool calls is a per-project setting. Most projects want warn, some want
  block, and the default is warn. One key in `.claude/hooks-daemon.yaml`, read
  by `init.sh` in bash without a daemon. `provision` itself is always allowed.
  Projects with `ci_enabled: true` keep today's blocking behaviour.

### Phase 4: Docs and wording

- [x] ✅ **Task 4.1**: `LLM-INSTALL.md`, the skill's `install.md` and the
  troubleshooting guide route a fresh clone to `provision`, and `install.md`
  stops describing itself as the fresh-clone command.
- [x] ✅ **Task 4.2**: A release note and an UNRELEASED post-upgrade task: an
  upgraded project gains the config key and the tracked `provision.sh`.
  (`98c7ee990`: release note 066, post-upgrade task 02)

### Phase 5: A pulled version change syncs itself (owner request)

The owner's case: someone else upgrades the project and commits, and this
checkout pulls. `daemon.expected_version` now names a version the local clone is
not at. The daemon is present and installed, just at the wrong version, so it
should be brought to the configured version and restarted, automatically where
possible.

This is a sync, not an upgrade. The upgrade already ran where it was committed:
its tracked-file migrations are in the pull. Only the per-checkout parts are
stale: the clone's checked-out tag, the venv and the running daemon.

- [x] ✅ **Task 5.1**: Detect drift: the installed clone's version differs from the
  resolved expected version. Decided: in `init.sh` by extending the Plan 00386
  mismatch path (`_detect_stale_clone` now compares the clone with
  `_resolve_expected_version`; it runs only after a failed start, so a healthy
  hook pays nothing), and at SessionStart for a running daemon in the
  `version_check` handler. Both name the versions, the source, UPGRADE or
  DOWNGRADE, and the command a human runs; neither moves the daemon.
- [x] ✅ **Task 5.2a** (#78): `provision` syncs an existing clone at the wrong
  version to the expected one, by the steps Task 5.2 names and through the target
  release's pre-deploy gate (Task 5.3). It refuses a modified clone or one with a
  foreign origin. A failure restores the previous version and restarts the old
  daemon. The drift advisories (`init.sh`, `version_check`,
  `daemon_sync_after_merge`) name `provision` rather than `upgrade` for this case.
- [ ] ⬜ **Task 5.2**: Sync in the background, never inside a hook's time budget:
  fetch exactly the tag from the fixed URL, check that its `version.py` names
  it, rebuild the venv through the clone's own build path, then restart. The
  old daemon keeps serving until the new one is ready, and a failed sync leaves
  it in place and says so loudly.
- [x] ✅ **Task 5.3**: How this meets the upgrade approval gate and its agent guard.
  Moot: on 2026-10-11 the owner had the approval tier and `upgrade_approval_guard`
  removed (Plan 00503, GitHub #112), under the careless-not-hostile threat model. A
  committed `daemon.expected_version` change is reviewed like any other commit,
  and the sync runs the target release's own pre-deploy gate, whose reading
  confirmation still applies.
- [x] ✅ **Task 5.4**: Tests: a pulled newer version syncs and restarts; a sync
  failure keeps the old daemon; the daemon's own repository never syncs.
  (`98c7ee990`, `55642216d`)

## Success Criteria

- [ ] After a pull that changes `daemon.expected_version`, the next session runs
  the daemon at the new version without a manual step.
- [x] In a fresh clone of a configured fixture project, the first session shows
  the human a message naming `provision` and the expected version
  (`test_init_sh_needs_provision.py::TestSessionStartAndUserPromptSubmit`).
- [x] Running provision brings up the daemon at exactly that version, with no
  restart and no change to any tracked file (`test_provision_sh.py::TestProvisioning`).
- [x] Provision never clones `main` when the config names a version
  (`test_installs_exactly_the_tag_the_config_names_never_main`).

## Delivery & Milestones

- Plan filed from the owner's ruling on the verb and on deliberate provisioning.
- Task 5.2a (#78): merged `57295f89c`, plus the range-QA fix `bebed359c`;
  release note 031 is in UNRELEASED.
