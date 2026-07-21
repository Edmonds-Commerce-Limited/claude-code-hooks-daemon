# Plan 00185: Installer/Upgrade settings.json SSoT reconciliation + plan-workflow provisioning

**Status**: In Progress
**Created**: 2026-07-21
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A newly-installed / upgraded client project floods every session start with
`WARNING: Missing hook registration for {Event} in settings.json` for the
Plan 00170 zero-handler-passthrough events (ConfigChange, CwdChanged,
Elicitation, ElicitationResult, FileChanged, InstructionsLoaded,
MessageDisplay, PermissionDenied, PostCompact, PostToolBatch,
PostToolUseFailure, Setup, StopFailure, SubagentStart, …). The user asked
whether the **install process has been neglected and drifted out of sync with
the upgrade process**. Investigation says: effectively yes — settings.json
hooks reconciliation is neither SSoT-derived on every path nor merge-based, so
both install and upgrade can leave a client's registrations frozen behind the
running daemon's expectations, and nothing self-heals.

Root cause has two independent halves:

- **Half A — hook-registration flood.** The daemon has THREE sources that
  produce settings.json hook registrations and they disagree:

  1. `install.py` `_DAEMON_FORWARDER_HOOKS` — 30 events (in sync).
  2. tracked `.claude/settings.json` template, copied by
     `install_version.sh` / `upgrade_version.sh` — 30 events (in sync).
  3. **`generate_settings_json()` bash fallback in `install_version.sh` — only
     15 events, explicitly documented as "NOT kept in lockstep with the full
     Plan 00170 wired set".** This is a second hardcoded list that drifts.

  Deployment is a **clobber `cp`**, never a merge: `upgrade_version.sh` step 9
  `cp`s the daemon template over the client file; if the release/`DAEMON_DIR`
  lacks `.claude/settings.json` the copy is skipped ("using existing") and the
  client's stale registrations survive while the Python code (the
  `hook_registration_checker`, which expects every `wired=True` event from
  `wired_event_metas()`) advances → flood. And `hook_registration_checker`
  only *detects* — it already auto-migrates command **shape** via
  `migrate_settings_to_bash_invocation`, but it never **adds** missing events,
  so it nags forever instead of fixing.

- **Half B — plan-workflow / journalling provisioning.**
  `deploy_plan_workflow_if_enabled` IS wired into install/upgrade (gated on
  `plan_workflow.enabled`), but there is **no on-demand path**: a user who
  flips the flag after install, or partially hand-scaffolds the plan tree, is
  left with CLAUDE.md and `plan_number_helper` pointing at a non-existent
  `mkplan.bash`, and journalling advertised but silently inert. No error is
  surfaced anywhere. (Documented in the migrated report
  `pre-investigation-notes.md`.)

The proper fix is to make settings.json hook reconciliation a single
**SSoT-derived, idempotent MERGE** (add missing wired events, fix command
shape, preserve `permissions` / `env` / `statusLine` / any client-added keys
and hooks), make the `hook_registration_checker` **self-heal** the same way so
already-installed projects recover on their next session, delete the second
hardcoded bash list, and give plan-workflow deployment an on-demand CLI + drift
advisory.

### Relationship to Plan 00176 (IMPORTANT — de-duplication)

