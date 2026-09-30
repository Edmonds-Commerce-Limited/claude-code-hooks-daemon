# Post-Upgrade Tasks — v3.66.0 → v3.67.0

> Convention and schema live in `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/README.md`. This file is the **per-release index** — populate it with the tasks that ship for this specific upgrade.

## About this directory

Task files here are **instructions for an LLM/human to follow after upgrading** from the source version to this target version. They are advisory only — nothing runs them automatically.

If no post-upgrade tasks apply to this release, delete this directory entirely before publishing the release. An empty `post-upgrade-tasks/` is worse than none — it suggests something is missing.

## Task index

<!-- BEGIN TASK INDEX -->

| File | Type | Severity | Applies to | One-line summary |
| ---- | ---- | -------- | ---------- | ---------------- |
| `01-remove-vendor-from-a-php-intelephense-override.md` | audit | recommended | PHP projects that followed the old `R-LSP-CONFIG-EXCLUDE` advice | Remove `**/vendor` from an intelephense override, which broke Composer types |
| `02-audit-daemon-outputs-for-secret-terms-under-a-non-default-word-list.md` | audit | recommended | Projects with a non-default `secret_word_list_path` | Audit logs and payload captures for terms the wrong list failed to redact |
| `03-add-modelsettings-entries-for-ccy-supervisor-effort.md` | config-migration | recommended | ccy sessions that relied on supervisor `/effort` injections | Pin effort in `modelSettings` now the supervisor no longer types it |
| `04-ignore-hooks-daemon-backups-directory.md` | config-migration | recommended | All prior versions | Gitignore `.claude/hooks-daemon-backups/` |
| `05-review-new-denials-from-strict-mode-and-safety-guards.md` | workflow-change | notification | `strict_mode: true` or SAFETY+BLOCKING handlers | Review new denials now `strict_mode` takes effect |

<!-- END TASK INDEX -->

## How an upgrading LLM should read this directory

1. Read this index first; skip any tasks whose **Applies to** does not cover the project's prior version.
2. For each remaining task, open its `.md`, follow the detection guidance, then act on the handling guidance.
3. Report a summary back to the user grouped by severity. `critical` tasks should block the user's next step until acknowledged; `recommended` and `optional` tasks can be reported without blocking.
