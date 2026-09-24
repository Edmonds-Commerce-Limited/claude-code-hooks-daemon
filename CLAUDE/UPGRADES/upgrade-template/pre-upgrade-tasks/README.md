# Pre-Upgrade Tasks — [vX.Y → vX.Z]

> Convention, schema and the detection contract live in `CLAUDE/UPGRADES/UNRELEASED/pre-upgrade-tasks/README.md`. This file is the **per-release index** — populate it with the tasks that ship for this specific upgrade.

## About this directory

Task files here describe changes a project must hear about **before** this version is deployed into it. The upgrade gate runs each task's `**Detect**` pattern over the project being upgraded, names every hit at `file:line`, and stops the upgrade until the upgrading agent acknowledges it. The owner must also approve when a `critical` task finds anything.

If no pre-upgrade tasks apply to this release, delete this directory entirely before publishing the release.

## Task index

<!-- BEGIN TASK INDEX — populate with the tasks moved in from UNRELEASED/ at release time -->

| File                 | Type                                                                                    | Severity                            | Applies to              | Detect      | One-line summary  |
| -------------------- | --------------------------------------------------------------------------------------- | ----------------------------------- | ----------------------- | ----------- | ----------------- |
| `NN-example-task.md` | audit \| config-migration \| data-migration \| workflow-change \| notification \| other | critical \| recommended \| optional | e.g. `≤vX.Y.Z` or `all` | `the-regex` | Short description |

<!-- END TASK INDEX -->
