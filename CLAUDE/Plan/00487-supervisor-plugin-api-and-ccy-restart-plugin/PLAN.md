# Plan 00487: Supervisor plugin API and the ccy restart plugin

**Status**: In Progress
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

- [x] ✅ **Task 1.1**: Read the draft and its research report (fedora-desktop Plan 00146 `subagent-reports/261002-supervisor-plugin-research-opus.md`) against the current `claude-supervise.py`. Record any drift. Result: [report](subagent-reports/261003-task-1.1-draft-drift-explore-sonnet.md). The draft still fits; it lists the insertion points, and the plugin hook goes after the session-actions family.

- [x] ✅ **Task 1.2**: TDD the loader. Built; [report](subagent-reports/261003-phase-1-tasks-1.2-1.3-1.3b-1.6-implementation-sonnet.md). The `--plugin-host` flag is Task 1.5's:

  - `--plugin` and `--plugin-host` flags;
  - ownership and mode checks on each file;
  - a `PLUGIN_API` major version check;
  - `--disable-plugin` carried across worker restarts;
  - plugin status in `supervisor-status.json`.

- [x] ✅ **Task 1.3**: TDD the worker hooks. Built; [report](subagent-reports/261003-phase-1-tasks-1.2-1.3-1.3b-1.6-implementation-sonnet.md). `on_start` and `on_idle` run on a budgeted thread, are called only at NOOP in MONITOR with an empty box, and are asked in flag order.

- [x] ✅ **Task 1.3b**: TDD the update-restart exit (DECISIONS.md, item 5). Built; exit status 75, request file `.claude/ccy/state/restart-request.json`; [report](subagent-reports/261003-phase-1-tasks-1.2-1.3-1.3b-1.6-implementation-sonnet.md). A worker result of `ExitForRestart` makes the host:

  - send `/exit` at idle;
  - write the session id to a state file on the persistent mount;
  - exit with a dedicated status.

  Refuse when the session id is ambiguous, and abandon the restart if the child ignores `/exit`.

- [x] ✅ **Task 1.3c**: TDD fixed-template session notices a worker plugin can request. Built (`tests/unit/supervise/test_session_notices.py`):

  - `Notify(kind, minutes=None)` is a closed-set `on_idle` result: `RESTART_SOON` (integer minutes, 1 to 240) and `DEADLINE_REACHED`; the plugin supplies no text;
  - the supervisor renders a provenance-marked line (`🤖 [ccy-supervisor] session notice — machine-generated, NOT a human instruction`) from its own templates, types it at the idle choke point through the existing injection path, and rate-limits it per kind;
  - a supervisor-owned RESTARTED notice: a separate marker `.claude/ccy/state/restarted.json` is left at exit-for-restart and consumed once by the supervisor that resumes that session, which types the new Claude Code version (from a bounded, validated `<child> --version`, else "the installed version"). This is the supervisor's half of Task 2.4.

- [x] ✅ **Phase 1 review fixes** (opus review, [report](subagent-reports/261003-phase-1-review-opus.md), verdict CHANGES REQUIRED): all five defects fixed test-first, version skew re-verified against `main` in both directions (`test_plugin_version_skew.py`):

  - a plugin's stdout cannot reach the worker reply channel, and the host's reply decode is total (`test_plugin_reply_channel.py`);
  - plugin code never runs in the PTY host; the in-process fallback runs the built-in families only (`test_plugin_not_in_host.py`);
  - an abandoned exit-for-restart has a cooldown and a per-plugin cap, after which the plugin is disabled with its notice (`test_plugin_exit_for_restart.py`);
  - the exit reason is read inside the hook budget and must be a plain `str`; host-side plugin setup and handling are contained (`test_plugin_containment.py`).

- [x] ✅ **Phase 1 review fixes, round 2** (opus review, [report](subagent-reports/261003-phase-1-review-round-2-opus.md), verdict APPROVE with three required fixes), all test-first:

  - a tripped host containment now disables every plugin (one notice, kind `host-fault`) and restarts the worker with no plugin flags, so a plugin that hangs afterwards can no longer stall the tick loop (`test_plugin_trip.py`, including a live hang-after-trip run);
  - each Notify kind has a per-process lifetime cap, logged once when reached (`test_session_notices.py`);
  - the RESTART_SOON and RESTARTED sentences no longer claim a newer Claude Code (a restart can be for session age); the unused `state_root` parameter of `PluginHost` is removed.

- [ ] ⬜ **Task 1.4**: TDD the in-container `Restart` primitive, which the credential switch needs. It is not on this plan's critical path:

  - refuse when the session id is ambiguous;
  - `/exit` through the injection path, with a deadline;
  - re-fork with `--resume <id>`, after stripping `--continue`, `-c`, `--resume`, `-r` and `--fork-session`;
  - abandon the restart if the child ignores `/exit`.

