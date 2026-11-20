# Task: Remove `mode: copy` worktree seeds of a file the secret guard protects

**Type**: config-migration
**Severity**: recommended
**Applies to**: all projects whose `worktree_create` `seed` option uses copy mode
**Idempotent**: yes
**Detect**: `^\s*(default_)?mode:\s*["']?copy\b`
**Detect in**: `.claude/hooks-daemon.yaml`, `.claude/hooks-daemon.yml`

## Why

From this release, worktree creation refuses a `worktree_create` `seed` entry in copy mode whose source is a path the `secret_file_guard` protects. It also refuses one whose source holds or links to such a path (Plan 00613). The refusal happens before `git worktree add`, so every worktree creation fails until the entry is removed.

A copy put the protected content under a second path. A project-anchored glob may not cover that path, and `git add -A` could commit it. If the guard config cannot be read, every copy entry is refused.

## How to detect if this applies to you

The gate has listed each line that sets copy mode, either an entry's `mode: copy` or the seed list's `default_mode: copy`. A `default_mode: copy` line covers every entry that names no mode of its own.

For each copy-mode entry, check whether its path is protected. It is protected when it matches a shipped default glob of the `secret_file_guard`, or a glob in that handler's `protected_paths` option. For a directory, check every path inside it, including paths reached through links.

Do not open the file to decide. The question is about its NAME. Name matches are exactly what the guard judges.

## How to handle

Remove each copy-mode entry whose path is protected from the `seed` list. If the entry relies on `default_mode: copy`, remove that entry.

Entries in symlink mode are not refused. Whether to seed a protected file at all is the project owner's decision, not the upgrading agent's.

## How to confirm

After the upgrade, run `hooks-daemon check-worktree-seed`. It must list no entry under `REFUSED`. That section reports, in the executor's own words, each copy-mode entry that worktree creation would refuse.
