# Plan 00137: Install/Upgrade SSoT + KISS Audit & Remediation

**Status**: Complete
**Created**: 2026-06-23
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration (one TDD fix per finding)

> User-directed (2026-06-23): "this PLAN_WORKFLOW env var is really stupid and we
> should get rid of this. We need clear SSoT and general KISS. I think despatch
> an opus agent to scan for and itemise these, lets track all this in a plan work
> flow folder and do it properly."

## Overview

Plan 00136 fixed the flagship instance — `mkplan.bash` deployment gated by the
orthogonal `PLAN_WORKFLOW=yes` env var and absent on upgrade — by deriving
deployment from the config SSoT and deleting the env var. An Opus audit agent
then scanned the whole install/upgrade/deployment system for **structural twins**
of that bug: env-var/flag gates orthogonal to config, install-vs-upgrade
asymmetries, dual sources of truth, deploy decisions decoupled from runtime
config, and KISS violations.

This plan catalogues the audit's verified findings and tracks their remediation.
Each finding is fixed with TDD on its own (failing test → fix → QA → daemon
restart), one checkpoint commit per finding. The guiding principle throughout:
**the runtime config (`.claude/hooks-daemon.yaml`) is the single source of truth;
deployment and install-time behaviour derive from it, never from a second
unpersisted switch.**

## Goals

- Eliminate every install-time env-var/flag that acts as a second source of truth
  for something the runtime config governs (flagship: `HANDLER_PROFILE`).
- Remove all remaining install-vs-upgrade and full-path-vs-fast-path asymmetries
  in artifact/behaviour deployment.
- Collapse duplicated sources of truth (Python floor version, plan directory,
  profile handler-name lists, stale summary paths) to one authority each.
- Make shipped defaults (example config) agree with shipped behaviour (handler
  enabled-state) so deploy decisions cannot drift from runtime.

## Non-Goals

- NOT re-doing Plan 00136 (mkplan/`PLAN_WORKFLOW`) — that is the exemplar, already
  fixed. Findings F-FASTPATH and F-SUMMARY below were resolved by 00136 and are
  recorded here only for completeness.
- NOT a config-schema redesign beyond what each finding's KISS fix requires.
- NOT changing daemon runtime behaviour where config already is the SSoT.

## Audit Findings (verified against source by the Opus audit agent)

| ID         | Title                                                                 | Class     | Severity | Status                 |
| ---------- | --------------------------------------------------------------------- | --------- | -------- | ---------------------- |
| F-PROFILE  | `HANDLER_PROFILE` env gate orthogonal to config, never on upgrade     | env-gate  | High     | ✅ Fixed (defe9fb)     |
| F-PLANDEF  | `plan_workflow.enabled` defaults True but handler ships disabled      | deploy≠rt | Medium   | ✅ Fixed (18c4a65)     |
| F-PYFLOOR  | Python `3.11` floor hardcoded despite pyproject SSoT + parser         | dup-ssot  | Medium   | ✅ Fixed (faa53e2)     |
| F-PLANDIR  | Plan dir duplicated across `directory` + two `track_plans_in_project` | dup-ssot  | Medium   | ✅ Fixed (18c4a65)     |
| F-PROFLIST | Profile handler-name lists hardcode names that also live in config    | dup-ssot  | Low      | ✅ Fixed (026dde9)     |
| F-VENVSUM  | Install summary prints the deleted legacy venv path                   | dup/KISS  | Low      | ✅ Fixed (defe9fb)     |
| F-FASTPATH | Plan deploy missing from upgrade fast path                            | asymmetry | High     | ✅ Fixed in Plan 00136 |
| F-SUMMARY  | Install summary advertised removed `PLAN_WORKFLOW=yes` switch         | KISS      | Low      | ✅ Fixed in Plan 00136 |

## Finding detail & remediation

### F-PROFILE (High) — `HANDLER_PROFILE` install-only env gate, never on upgrade

**Location**: `scripts/install_version.sh` Step 15 (`HANDLER_PROFILE="${HANDLER_PROFILE:-minimal}"` → `apply_profile`); `src/.../install/handler_profiles.py`. `upgrade_version.sh` has zero profile references; `config/models.py` has no profile field.

**Why**: Exact structural twin of the `PLAN_WORKFLOW` exemplar. "Which handlers are enabled" is the most central thing the config governs, yet the initial answer is set by an install-time env var with no config record. On upgrade the profile is never re-applied; the config-merge reconciles against the minimal example default. The env var can silently disagree with the config the daemon reads.

