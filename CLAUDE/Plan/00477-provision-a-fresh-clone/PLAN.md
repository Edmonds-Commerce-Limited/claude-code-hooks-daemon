# Plan 00477: provision a fresh clone

**Status**: Not Started
**Created**: 2026-09-30
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

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

- [ ] ⬜ **Task 1.1**: Decide the key (for example `daemon.expected_version` in
  `.claude/hooks-daemon.yaml`). `install` and `upgrade` write it, config
  validation accepts it, and the config-changes manifest records it.
- [ ] ⬜ **Task 1.2**: One resolver, in bash (hooks cannot rely on the venv),
  reads the key, falls back to the `.claude/HOOKS-DAEMON.md` header for projects
  that predate it, and reports "unknown" rather than guessing.

### Phase 2: The provision command

- [ ] ⬜ **Task 2.1**: A deployed `.claude/provision.sh` (tracked in the client,
  so it exists before the daemon does) and a `hooks-daemon` skill verb
  `provision`. It clones the resolved version's tag, never `main`, builds the
  venv through the existing venv-build lock, and starts the daemon.
- [ ] ⬜ **Task 2.2**: Provision never writes a tracked file. Verify it against a
  configured fixture project: `git status` is clean afterwards. It refuses, and
  explains, when a clone is already present (pointing at `upgrade`, or at the
  Plan 00454 repair for a missing venv), and when the version is unknown.
- [ ] ⬜ **Task 2.3**: No session restart is needed after provisioning, because
  the hooks are already registered in the tracked `settings.json`. Prove it, and
  say so in the output instead of "restart your session".

### Phase 3: Loud detection

- [ ] ⬜ **Task 3.1**: `init.sh` names the state `NEEDS_PROVISION`: tracked assets
  present, no clone. The message names the expected version and the exact
  command.
- [ ] ⬜ **Task 3.2**: The human sees it: a `systemMessage` at SessionStart and on
  every UserPromptSubmit until the checkout is provisioned, and the status line
  shows it.
- [ ] ⬜ **Task 3.3**: Decide with the owner whether PreToolUse denies while the
  checkout is unprovisioned (as `ci_enabled: true` already makes it), leaving
  provision itself allowed.

### Phase 4: Docs and wording

- [ ] ⬜ **Task 4.1**: `LLM-INSTALL.md`, the skill's `install.md` and the
  troubleshooting guide route a fresh clone to `provision`, and `install.md`
  stops describing itself as the fresh-clone command.
- [ ] ⬜ **Task 4.2**: A release note and an UNRELEASED post-upgrade task: an
  upgraded project gains the config key and the tracked `provision.sh`.

## Success Criteria

- [ ] In a fresh clone of a configured fixture project, the first session shows
  the human a message naming `provision` and the expected version.
- [ ] Running provision brings up the daemon at exactly that version, with no
  restart and no change to any tracked file.
- [ ] Provision never clones `main` when the config names a version.

## Delivery & Milestones

- Plan filed from the owner's ruling on the verb and on deliberate provisioning.
