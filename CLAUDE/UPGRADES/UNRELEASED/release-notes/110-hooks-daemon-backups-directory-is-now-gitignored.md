# Callout: the skill-rescue backup directory is now gitignored

**Plan**: 00466
**Audience**: client projects

`install/skills.py`'s `_preserve_replaced_skill` moves a deployed skill that
differs from the shipped one into `.claude/hooks-daemon-backups/skills/<name>`
before replacing it, rather than deleting a customisation outright. Neither
the deployed `.claude/.gitignore` template nor this repository's own copy
ignored that directory, so after a dogfood redeploy, or a client upgrade
that replaced an edited skill, `git status` showed
`?? .claude/hooks-daemon-backups/`, and a careless `git add -A` committed
the backup.

`.claude/.gitignore` now ignores `/hooks-daemon-backups/`. A fresh install
or a project whose `.claude/.gitignore` is regenerated picks this up
automatically; an existing project's `.claude/.gitignore` predates the fix
and needs the line added by hand — see the post-upgrade task
`04-ignore-hooks-daemon-backups-directory.md`.
