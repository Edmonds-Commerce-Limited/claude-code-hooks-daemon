# Pre-Upgrade Tasks — v3.63.0 → v3.64.0

> Convention, schema and the detection contract live in `CLAUDE/UPGRADES/UNRELEASED/pre-upgrade-tasks/README.md`. This file is the **per-release index** for this specific upgrade.

## About this directory

Task files here describe changes a project must hear about **before** v3.64.0 is deployed into it. The upgrade gate runs each task's `**Detect**` pattern over the project, names every hit at `file:line`, and stops the upgrade until it is acknowledged. The owner must also approve when a `critical` task finds anything.

## Task index

<!-- BEGIN TASK INDEX -->

| File                                           | Type            | Severity | Applies to                                                   | Detect                     | One-line summary                                                                                               |
| ---------------------------------------------- | --------------- | -------- | ------------------------------------------------------------ | -------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `01-rewrite-plan-qa-json-level-to-severity.md` | workflow-change | critical | upgrades from ≤v3.63.x whose tooling parses `plan-qa --json` | `plan[-_]qa\b[^\n]*--json` | `plan-qa --json` emits `severity`, not `level`: rewrite every consuming call site before the new version lands |

<!-- END TASK INDEX -->
