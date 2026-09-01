# Task: Migrate `monorepo_subproject_patterns` to `projects:`

**Type**: config-migration
**Severity**: critical
**Applies to**: any project setting `handlers.pre_tool_use.markdown_organization.options.monorepo_subproject_patterns`
**Idempotent**: yes

## Why

Plan 00300 (hard cutover, owner ruling) removed the `monorepo_subproject_patterns` regex-pattern alias outright. `projects:` (Plan 00296) is now the ONLY sub-project resolution mechanism for `markdown_organization` and `tdd_enforcement`. The daemon fails config validation at startup while the old option is still set — there is no silent fallback, and no override.

## How to detect if this applies to you

Check the project's `.claude/hooks-daemon.yaml` for the key:

```bash
grep -n "monorepo_subproject_patterns" .claude/hooks-daemon.yaml
```

If it prints nothing, this task does not apply. If the daemon fails to start with a validation error naming `monorepo_subproject_patterns`, this task applies.

## How to handle

1. Run the daemon (or `bin/hooks-daemon validate-config`) and read the printed error — it contains a paste-ready `projects:` YAML block for every LITERAL (non-wildcard) pattern, e.g. `packages/api` becomes:

   ```yaml
   projects:
     - name: api
       root: packages/api
   ```

2. For any pattern the error could not auto-translate (it contained a regex wildcard, e.g. `packages/[^/]+`), declare one `projects:` entry per REAL sub-project directory by hand — the regex only described a shape, never concrete paths.

3. Delete the `monorepo_subproject_patterns` key from `.claude/hooks-daemon.yaml` entirely.

4. Restart the daemon and confirm it starts cleanly.

## How to confirm

`bin/hooks-daemon validate-config` (or a daemon restart) succeeds with no error mentioning `monorepo_subproject_patterns`.

## Rollback / if this goes wrong

There is no in-place rollback for this version — the option is gone, not deprecated. If the migration is not ready, stay on the prior daemon version until it is; that is the documented backward-compat path for this release.