**Plan 00176 ("settings.json merge — preserve client customizations on
upgrade", Not Started) already owns the upgrade/install-time structured merge**
— the `config_preserve`-style shell wiring that replaces the clobber-`cp`, plus
the agent-assisted diff for un-mechanical cases. 00185 does NOT re-implement
that. Instead 00185 provides the **shared SSoT reconciler core** that BOTH
consume, and the pieces 00176 does not cover:

- **Shared core** (Phase 1): one `reconcile_settings_hooks()` util derived from
  `wired_event_metas()`. 00176's upgrade merge calls it for the hook block;
  00185's self-heal checker calls it at session start.
- **Session-time self-heal** (Phase 2): the piece that stops the flood the user
  sees TODAY on an already-installed project **without** waiting for an upgrade.
- **SSoT de-dup + regression guard** (Phase 4): remove/regenerate the stale
  15-event bash `generate_settings_json`; add the drift test.
- **Half B** (Phase 3): plan-workflow on-demand deploy CLI + drift advisory —
  entirely 00185's own, unrelated to 00176.

## Goals

- Eliminate the session-start flood for both fresh installs AND already-installed
  projects, without a full reinstall, by SSoT-derived reconciliation + self-heal.
- Establish ONE source of truth for the wired hook set (`wired_event_metas()`),
  consumed by installer, upgrader, checker, and the tracked template — remove
  the drifting second/third hardcoded lists.
- Reconcile settings.json by **merge** (never clobber): preserve client
  `permissions`/`env`/`statusLine` and any client-added hook entries.
- Give plan-workflow assets an on-demand (re)deploy CLI and a SessionStart drift
  advisory when `plan_workflow.enabled: true` but core assets are missing.
- Add regression guards that fail if any settings.json source drifts from the
  SSoT again (the test that would have caught this).

## Non-Goals

- Not changing the *set* of wired events (no new Plan 00170 wiring here).
- Not moving client `permissions` between settings.json / settings.local.json
  (policy unchanged); we only preserve whatever is there.
- Not a release. Release is a separate, gated workflow (`/release`) after this
  lands and is dogfooded.
- **Not** the upgrade/install shell-side merge wiring or agent-assisted diff —
  that is Plan 00176. 00185 only provides the reconciler core it consumes and,
  optionally, replaces the stale bash fallback (Phase 4) if 00176 has not yet.

## Dependencies

- **Related / shares core**: Plan 00176 (settings.json upgrade-time merge) —
  consumes the Phase 1 reconciler. Coordinate so the util lands once.
- **Related**: Plan 00170 (universal hook coverage — SSoT `wired_event_metas()`),
  Plan 00172 (HandlersConfig ↔ wired-events drift), Plan 00163 (plan journalling).

## Context & Background

- SSoT for events: `src/claude_code_hooks_daemon/constants/events.py`
  (`EventID`, `wired_event_metas()`; all catalogued events currently
  `wired=True`). StatusLine is excluded from the `hooks` section (top-level
  `statusLine` key).
- Checker: `handlers/session_start/hook_registration_checker.py` +
  `utils/hook_registration.py` (`HOOK_EVENTS_IN_SETTINGS`,
  `validate_settings_hooks`, `validate_hook_commands`, …).
- Existing auto-repair precedent: `utils/hook_command_migration.py`
  (`migrate_settings_to_bash_invocation`) — invoked by the checker under an
  opt-out `auto_migrate_settings` flag. The new self-heal mirrors this exactly.
- Installer/upgrader: `install.py` (`_DAEMON_FORWARDER_HOOKS`,
  `create_settings_json`, `create_all_hooks`), `scripts/install_version.sh`
  (`generate_settings_json` fallback + copy path), `scripts/upgrade_version.sh`
  (clobber-`cp` step 9), `scripts/install/hooks_deploy.sh`
  (`_DAEMON_HOOK_BASENAMES`, `deploy_all_hooks`).
- Plan-workflow deploy: `src/claude_code_hooks_daemon/install/plan_workflow.py`
  (`deploy_plan_workflow_if_enabled`, idempotent gap-fill). CLI:
  `src/claude_code_hooks_daemon/daemon/cli.py`.
- Supporting detail: `pre-investigation-notes.md` in this folder (migrated from
  `untracked/hooks-daemon-plan-docs.md`).

## Tasks

### Phase 1: SSoT settings.json reconciler (merge, not clobber)

- [x] ✅ **Task 1.1**: RED — failing tests for `reconcile_settings_hooks()` in
  `utils/hook_registration.py` (adds missing wired events; preserves
  permissions/env/statusLine/unknown keys + client hook entries; idempotent;
  SSoT-derived). Done (11 tests).
- [x] ✅ **Task 1.2**: GREEN — implemented `reconcile_settings_hooks()` +
  `ReconcileResult` on the SSoT (`HOOK_EVENTS_IN_SETTINGS`). Commit `521fc96e`.
- [x] ✅ **Task 1.3**: Added `reconcile-settings` CLI (creates a missing
  settings.json with the full wired set; merges missing events into a partial
  one; `--check` for CI). 6 tests. Live-verified against this repo.
- [x] ✅ **Task 1.4**: `install_version.sh::generate_settings_json` now delegates
  to `reconcile-settings` (SSoT) as its primary path — the 15-event hardcoded
  heredoc is demoted to an inert last-resort behind the CLI. Syntax + shellcheck
  clean. (Shell-side upgrade MERGE wiring remains Plan 00176's deliverable.)

### Phase 2: Self-healing hook_registration_checker

- [x] ✅ **Task 2.1**: RED — failing tests for the file-level
  `repair_settings_registrations()` + checker `auto_repair_registrations`
  default-on behaviour, warn-mode fallback, permission preservation, one-shot
  backup, and fail-safe malformed/non-dict paths. Done.
- [x] ✅ **Task 2.2**: GREEN — new `utils/settings_repair.py` (file-level,
  fail-safe, one-shot backup) built on the Phase 1 reconciler; wired into
  `hook_registration_checker` under opt-out `auto_repair_registrations` (mirrors
  `auto_migrate_settings`). Dogfood-proved on a simulated 10-event stale client →
  30 events, permissions preserved, backup written.
- [x] ✅ **Task 2.3**: Updated `get_claude_md()` "Missing hooks" remediation to
  describe self-heal + opt-out. (HANDLER_REFERENCE doc entry: Phase 4.)

### Phase 3: Plan-workflow on-demand deploy + drift advisory

- [x] ✅ **Task 3.1**: `deploy-plan-workflow` CLI added (wraps
  `deploy_plan_workflow_if_enabled`; `--project-root`). 3 tests; live `--help` ok.
  Found (not fixed here) that the deploy fn's docstring claims a missing config
  defaults to *enabled*, but `PlanWorkflowConfig.enabled` defaults to **False** —
  noted for a follow-up doc fix.
- [ ] ⬜ **Task 3.2**: SessionStart drift advisory: when
  `plan_workflow.enabled: true` but core assets (`mkplan.bash`,
  `_JOURNAL_TEMPLATE_.md`, `PlanJournalling.md`) are missing, advise running
  `deploy-plan-workflow`. Silent when assets present or workflow disabled.
  **REMAINING** — separable enhancement (a new handler needs config-default
  registration + docs regen + acceptance + daemon-load verification); the 3.1 CLI
  already gives users the recovery path.

### Phase 4: Regression guards + dogfood

- [x] ✅ **Task 4.1**: `test_settings_sources_ssot_drift.py` asserts `install.py`
  `_DAEMON_FORWARDER_HOOKS`, the tracked `.claude/settings.json`, and
  `hooks_deploy.sh` `_DAEMON_HOOK_BASENAMES` all agree with `wired_event_metas()`.
  3 tests, fail-on-drift. (HANDLER_REFERENCE doc entry for the new checker option
  still to add.)
- [ ] ⬜ **Task 4.2**: Full QA (`./scripts/qa/run_all.sh`) + daemon restart RUNNING.
- [ ] ⬜ **Task 4.3**: Dogfood: run the reconciler against this repo; confirm
  session-start no longer floods; verify plan assets present.

## Success Criteria

- [ ] A fresh install and an upgrade both leave settings.json with the full wired
  hook set, client `permissions`/`env`/`statusLine` preserved.
- [ ] An already-installed project with a stale settings.json self-heals on the
  next session (no reinstall) and the flood stops.
- [ ] Exactly one source of truth for the wired hook set; regression test fails on
  any drift.
- [ ] `deploy-plan-workflow` CLI exists; drift advisory fires when assets missing.
- [ ] `./scripts/qa/run_all.sh` passes; daemon restarts RUNNING.

## Risks & Mitigations

| Risk                                              | Impact | Probability | Mitigation                                                                                                                         |
| ------------------------------------------------- | ------ | ----------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Reconciler corrupts a client settings.json        | High   | Low         | Back up before write; merge is additive; extensive unit tests incl. malformed input; fail-safe (warn, no write) on any parse error |
| Auto-repair writes unexpectedly / surprises users | Med    | Med         | Opt-out flag defaulting on, mirroring `auto_migrate_settings`; report every change; only touch the `hooks` section                 |
| Install-path change breaks H-1 acceptance gate    | High   | Med         | Cover with acceptance-style tests; run install/upgrade e2e tests before any release                                                |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when"). Blow-by-blow log lives in JOURNAL/00185-Journal-YY-MM-DD.md. -->

- Plan created; root cause established across install/upgrade/checker paths — `daa273ca`.
- Phase 1 — SSoT reconciler core (`reconcile_settings_hooks`) — `521fc96e`.
- Phase 2 — self-healing checker (the flood fix; no reinstall needed) — `84a7b9d4`.
- Phase 1.3/1.4 + 4.1 — `reconcile-settings` CLI, SSoT bash fallback, drift guard — `71fed429`.
- Phase 3.1 — `deploy-plan-workflow` CLI — `7841550b`.
- Phase 4.2 — full QA 13/13 (10503 tests, 95.2% cov); format auto-fix — `7b9541fc`.

**Status of concerns raised by the user:**

- Registration flood: **FIXED** — self-heal repairs an already-installed project
  on its next session; fresh install/upgrade stay SSoT-correct; drift guard
  prevents recurrence.
- Plan/journal provisioning: **recovery path shipped** (`deploy-plan-workflow`);
  proactive SessionStart advisory (Task 3.2) is the one tracked remaining item.

## Notes & Updates

- Failsafe recovery cron (non-durable, hourly at :37): **88ad018c**.
- Supporting investigation: `pre-investigation-notes.md` (migrated from
  `untracked/hooks-daemon-plan-docs.md`, which already fixed this repo's own
  missing plan-workflow assets via `deploy_plan_workflow_if_enabled`).
