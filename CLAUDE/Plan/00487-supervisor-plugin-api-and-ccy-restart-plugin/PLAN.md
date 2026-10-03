# Plan 00487: Supervisor plugin API and the ccy restart plugin

**Status**: Not Started
**Created**: 2026-10-03
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #71

## Overview

The ccy supervisor (`.claude/ccy/claude-supervise.py`, shipped by this repository) builds in every behaviour it has. A launcher that needs one more behaviour has to ask for a feature that belongs to the launcher, not the supervisor. This plan adds a small plugin API to the supervisor. It also writes the first consumer, a ccy plugin that lives in the fedora-desktop repository. Both sides are tracked here, by owner ruling (2026-10-03).

The ccy plugin covers two features from LongTermSupport/fedora-desktop#61:

- **Maximum session age.** Past a set age, the plugin warns the session that a restart is coming, then restarts it at the next idle point. The restarted `claude` comes back on the current Claude Code version, and the supervisor tells it so.
- **Time-bounded sessions** (`--run-for` / `--until`). At the deadline the plugin sends a "finish the unit, commit, push, write a hand-off" message.

The design source is the owner-ruled draft in fedora-desktop Plan 00146: `CLAUDE/Plan/00146-ccy-token-switch-through-the-supervisor/UPSTREAM-REQUEST-supervisor-plugins-draft.md`. #71 and its comment record where it differs from the issue summary. The draft's rulings:

- Plugins run at two levels, and the worker level is the default.
- Plugins are discovered through explicit `--plugin` / `--plugin-host` flags, never by scanning a directory.
- A plugin can never block the supervisor or the session.
- Every failure takes one path: detect, disable, recover, then tell the session with a fixed-template notice.
- Restart is a supervisor primitive that is triggered by a `Restart` result, not by plugin code.

The agent's rulings on ordering, plugin location and restart policy, made while the owner was away, are in [DECISIONS.md](DECISIONS.md).

## Goals

- The supervisor loads explicitly named plugins. A plugin that fails in any way is disabled, the supervisor recovers, and the agent is told. The session always starts.
- `Restart` as a supervisor primitive: `/exit` at idle, wait for the child to exit, re-fork with `--resume <id>`.
- A ccy plugin on a fedora-desktop feature branch that uses the API for max-age restarts and deadlines.

## Non-Goals

- The credential-switch plugin from fedora-desktop Plan 00146. The API supports it, with its host half, but it remains that plan's work.
- A general "type this text" action. Only fixed supervisor templates reach the chat.
- Merging or opening a PR on fedora-desktop. The owner reviews and tests that branch, because the restart path needs a live ccy session to prove it.

## Tasks

### Phase 1: Plugin API in the supervisor (this repository, worktree branch)

- [ ] ⬜ **Task 1.1**: Read the draft and its research report (fedora-desktop Plan 00146 `subagent-reports/261002-supervisor-plugin-research-opus.md`) against the current `claude-supervise.py`. Record any drift.
- [ ] ⬜ **Task 1.2**: TDD the loader:
  - `--plugin` and `--plugin-host` flags;
  - ownership and mode checks on each file;
  - a `PLUGIN_API` major version check;
  - `--disable-plugin` carried across worker restarts;
  - plugin status in `supervisor-status.json`.
- [ ] ⬜ **Task 1.3**: TDD the worker hooks. `on_start` and `on_idle` run on a budgeted thread, are called only at NOOP in MONITOR with an empty box, and are asked in flag order.
- [ ] ⬜ **Task 1.4**: TDD the `Restart` primitive in the host:
  - refuse when the session id is ambiguous;
  - `/exit` through the injection path, with a deadline;
  - re-fork with `--resume <id>`, after stripping `--continue`, `-c`, `--resume`, `-r` and `--fork-session`;
  - abandon the restart if the child ignores `/exit`.
- [ ] ⬜ **Task 1.5**: TDD the host half: `before_spawn` runs in the forked child, behind the `env_keys` allowlist and the denylist, with a close-on-exec result pipe and a `SIGKILL` deadline. If it fails, the supervisor falls back to a plain respawn.
- [ ] ⬜ **Task 1.6**: TDD the uniform failure path and the plugin notice family:
  - the notice is built from a fixed template, typed only at an idle point, and capped;
  - it is also shown as a status-line warning and written to the audit log;
  - every failure kind in the draft's test list is covered.
- [ ] ⬜ **Task 1.7**: Document the API in `CLAUDE/development/CcySupervisor.md`, add a release-notes callout, and run the merge checks (static checks, semgrep, `tests/unit/supervise`). Then verify the worker reload as the CcySupervisor doc requires.

### Phase 2: ccy plugin (fedora-desktop feature branch, cloned under `untracked/repos/`)

- [ ] ⬜ **Task 2.1**: Establish from the fedora-desktop source how ccy installs and updates Claude Code, and how it builds the wrapper line. Record which restart picks up a new version (DECISIONS.md, item 5).
- [ ] ⬜ **Task 2.2**: Write the worker half: track session age and deadlines in `state_dir`, send the restart-warning notice, then return `Restart` at the next idle point. Include the forced-restart fallback. Unit-test it against the API's test harness.
- [ ] ⬜ **Task 2.3**: Add the ccy launcher options (`--max-age`, `--run-for`, `--until`) that build the `--plugin` flags. Follow fedora-desktop's own rules: IaC only, the ccy version bump, and `qa-all.bash` plus its `qa-reviewer`.
- [ ] ⬜ **Task 2.4**: Have the supervisor send a post-restart message naming the new Claude Code version.
- [ ] ⬜ **Task 2.5**: Push the branch and write an owner test script in the fedora-desktop plan folder, so the owner can run the live restart test on the host.

### Phase 3: Close out

- [ ] ⬜ **Task 3.1**: The owner runs the live test. Fix what it finds, then merge this repository's branch after v3.68.0.
- [ ] ⬜ **Task 3.2**: Comment the outcome on #71 and fedora-desktop#61, using "Addresses" wording.

## Success Criteria

- [ ] A crashing, hanging or unloadable plugin never stops the session from starting or running, and the agent gets exactly one notice for it.
- [ ] A ccy session past its maximum age gets warned, restarts at an idle point, resumes the same conversation on the current Claude Code version, and is told so.
- [ ] A `--run-for` / `--until` session gets its deadline message.

## Delivery & Milestones

- Plan filed.