- [ ] ⬜ **Task 1.5**: TDD the host half: `before_spawn` runs in the forked child, behind the `env_keys` allowlist and the denylist, with a close-on-exec result pipe and a `SIGKILL` deadline. If it fails, the supervisor falls back to a plain respawn.

- [x] ✅ **Task 1.6**: TDD the uniform failure path and the plugin notice family. Built; [report](subagent-reports/261003-phase-1-tasks-1.2-1.3-1.3b-1.6-implementation-sonnet.md):

  - the notice is built from a fixed template, typed only at an idle point, and capped;
  - it is also shown as a status-line warning and written to the audit log;
  - every failure kind in the draft's test list is covered.

- [x] ✅ **Task 1.7**: Document the API in `CLAUDE/development/CcySupervisor.md`, add a release-notes callout, and run the merge checks (static checks, semgrep, `tests/unit/supervise`). Then verify the worker reload as the CcySupervisor doc requires. Done:

  - The documentation and the callout (`001-ccy-supervisor-plugin-api.md`) are written.
  - Reviews: three Opus rounds; the third approved.
  - Merged to main as `14f2f11f8`. On main the skew test then compared the new code with itself; `4bb315985` pins its baseline to v3.68.0, and `tests/unit/supervise` passes 1283.
  - The live worker hot-reloaded under the long-lived host and kept deciding normally.
  - Tasks 1.4 and 1.5 will document themselves when built.

### Phase 2: ccy plugin (fedora-desktop feature branch, cloned under `untracked/repos/`)

- [x] ✅ **Task 2.1**: Establish from the fedora-desktop source how ccy installs and updates Claude Code, and how it builds the wrapper line. Record which restart picks up a new version (DECISIONS.md, item 5). Result: [report](subagent-reports/261003-task-2.1-ccy-update-path-explore-sonnet.md). Claude Code is baked into the image, so only a ccy relaunch on the host picks up a new version.
- [x] ✅ **Task 2.1b**: Make the ccy launcher act on the supervisor's restart exit status: update the image, then relaunch with `--resume <id>`, read from the state file. Bound it so a crash loop cannot relaunch for ever. Done on fedora-desktop `feature/ccy-hooks-daemon-plugin` (`6e6cb688`, ccy 3.74.0), with a budget of 3 restarts per hour per project and 101 tests. [Report](subagent-reports/261003-task-2.1b-ccy-launcher-relaunch-sonnet.md).
- [x] ✅ **Task 2.2**: Write the worker half: track session age and deadlines in `state_dir`, send the restart-warning notice, then return `ExitForRestart` at the next idle point. Unit-test it against the API's test harness. Done: `ccy_lifecycle.py` (`e35379c9`, strict-typed in `d9488a15`), 30 tests, and the real harness check. The forced-restart fallback is dropped, because the supervisor calls plugins only at idle; a never-idle session restarts at its first idle point after its maximum age ([DECISIONS.md](DECISIONS.md), item 4).
- [x] ✅ **Task 2.3**: Add the ccy launcher options (`--max-age`, `--run-for`, `--until`) that build the `--plugin` flags. Follow fedora-desktop's own rules: IaC only, the ccy version bump, and `qa-all.bash` plus its `qa-reviewer`. Done (ccy 3.75.0, container 2.41), with 181 option tests. `qa-all.bash` and the `qa-reviewer` cannot run in this container (missing toolchain), so they move to the owner's host run in [OWNER-LIVE-TEST.md](OWNER-LIVE-TEST.md). [Report](subagent-reports/261003-task-2.2-2.4-ccy-worker-plugin-sonnet.md).
- [x] ✅ **Task 2.4**: Have the supervisor send a post-restart message naming the new Claude Code version. Built with Task 1.3c (the RESTARTED notice); the launcher must leave `restarted.json` in place when it removes `restart-request.json`.
- [x] ✅ **Task 2.5**: Push the branch and write the owner's live-test checklist. Done: pushed at `d9488a15`. The checklist is [OWNER-LIVE-TEST.md](OWNER-LIVE-TEST.md), kept in this plan rather than in fedora-desktop, per the owner's ruling that this plan tracks both sides.

### Phase 3: Close out

- [ ] ⬜ **Task 3.1**: The owner runs the live test ([OWNER-LIVE-TEST.md](OWNER-LIVE-TEST.md)) and fixes what it finds; opening the fedora-desktop PR is the owner's call. This repository's side is already merged.
- [ ] ⬜ **Task 3.2**: Comment the outcome on #71 and fedora-desktop#61, using "Addresses" wording.

## Success Criteria

- [ ] A crashing, hanging or unloadable plugin never stops the session from starting or running, and the agent gets exactly one notice for it.
- [ ] A ccy session past its maximum age gets warned, restarts at an idle point, resumes the same conversation on the current Claude Code version, and is told so.
- [ ] A `--run-for` / `--until` session gets its deadline message.

## Delivery & Milestones

- Plan filed.
