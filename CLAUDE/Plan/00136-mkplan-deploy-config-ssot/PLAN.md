# Plan 00136: mkplan deployment driven by config SSoT

**Status**: Implementation complete (Phases 1–3 shipped; release-prep Task 4.3 pending)
**Created**: 2026-06-23
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded (TDD)

> Source bug report: `untracked/hooks-daemon-plan-script.md` (downstream client
> `client-a-infra`, upgrading v3.22.0 → v3.24.0). High severity: every project
> following the daemon's own `plan_number_helper` guidance is told to run
> `CLAUDE/Plan/mkplan.bash`, a script the upgrade path never deploys.

## Overview

`mkplan.bash` (the atomic plan-number-allocation scaffolding script introduced in
v3.23.0) is only ever written to a project by `bootstrap_plan_workflow()` in
`install/plan_workflow.py`. That function has exactly one caller —
`scripts/install_version.sh` Step 14 — and the call is gated behind the opt-in
env var `PLAN_WORKFLOW=yes`. The **upgrade path (`scripts/upgrade_version.sh`)
never calls it at all**, on either its full path (Steps 6–16) or its idempotent
fast path (already-at-target, lines ~197–259).

The result is a silent contradiction: three v3.23.0 artifacts assert the script
is present — the `plan_number_helper` handler guidance (primary instruction:
"run `CLAUDE/Plan/mkplan.bash`"), the `truth-changes/v3.23.0.yaml` ("distributed
by the installer"), and the `plan_workflow.py` docstring ("always (re)deployed …
on upgrade") — while the delivery mechanism guarantees the script is **absent**
on every upgrade and on default fresh installs. The dogfood repo masks this
because `CLAUDE/Plan/mkplan.bash` was created here manually, so QA/acceptance
never exercised the gap.

The root cause is structural: **whether the plan workflow is "on" is decided in
two places that don't agree.** The runtime SSoT is the config
(`config.plan_workflow.enabled` / `.directory`, which the daemon already reads and
which drives the active handler guidance). The install-time `PLAN_WORKFLOW=yes`
env var is an orthogonal, unpersisted second switch. This plan makes **config the
single source of truth for deployment**: artifact deployment is derived from
`config.plan_workflow.enabled`, exactly as hooks, skills, and slash commands are
redeployed on every install and upgrade.

## Goals

- Deploy `mkplan.bash` + the plan scaffold **whenever `config.plan_workflow.enabled`
  is true**, on every `install_version.sh` run AND both `upgrade_version.sh` paths
  (full + idempotent fast path) — derived from config, not from an env var.
- Put the deploy decision in **one testable Python function** (SSoT, DRY) that all
  three shell sites call identically, so deployment can never drift from config.
- **Remove the `PLAN_WORKFLOW` env var entirely** (user-directed KISS): config is
  the only authority; no install-time switch that can disagree with it.
- Add a **deterministic acceptance gate** that fails if a simulated upgrade of a
  config-enabled fixture project does not leave `mkplan.bash` present + executable.
- Reconcile the now-true-once-wired docstring and stage a `truth-changes` /
  `config-changes` reconciliation for the release that ships the fix.

## Non-Goals

- NOT changing what `mkplan.bash` does, nor the plan-number git counter logic.
- NOT changing the config schema — `PlanWorkflowConfig.enabled`/`.directory`
  already exist and already migrate from legacy `track_plans_in_project` handler
  options. We consume that SSoT; we do not redesign it.
- NOT deploying the scaffold when the plan workflow is disabled in config.
- NOT overwriting client content: `README.md`/`CLAUDE.md` remain skip-if-exists;
  only the daemon-owned `mkplan.bash` is overwritten on every run.
- NOT editing released truth-changes in place (the v3.23.0 entry shipped); the
  reconciliation is a NEW entry for the fixing release, handled at release time.

## Context & Background

Verified against the v3.24.0 tree:

- `install/plan_workflow.py`: `bootstrap_plan_workflow(project_root, plan_dir_name)`
  creates the dir + `Completed/`, writes `README.md`/`CLAUDE.md` skip-if-exists,
  and `_deploy_mkplan()` copies the bundled template with mode `0o755`
  (overwrite-on-every-run). Docstring (lines ~125–126) already claims upgrade
  redeployment — currently aspirational.
- `config/models.py`: `PlanWorkflowConfig` has `enabled: bool = True`,
  `directory: str = "CLAUDE/Plan"`; `Config.migrate_plan_handler_options` promotes
  legacy `markdown_organization.options.track_plans_in_project` into
  `plan_workflow`. So `config.plan_workflow.enabled` + `.directory` IS the SSoT.
- `scripts/install_version.sh:417` — only caller, gated `PLAN_WORKFLOW=yes`; uses
  `Config.load_or_default($TARGET_CONFIG)` and `config.plan_workflow.directory`.
- `scripts/upgrade_version.sh` — full path Steps 6–16 (hooks/settings/config-merge/
  gitignore/slash-commands/skills/restart) and fast path lines ~197–259; **neither
  deploys mkplan**.

## Technical Decisions

### Decision A: Single Python entrypoint consumed by all shell sites (DRY/SSoT)

**Context**: deployment is needed at three shell sites (install, upgrade-full,
upgrade-fast). Duplicating config-reading + bootstrap invocation in bash across
three sites would re-create the drift the bug is about.

**Decision**: add one pure-Python function
`deploy_plan_workflow_if_enabled(project_root: Path, config_path: Path) -> BootstrapResult`
to `install/plan_workflow.py`. It loads the config via `Config.load_or_default`,
no-ops with a clear message when `plan_workflow.enabled` is false, and otherwise
delegates to the existing `bootstrap_plan_workflow(project_root, config.plan_workflow.directory)`.
All three shell sites call it with one identical `$VENV_PYTHON -c` invocation (or a
tiny CLI shim). One decision site → cannot drift.

### Decision B: Config is the only gate; `PLAN_WORKFLOW` env var removed entirely (KISS)

**Decision** (user-directed, 2026-06-23 — "this PLAN_WORKFLOW env var is really
stupid… we need clear SSoT and general KISS"): the deploy step runs
unconditionally on every install/upgrade and lets the Python function decide from
config (`config.plan_workflow.enabled`). The `PLAN_WORKFLOW` env var is **deleted
outright** — not demoted, not kept as a seed — so there is exactly ONE source of
truth (the config the daemon reads). No second, install-time-only switch that can
disagree with config. `config.plan_workflow.enabled` defaults `true`, so a stock
install deploys the scaffold by default; a project that does not want it sets
`plan_workflow.enabled: false`.

**Behaviour change**: fresh installs (and existing upgrades) now deploy the plan
scaffold + `mkplan.bash` by default, where previously a fresh install required
`PLAN_WORKFLOW=yes`. This matches the config SSoT (`enabled` defaults true) and
the field-bug report (which lists "default fresh installs" as wrongly NOT getting
the script). Recorded as a `config-changes` note at release.

### Decision C: Fold the acceptance gate into the existing end-to-end tests (DRY)

**Decision (as built)**: rather than a new `test_plan_workflow_deploy.py` that
would duplicate the slow daemon-spinning harness, the gate was folded into the two
existing end-to-end tests in `tests/acceptance/test_install_sh_end_to_end.py`
(already in RELEASING.md Step 12.0). A shared `_assert_mkplan_deployed` helper
asserts `CLAUDE/Plan/mkplan.bash` is present + mode `0o755` after the real
`install_version.sh` AND `upgrade_version.sh` (fast path) runs. This proves the
actual shell WIRING calls the deploy — non-redundant with the Phase 1 unit tests
(which already cover the Python entrypoint's enabled/disabled/custom-dir logic).
The example config the fixtures use has `plan_workflow.enabled` defaulting True, so
the deploy fires; the disabled-config case is covered by the Phase 1 unit test.

## Tasks

### Phase 1: Python deploy entrypoint (TDD)

- [ ] ⬜ **Task 1.1**: RED — add tests to
  `tests/unit/install/test_plan_workflow.py` for `deploy_plan_workflow_if_enabled`:
  (a) enabled config → deploys mkplan into `config.plan_workflow.directory`, file
  exists + mode 0o755; (b) disabled config → no-op, mkplan absent, clear message;
  (c) honours a non-default `directory`; (d) missing config file → uses model
  default (enabled) and deploys to `CLAUDE/Plan`.
- [ ] ⬜ **Task 1.2**: GREEN — implement `deploy_plan_workflow_if_enabled` in
  `install/plan_workflow.py` delegating to `bootstrap_plan_workflow`.
- [ ] ⬜ **Task 1.3**: REFACTOR; reconcile the `bootstrap_plan_workflow` /
  `_deploy_mkplan` docstrings so the "always (re)deployed on upgrade" claim is
  scoped to "when enabled in config" and is now actually wired.
- [ ] ⬜ **Task 1.4**: Verify 95%+ coverage on `install/plan_workflow.py`.

### Phase 2: Wire deployment into install + both upgrade paths

- [ ] ⬜ **Task 2.1**: `install_version.sh` Step 14 — replace the
  `PLAN_WORKFLOW=yes` gate with an unconditional call to
  `deploy_plan_workflow_if_enabled`. Demote the env var per Decision B.
- [ ] ⬜ **Task 2.2**: `upgrade_version.sh` full path — add a deploy step (after
  skills redeploy, Step 13) calling `deploy_plan_workflow_if_enabled`.
- [ ] ⬜ **Task 2.3**: `upgrade_version.sh` fast/idempotent path (lines ~197–259)
  — add the same call after `deploy_skills` so already-at-target re-runs also
  deliver the script.
- [ ] ⬜ **Task 2.4**: shellcheck clean (`shell_audit` QA); no `cd`, absolute/`-C`
  invocations only; surface failures (non-fatal print_warning, matching siblings).

### Phase 3: Acceptance gate + regression closure

- [ ] ⬜ **Task 3.1**: RED/GREEN — `tests/acceptance/test_plan_workflow_deploy.py`
  per Decision C (enabled→present+executable, disabled→absent).
- [ ] ⬜ **Task 3.2**: Add the new acceptance test to RELEASING.md Step 12.0 gate.

### Phase 4: QA, dogfood, release-prep reconciliation

- [ ] ⬜ **Task 4.1**: Full QA (`./scripts/qa/llm_qa.py all`) — 13/13.
- [ ] ⬜ **Task 4.2**: Daemon restart verification — RUNNING, logs clean.
- [ ] ⬜ **Task 4.3**: Stage a `config-changes` / `truth-changes` reconciliation
  note for the fixing release (the v3.23.0 "distributed by the installer" wording
  becomes "distributed when the plan workflow is enabled in config, on install and
  upgrade"). Done as part of `/release`, not committed as a released manifest now.

## Dependencies

- Consumes: `PlanWorkflowConfig` (config SSoT), `bootstrap_plan_workflow`.
- Must not regress: existing `bootstrap_plan_workflow` behaviour, config merge on
  upgrade (Step 10 must run before the deploy step so config is current).

## Success Criteria

- [ ] A simulated upgrade of a config-enabled project leaves `CLAUDE/Plan/mkplan.bash`
  present and executable (acceptance gate proves it).
- [ ] A config-disabled project gets no `mkplan.bash` (no-op verified).
- [ ] `deploy_plan_workflow_if_enabled` is the single deploy decision site; all
  three shell sites call it identically.
- [ ] `PLAN_WORKFLOW=yes` is no longer the deployment gate.
- [ ] Docstrings match wired behaviour.
- [ ] 13/13 QA; daemon restarts RUNNING; 95%+ coverage.

## Risks & Mitigations

| Risk                                              | Impact | Probability | Mitigation                                                                                   |
| ------------------------------------------------- | ------ | ----------- | -------------------------------------------------------------------------------------------- |
| Deploy step runs before config merge on upgrade   | Medium | Low         | Place the call AFTER Step 10 (config merge) so `plan_workflow.enabled` reflects new default  |
| Overwriting a client-customised mkplan            | Low    | Low         | mkplan is daemon-owned by design (overwrite-on-run); client custom logic belongs elsewhere   |
| Self-install/dogfood path accidentally triggered  | Medium | Low         | upgrade_version.sh is guarded `ensure_normal_mode_only`; deploy honours configured directory |
| Disabled-config projects get an unwanted scaffold | Medium | Low         | Function no-ops when `plan_workflow.enabled` is false; acceptance test asserts absence       |

## Notes & Updates

### 2026-06-23

- Plan scaffolded and authored from `untracked/hooks-daemon-plan-script.md`.
  Root cause confirmed against the v3.24.0 tree: `bootstrap_plan_workflow` has a
  single env-gated caller (`install_version.sh`); `upgrade_version.sh` never
  deploys mkplan on either path. Config SSoT (`PlanWorkflowConfig.enabled`)
  already exists — the fix derives deployment from it.
- **Phases 1–3 delivered** (all tasks done):
  - Phase 1 (`db41fed`): `deploy_plan_workflow_if_enabled` entrypoint + 6 unit
    tests; module coverage 97.3%; docstrings reconciled.
  - Phase 2 (`753e9ed`): wired the config-driven deploy into `install_version.sh`
    Step 14 and BOTH `upgrade_version.sh` paths (full new Step 14 + idempotent
    fast path); **`PLAN_WORKFLOW` env var removed entirely** (gate + summary +
    customisation hints) per user KISS direction; steps renumbered.
  - Phase 3 (`79ba0d6`): the two end-to-end acceptance gates now assert
    `CLAUDE/Plan/mkplan.bash` present + mode 0o755 after a real shell install AND
    upgrade. Both PASS — bug fixed and proven end-to-end. Files already in
    RELEASING.md Step 12.0, so Task 3.2 satisfied.
  - Phase 4: full QA 13/13 PASSED (8703 tests, 95.1% cov); daemon restarts
    RUNNING. Task 4.3 (config-changes/truth-changes note for the deploy-by-default
    behaviour change) is a `/release`-time activity.
- **Gate decision (KISS, user-directed)**: deploy is gated on the single config
  SSoT `config.plan_workflow.enabled`. The default-True-vs-shipped-disabled-handler
  nuance (deploy-by-default on stock installs) is catalogued as finding F-PLANDEF
  in Plan 00137 for deliberate reconciliation (it touches the migration validator
  - example config), rather than rushed here.
- Spawned the **Opus SSoT/KISS audit** the user requested → findings tracked in
  Plan 00137 (F-FASTPATH and F-SUMMARY were already fixed by this plan's Phase 2).
