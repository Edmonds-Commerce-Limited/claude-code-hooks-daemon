# Callout: the "Not installed" message no longer points at rm -rf when a clone shares a mount

**Plan**: 00454
**Audience**: operators

A daemon clone present but with no usable venv for the current project path —
the normal state the first time a bind-mounted project is opened from a
second view (host vs container) — used to get the exact same "HOOKS DAEMON:
Not installed" message as a genuinely fresh checkout. Following that advice
was destructive: the skill's health probe cannot pass against the other
view's venv, so it escalates to `--force` on its own, and the installer's
force path is `rm -rf` on the whole daemon directory — deleting the other
view's venv, which lives inside it. Alternating between views compounded the
damage on every switch.

`init.sh` now tells the two states apart. A clone present with a missing venv
gets its own message: it names the clone as present, points at a
version-pinned same-version upgrade (`scripts/upgrade_version.sh`'s idempotent
path, which only builds the missing venv and deletes nothing), and explicitly
says not to install/force here. A genuinely absent clone is unchanged.

The discriminator required care: `HOOKS_DAEMON_ROOT_DIR` always exists once
`init.sh` has been sourced once, because it unconditionally creates its own
`untracked/` subdirectory on every source — so bare directory presence cannot
tell a real clone from a fresh checkout. The new check
(`_daemon_clone_present`) looks for `scripts/lib/resolve_venv.sh`, a file that
ships with a real clone and that nothing else creates.