**Decision needed**: profiles should be a one-shot SEED of the user's config at fresh-install time only (after `apply_profile`, the chosen handlers are `enabled: true` in the yaml — which IS the SSoT thereafter). Remediation: (a) document profiles as initial-seed-only, (b) verify/add a test that the upgrade config-merge PRESERVES profile-enabled handlers (so the seed survives upgrades), (c) ensure no upgrade path needs to re-apply a profile. If profiles must be re-assertable, store the selected profile name in config and derive on both paths. **Confirm approach with user before building** (behaviour-sensitive).

### F-PLANDEF (Medium) — config default True vs shipped-disabled handler

**Location**: `config/models.py` (`PlanWorkflowConfig.enabled` default True); `.claude/hooks-daemon.yaml.example` has no top-level `plan_workflow:` block; `plan_number_helper` ships `enabled: false`.

**Why**: After Plan 00136, `deploy_plan_workflow_if_enabled` deploys whenever `plan_workflow.enabled` is true. Because the example config omits the block, the model default (True) wins → mkplan + `CLAUDE/Plan/` scaffold deploy into EVERY install/upgrade, even though the handler that uses mkplan (`plan_number_helper`) ships disabled. Deploy ≠ runtime: the artifact ships while its consumer is dormant (inverse of the mkplan bug).

**Remediation (KISS, one SSoT)**: make the shipped default match the shipped (opt-in) handler state. Add an explicit top-level `plan_workflow:\n  enabled: false` to the example config so a stock install does NOT scatter `CLAUDE/Plan/`, and opting in (one field) turns on BOTH the handlers' directory feed (registry already gates on `plan_workflow.enabled`) AND the deploy. **Caution**: the migration validator (`migrate_plan_handler_options`) skips migration when `plan_workflow` is explicitly set — adding an explicit block to the example interacts with legacy `track_plans_in_project` opt-in (F-PLANDIR). Must be designed together with F-PLANDIR so the legacy opt-in path still works. This finding also revisits Plan 00136's deploy-by-default behaviour.

### F-PYFLOOR (Medium) — hardcoded `3.11` despite pyproject SSoT

**Location**: `scripts/install/prerequisites.sh:65,69-70` (`find_latest_python 3.11`, no pyproject arg); `scripts/lib/resolve_venv.sh:156`. SSoT is `pyproject.toml` `requires-python`, parsed by `parse_min_python.sh`; `find_latest_python(floor, pyproject)` raises the floor from pyproject when the 2nd arg is passed (the skill `install.sh` does this correctly).

**Remediation**: pass `$DAEMON_DIR/pyproject.toml` to `find_latest_python` in `prerequisites.sh` (and drop the bare literal in `resolve_venv.sh`); generate the `(3.11+)` diagnostic text from the parsed floor. No behaviour change today; prevents a silent install-time bug at the next floor bump.

### F-PLANDIR (Medium) — plan directory duplicated, "must match" admitted in comment

**Location**: `.claude/hooks-daemon.yaml.example:120,167` (two `track_plans_in_project`, one commented "Must match markdown_organization setting"); `config/models.py` (`plan_workflow.directory`). Migration copies handler option → `plan_workflow` only when top-level absent.

**Remediation**: make `plan_workflow.directory` the only writable SSoT; have plan handlers read it (derive `track_plans_in_project` at config-load), deprecating the per-handler option. Design jointly with F-PLANDEF (both touch the migration validator + example config).

### F-PROFLIST (Low) — profile handler-name lists duplicate config keys

**Location**: `src/.../install/handler_profiles.py:24-60` (`_RECOMMENDED_HANDLERS`, `_STRICT_ONLY_HANDLERS`). No cross-check that a listed name exists in config; a renamed handler silently no-ops.

**Remediation**: validate profile entries against the loaded config's known handler keys at apply time; warn/fail on unknown names. Tie to F-PROFILE.

### F-VENVSUM (Low) — install summary prints deleted legacy venv path

**Location**: `scripts/install_version.sh:486` (`echo "  Venv:  $DAEMON_DIR/untracked/venv/"`). Venvs are fingerprint-keyed; the script computes the real path as `$VENV_PATH` and DELETES the legacy `untracked/venv`. The summary hardcodes the stale path.

**Remediation**: print `$VENV_PATH` instead of the hardcoded literal. Output-only; trivial.

## Tasks

### Phase 1: High severity

- [x] ✅ **Task 1.1 (F-PROFILE)**: Approach decided seed-only (config IS the SSoT after the seed; re-applying on upgrade would clobber user handler choices). TDD: added `TestProfileSeedSurvivesUpgrade` (profile-seeded enabled:true survives the production diff+merge); documented profiles as an initial install-time seed in the module docstring + install summary; reworded HANDLER_PROFILE messaging so it no longer reads as a durable switch.

