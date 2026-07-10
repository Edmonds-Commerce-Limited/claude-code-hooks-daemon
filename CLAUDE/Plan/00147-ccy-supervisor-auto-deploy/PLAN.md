# Plan 00147: ccy Supervisor Auto-Deploy

**Status**: In Progress
**Created**: 2026-07-10
**Owner**: joseph / Claude (Opus)
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The Plan 00135 PTY supervisor (`claude-supervise.py`) currently lives only in
this repo's `.claude/ccy/` and is dogfooded here. Client projects that use the
ccy container workflow (detectable by a `.claude/ccy/` directory) get no
supervisor and no compact-and-resume behaviour.

This plan makes the daemon **auto-deploy the supervisor into `.claude/ccy/` on
install and upgrade**, gated by a config flag. The daemon is installed by
git-cloning this repo into `.claude/hooks-daemon/`, so the tracked
`.claude/ccy/claude-supervise.py` is present in EVERY install at
`<daemon_root>/.claude/ccy/claude-supervise.py` — the deploy sources from there
and copies it into the target project's `.claude/ccy/`. There is exactly ONE
tracked copy of the script in this repo (pure dogfooding); no package/`src/`
duplicate. In self-install the daemon-root and project-root are the same path,
so the deploy is a no-op.

The deploy is a strongly-suggested opt-in: when the flag is absent and a
`.claude/ccy/` directory is present, the daemon deploys the supervisor anyway
and surfaces a recommendation (via the config-changes advisory) to set the flag
explicitly. An explicit `false` fully disables deploy.

## Goals

- Keep `claude-supervise.py` as the single tracked copy at `.claude/ccy/`
  (dogfooded); NO second copy in `src/` or the wheel.
- Add a `ccy.deploy_supervisor` config flag with tri-state semantics
  (true / false / absent).
- Deploy the supervisor into `<project>/.claude/ccy/claude-supervise.py` on
  fresh install and on upgrade, only when a `.claude/ccy/` directory exists and
  the flag is not `false`.
- Surface a strong recommendation to enable the flag on upgrade via the
  existing `check-config-migrations` config-changes channel
  (`recommended: true`, `recommended_value: true`).

## Non-Goals

- No change to the supervisor's runtime behaviour (Plan 00135 owns that).
- No ccy launcher / `ccy.env` wiring or LXC support (user-owned, deferred —
  see Plan 00135 `LXC-SUPPORT.md`). This plan deploys the *script*; arming it as
  `CCY_CLAUDE_WRAPPER` remains the launcher's job.
- No deploy into projects that have no `.claude/ccy/` directory (not ccy users).
- No wheel/pip-install support for the supervisor deploy (the daemon install
  model is git-clone; a pip install with no `.claude/ccy/` source simply skips
  the deploy with a message). Follow-up if wheel installs ever need it.

## Deploy Semantics (Decision D-CONFIG)

`ccy.deploy_supervisor`:

| Value   | target `.claude/ccy/` present? | Behaviour                                              |
| ------- | ------------------------------ | ------------------------------------------------------ |
| `true`  | yes                            | Deploy / refresh `claude-supervise.py`                 |
| `true`  | no                             | No-op (nothing to supervise)                           |
| `false` | any                            | Never deploy (explicit opt-out)                        |
| absent  | yes                            | Deploy / refresh AND recommend setting the flag `true` |
| absent  | no                             | No-op                                                  |

