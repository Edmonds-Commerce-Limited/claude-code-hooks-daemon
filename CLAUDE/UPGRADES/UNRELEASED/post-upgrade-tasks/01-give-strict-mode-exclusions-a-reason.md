# Task: Give every `exclude_paths` / `extra_whitelist` entry a reason in a `strict_mode` project

**Type**: config-migration
**Severity**: recommended
**Applies to**: projects with `daemon.strict_mode: true` that list plain strings under `exclude_paths` or `extra_whitelist`
**Idempotent**: yes

## Why

Entries of `exclude_paths` (project-wide and per-handler) and `extra_whitelist` may now be written as `{pattern, reason}`, so a later reader can tell why each exception exists. `daemon.strict_mode: true` asks for the reason on every entry. A plain string still works and still loads; under `strict_mode` the daemon reports each one as a config problem in the SessionStart advisory and logs a warning. Requiring a reason for every project is planned for the next major release.

## How to detect if this applies to you

Applies only when `daemon.strict_mode` is `true` in `.claude/hooks-daemon.yaml`. Sample: look for `strict_mode: true`, then list the entries under any `exclude_paths:` or `extra_whitelist:` key that are plain strings (a line starting `- "..."` or `- '...'`, not `- pattern:`). The SessionStart config-problem advisory names each one by location.

## How to handle

For each plain entry, write it as a mapping and state why the exception exists:

```yaml
exclude_paths:
  - pattern: "vendor/**"
    reason: "third-party code we do not edit"
```

Use the reason already given in an adjacent comment if there is one. Where nobody recorded why an exception exists, ask the user rather than inventing a reason; a placeholder such as `tbd`, `because` or `n/a` is rejected as a config error. Do not add, remove or widen any entry while converting.

## How to confirm

Restart the daemon and start a new session: the config-problem advisory no longer lists the entries, and `hooks-daemon validate-config` (or the daemon log) shows no `has no reason` warning.

## Rollback / if this goes wrong

Revert the YAML change with git. A plain string is always accepted, so reverting cannot stop the daemon starting.
