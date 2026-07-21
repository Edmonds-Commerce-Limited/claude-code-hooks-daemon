# Hooks Daemon — Plan Journalling Setup / Repair Notes

**Date**: 2026-07-21
**Context**: User asked whether plan journalling was properly enabled. It was not.

## Findings (before fix)

### Enforcement config

- `.claude/hooks-daemon.yaml` `plan_workflow:` block is only 5 lines (enabled, directory,
  workflow_docs, enforce_claude_code_sync). **No `qa:` subsection, no `qa.journal:` subsection.**
- Journal checks therefore run on daemon *defaults* (`PlanWorkflowQaJournalConfig`):
  - `enabled: true`, `mode: advise` (advisory only)
  - `dir_name: JOURNAL`, `freshness_days: 3`
  - `enforce_on_completion: false` ← no closing-journal advisory on completion
  - `grandfather_before: 0` ← docstring suggests dogfood repos set this to 163

### Missing client assets (installer `_deploy_journal_assets` / `_deploy_mkplan` should seed these)

The plan dir was scaffolded only partially (commit a847986 created README + Completed/ +
Cancelled/), so the full plan-workflow bootstrap never ran. Missing:

| Asset                       | Expected location                             | Purpose                                         | Status (before)                                 |
| --------------------------- | --------------------------------------------- | ----------------------------------------------- | ----------------------------------------------- |
| `mkplan.bash`               | `CLAUDE/Plan/mkplan.bash`                     | Plan scaffolder (daemon-owned)                  | MISSING                                         |
| `_JOURNAL_TEMPLATE_.md`     | `CLAUDE/Plan/_JOURNAL_TEMPLATE_.md`           | **Marker** gating mkplan's JOURNAL/ scaffolding | MISSING                                         |
| `PlanJournalling.md`        | `CLAUDE/PlanJournalling.md` (plan dir PARENT) | Journalling reference doc                       | MISSING (dangling ref from PlanWorkflow.md:214) |
| `_TEMPLATE_.md`             | `CLAUDE/Plan/_TEMPLATE_.md`                   | Plan template (client-owned)                    | MISSING                                         |
| `.plan-template-default.md` | `CLAUDE/Plan/.plan-template-default.md`       | Daemon-owned template snapshot                  | MISSING                                         |

Net effect: enforcement handlers exist (advise-only) but nothing makes journalling actually
*happen* for new plans, and PlanWorkflow.md points at a broken link.

## Fix approach

Invoke the daemon's single deploy site `deploy_plan_workflow_if_enabled(project_root, config_path)`
(install/plan_workflow.py) — it is idempotent (only fills gaps, never overwrites client files
except the daemon-owned mkplan.bash + snapshot). Config `plan_workflow.enabled: true` so it runs.

## Actions taken

Ran the daemon's own deploy API from `/workspace` (no cd into daemon dir):

```
$PYTHON -c 'from pathlib import Path; \
  from claude_code_hooks_daemon.install.plan_workflow import deploy_plan_workflow_if_enabled; \
  deploy_plan_workflow_if_enabled(Path("/workspace"), Path("/workspace/.claude/hooks-daemon.yaml"))'
```

Result — all gaps filled (idempotent, existing README kept):

- Deployed `CLAUDE/Plan/mkplan.bash` (chmod 755, executable ✓)
- Created `CLAUDE/Plan/_TEMPLATE_.md` (client-owned plan template)
- Created `CLAUDE/Plan/.plan-template-default.md` (daemon-owned snapshot)
- Created `CLAUDE/Plan/_JOURNAL_TEMPLATE_.md` (journal marker — turns on JOURNAL/ scaffolding)
- Created `CLAUDE/Plan/CLAUDE.md` (plan lifecycle instructions)
- Created `CLAUDE/PlanJournalling.md` (journalling reference — resolves PlanWorkflow.md:214 dangling link)

## Verification

- `mkplan.bash` lines 326-350: JOURNAL/ scaffolding is gated on the presence of
  `_JOURNAL_TEMPLATE_.md`. That marker now exists → new plans created via
  `mkplan.bash` will get a `JOURNAL/NNNNN-Journal-YY-MM-DD.md` day-file. ✓
- No daemon restart needed (these are on-disk assets read live; no config changed).

---

# Upstream report: no on-demand way to (re)deploy plan-workflow assets

**Component**: `install/plan_workflow.py` + `daemon/cli.py` · **Severity**: Medium
(silent — advertised feature is non-functional with no error) · **Version**: v3.47.0

## Root cause

- `install_version.sh:487` and both `upgrade_version.sh` paths DO call
  `deploy_plan_workflow_if_enabled`, gated on `config.plan_workflow.enabled`.
- Here the plan tree was scaffolded by a **separate manual commit** (a847986
  "Add Plan archive directory structure") rather than by the bootstrap, and the
  install-time deploy either ran with the workflow disabled or before the dir existed.
- **There is no on-demand CLI to (re)deploy plan-workflow assets** — the only
  triggers are a full install or upgrade. `add_parser` scan of `daemon/cli.py`
  shows only `plan-qa`, no `deploy-plan-workflow`/`plan-init`.
- So a user who flips `plan_workflow.enabled: true` after install, or partially
  hand-scaffolds the plan dir, is left with CLAUDE.md guidance pointing at a
  non-existent `mkplan.bash` and journalling advertised but non-functional. No
  error is surfaced anywhere — the feature is simply silently inert.

## Reproduction

1. Install the daemon, or start from a repo where the plan tree was created by
   hand (`README.md` + `Completed/` + `Cancelled/` only).
2. `.claude/hooks-daemon.yaml` has `plan_workflow.enabled: true`, no `qa.journal` overrides.
3. `CLAUDE/Plan/` has no `mkplan.bash` / `_TEMPLATE_.md` / `_JOURNAL_TEMPLATE_.md`;
   `CLAUDE/PlanJournalling.md` absent.
4. Follow CLAUDE.md's instruction `CLAUDE/Plan/mkplan.bash "foo"` → file not found.
5. No CLI command exists to fix it short of a full reinstall/upgrade.

## Suggested fixes (either/both)

1. **Add a CLI subcommand** — e.g. `daemon.cli deploy-plan-workflow` (or `plan-init`)
   that calls `deploy_plan_workflow_if_enabled(project_root, config_path)`. Gives
   config-flip / partial-setup recovery a documented entry point mirroring `plan-qa`.
2. **SessionStart drift advisory** — when `plan_workflow.enabled: true` but expected
   assets (`mkplan.bash`, `_JOURNAL_TEMPLATE_.md`, `PlanJournalling.md`) are missing
   from the plan dir, emit an advisory naming the remediation from (1). The daemon
   already advertises `mkplan.bash` via `plan_number_helper`, so it should notice when
   that script is absent.

The deploy is already idempotent (fills gaps only, never overwrites client files), so
exposing it as a repeatable command is safe.

## Config note (optional, NOT applied)

`plan_workflow.qa.journal` is absent from the yaml → journalling runs on defaults
(enabled, advise mode, enforce_on_completion:false, grandfather_before:0). Defaults
are sensible for a fresh repo. Did NOT set grandfather_before:163 — that value is
specific to the daemon's OWN repo (163+ existing plans to grandfather); this repo
has zero plans. Leaving defaults.