### Phase 2: Medium severity (design F-PLANDEF + F-PLANDIR together)

- [x] ✅ **Task 2.1 (F-PLANDEF + F-PLANDIR)**: Flipped `PlanWorkflowConfig.enabled` model default to False (matches opt-in handlers); kept `migrate_plan_handler_options` so legacy per-handler opt-in survives; shipped only a COMMENTED top-level `plan_workflow` block in the example (an active one would merge into legacy configs and skip migration); removed the dead per-handler `track_plans_in_project` from the example (registry already derives it from `plan_workflow.directory`). TDD across config-model, example-config integration, and deploy tests.
- [x] ✅ **Task 2.2 (F-PYFLOOR)**: `check_python3` now takes a pyproject path, raises the floor via `_pd_parse_pyproject_floor`, and derives the `(X.Y+)` diagnostic from the parsed floor; `check_all_prerequisites` forwards it; `install_version.sh` passes `$DAEMON_DIR/pyproject.toml`. `resolve_venv.sh` already passed pyproject (3.11 there is the documented floor-of-last-resort — left as-is). shellcheck clean; isolated-subshell regression test added.

### Phase 3: Low severity

- [x] ✅ **Task 3.1 (F-PROFLIST)**: Added `config_handler_names` + `all_profile_handler_names`; `apply_profile` warns on profile handlers absent from the target config; integration guard asserts every profile handler name exists in the shipped example.
- [x] ✅ **Task 3.2 (F-VENVSUM)**: Install summary prints `$VENV_PATH` instead of the deleted legacy `untracked/venv/` literal.

### Phase 4: Close-out

- [x] ✅ **Task 4.1**: 13/13 QA passing; daemon restarts RUNNING after the changes.
- [x] ✅ **Task 4.2**: Staged `config-changes/v3.26.0.yaml` (documentation-only `changed` entry for the opt-in flip, with migration note) and `truth-changes/v3.26.0.yaml` in `UNRELEASED/` for the next release.

## Dependencies

- Builds on Plan 00136 (exemplar + the `deploy_plan_workflow_if_enabled` SSoT entrypoint).
- F-PLANDEF and F-PLANDIR are coupled (both touch the migration validator + example config) — do together.

## Success Criteria

- [ ] No install-time env var acts as a second source of truth for config-governed state.
- [ ] No artifact/behaviour deploys on one install/upgrade path but not another.
- [ ] Python floor, plan directory, profile handler lists each have ONE authority.
- [ ] Example-config defaults agree with shipped handler state (deploy == runtime).
- [ ] 13/13 QA; daemon restarts RUNNING; behaviour changes carry config/truth-change notes.

## Notes & Updates

### 2026-06-23

- Findings catalogued from the Opus audit agent (read-only scan, all items
  verified against source with `file:line` citations). F-FASTPATH and F-SUMMARY
  were already resolved by Plan 00136 (the audit read a pre-fix snapshot);
  recorded as ✅ for completeness. Remediation of the remaining six is pending;
  F-PROFILE needs a user decision on the seed-vs-config-stored approach before
  building.

- All six remaining findings remediated with TDD, one checkpoint commit per
  finding (F-PROFILE+F-VENVSUM share `install_version.sh`; F-PLANDEF+F-PLANDIR
  are coupled). Delivery commits:

  - F-PROFILE + F-VENVSUM: `defe9fb`
  - F-PYFLOOR: `faa53e2`
  - F-PROFLIST: `026dde9`
  - F-PLANDEF + F-PLANDIR: `18c4a65`
  - UNRELEASED config/truth-change manifests: `d5c95cd`
  - End-to-end deploy gates updated for opt-in default: `a7ef263`

- F-PROFILE resolved as **seed-only**: a profile seeds the per-handler
  `enabled:` flags once at install; the yaml is the SSoT thereafter and the
  config-merge preserves the seed on upgrade (so no upgrade path re-applies a
  profile).

- F-PLANDEF/F-PLANDIR design note: the model default flip (True→False) is the
  KISS fix. An active example `plan_workflow: {enabled:false}` block was
  deliberately NOT added — it would merge into legacy client configs on
  upgrade, cause `migrate_plan_handler_options` to skip, and silently drop the
  legacy per-handler opt-in. A commented block + the model default avoids that.
  This is a behaviour change carrying the staged config/truth-change manifests.

- Final state: 13/13 QA, daemon RUNNING.
