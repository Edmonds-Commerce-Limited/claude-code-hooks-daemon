# Task: ignore `.claude/hooks-daemon-backups/`

**Type**: config-migration
**Severity**: recommended
**Applies to**: all versions before this fix (Plan 00466 N105)
**Idempotent**: yes

## Why

`install/skills.py`'s `_preserve_replaced_skill` moves a deployed skill that
differs from the shipped one into `.claude/hooks-daemon-backups/skills/<name>`
rather than deleting it, so a customisation is never silently lost on
upgrade. Neither the deployed `.claude/.gitignore` template nor this
repository's own copy ignored that directory, so after any redeploy that
rescued an edited skill, `git status` shows
`?? .claude/hooks-daemon-backups/`, and a careless `git add -A` commits the
backup. The fix adds `/hooks-daemon-backups/` to `.claude/.gitignore`, but a
project's existing `.claude/.gitignore` was written before the fix and does
not pick it up on its own — upgrading only changes what a FRESH install or
redeploy of `.claude/.gitignore` would contain, not a file already on disk.

## How to detect if this applies to you

```bash
grep -q 'hooks-daemon-backups' .claude/.gitignore || echo "missing"
```

If that prints `missing`, this task applies. Also check whether a backup
directory already exists and is tracked or untracked-and-visible:

```bash
git status --porcelain .claude/hooks-daemon-backups/ 2>/dev/null
```

## How to handle

Add this line to `.claude/.gitignore` (a new section, or alongside the
existing backup-directory entries such as `hooks.bak/`):

```
/hooks-daemon-backups/
```

If `git status` already showed `.claude/hooks-daemon-backups/` as tracked
(committed by an earlier careless `git add -A`), untrack it without deleting
the files on disk:

```bash
git rm -r --cached .claude/hooks-daemon-backups/
```

## How to confirm

```bash
git status --porcelain
```

No longer lists `.claude/hooks-daemon-backups/` as untracked.

## Rollback / if this goes wrong

The change is a single added `.gitignore` line (plus, if applicable, an
untracking of already-committed backup files that stay on disk); revert with
`git diff`/`git restore` on `.claude/.gitignore` if unwanted.