Detection signal = presence of the target project's `.claude/ccy/` directory
(mirrors the user's framing: "projects where we detect the `.claude/ccy`
folder"). Self-install no-op: when source and target resolve to the same file,
skip the copy (already in place).

## Design Decisions

- **D1 canonical location**: unchanged — `.claude/ccy/claude-supervise.py` is the
  single tracked source of truth, dogfooded in this repo. Clients receive it via
  the git-clone install, so it is present at `<daemon_root>/.claude/ccy/`. No
  `src/` move, no package-data, no drift risk (only one copy exists).
- **D2 deploy function**: mirror `deploy_plan_workflow_if_enabled`. New
  `install/ccy_supervisor.py` with `deploy_ccy_supervisor_if_enabled(daemon_root, project_root, config_path)`. Source = `daemon_root/.claude/ccy/claude-supervise.py`;
  target = `project_root/.claude/ccy/claude-supervise.py`; chmod 0o755; skip when
  source==target (self-install) or target `.claude/ccy/` dir absent.
- **D3 config**: new `CcyConfig(model_config extra="forbid")` with
  `deploy_supervisor: bool | None = None` (tri-state); attach as `ccy` field on
  root `Config` (models.py:621-ish).
- **D4 wiring**: `deploy-ccy-supervisor --project-root PATH` daemon CLI
  subcommand resolves `daemon_root` from `__file__`, loads config, applies the
  tri-state table, deploys. Wired into `install_version.sh` and BOTH
  `upgrade_version.sh` paths (full + fast) alongside the existing deploys.

## Tasks

### Phase 1: Config model (TDD)

- [x] ✅ **Task 1.1**: Failing tests for `CcyConfig` + `Config.ccy`
  (tri-state `deploy_supervisor`, `extra="forbid"`, default absent → None).
- [x] ✅ **Task 1.2**: Implement `CcyConfig` and attach `ccy` field to `Config`.

### Phase 2: Deploy function (TDD)

- [x] ✅ **Task 2.1**: Failing tests for `deploy_ccy_supervisor_if_enabled`
  covering the full tri-state table, self-install no-op (source==target),
  target-dir-absent no-op, chmod 0o755, missing-source skip-with-message.
- [x] ✅ **Task 2.2**: Implement `install/ccy_supervisor.py`.

### Phase 3: CLI subcommand (TDD)

- [ ] ⬜ **Task 3.1**: Failing tests for the `deploy-ccy-supervisor` subcommand
  (arg parsing, daemon-root resolution, config load, exit codes).
- [ ] ⬜ **Task 3.2**: Implement + register the subcommand in the daemon CLI.

### Phase 4: Wire into install + upgrade

- [ ] ⬜ **Task 4.1**: Call the subcommand at the fresh-install entry
  (`install_version.sh`, alongside `deploy_skills`).
- [ ] ⬜ **Task 4.2**: Call it in both `upgrade_version.sh` paths (full + fast).
- [ ] ⬜ **Task 4.3**: Integration test(s): fresh-install fixture deploys the
  supervisor; upgrade fixture refreshes it; explicit `false` skips;
  self-install no-op.

### Phase 5: Release plumbing + dogfood config

- [ ] ⬜ **Task 5.1**: Author
  `CLAUDE/UPGRADES/UNRELEASED/config-changes/v{X.Y.Z}.yaml` with the new
  `ccy.deploy_supervisor` key, `recommended: true`, `recommended_value: true`,
  `dormant: false`.
- [ ] ⬜ **Task 5.2**: Set `ccy.deploy_supervisor: true` in this repo's
  `.claude/hooks-daemon.yaml` (dogfood).
- [ ] ⬜ **Task 5.3**: Update generated docs / HANDLER_REFERENCE for the flag.

### Phase 6: Verify

- [ ] ⬜ **Task 6.1**: Full QA (`./scripts/qa/llm_qa.py all`) green.
- [ ] ⬜ **Task 6.2**: Daemon restart → RUNNING.
- [ ] ⬜ **Task 6.3**: Dogfood: run the CLI subcommand here, confirm it no-ops
  cleanly (source==target) with the right message.

## Success Criteria

- [ ] One tracked supervisor copy (`.claude/ccy/`); no `src/` duplicate.
- [ ] `deploy_ccy_supervisor_if_enabled` honours the tri-state table with full
  coverage (incl. self-install no-op).
- [ ] Fresh install and upgrade both deploy/refresh the supervisor when a
  `.claude/ccy/` dir exists and the flag is not `false`.
- [ ] Upgrade advisory recommends enabling the flag (config-changes manifest).
- [ ] QA green, daemon RUNNING.

## Notes & Updates

### 2026-07-10

- Plan created. Failsafe recovery cron `36afa8e5` (hourly at :37, non-durable)
  created for the execution window.
- Explore agent mapped deploy wiring: `deploy_skills` call sites
  (`install_version.sh`, both `upgrade_version.sh` paths), config schema
  (`config/models.py` root `Config`), config-changes manifest
  (`config-changes/SCHEMA.md` → `config_migrations.py` → `check-config-migrations`),
  and the `deploy_plan_workflow_if_enabled` analog.
- **Course correction (user)**: keep the canonical supervisor at
  `.claude/ccy/claude-supervise.py` — one tracked copy, pure dogfooding, no
  `src/` duplicate. Superseded the initial "move into package data" approach
  (reverted). Deploy sources from `<daemon_root>/.claude/ccy/` (present in every
  git-clone install) and self-install no-ops when source==target.
