# Callout: the recovery exemption checks that `HOOKS_DAEMON_ROOT_DIR` belongs to the project

**Plan**: 00466
**Audience**: operators

While the daemon cannot be reached, `PreToolUse` exempts only the command
that runs this install's launcher. "This install" came from
`HOOKS_DAEMON_ROOT_DIR`, which can be inherited from the environment that
started Claude Code as well as set in `.claude/hooks-daemon.env`. The
launcher always manages the project it finds from its own location, so a
value naming another project's install made the deny name, and exempt, a
command that recovers that other project.

Now the value counts only when the launcher under it manages this project.
If it does not, no command is exempt: the deny says that
`HOOKS_DAEMON_ROOT_DIR` is not an install of this project and names the
command a human can run with the `!` prefix. Correct or unset the variable
to restore the exemption.

The deny `init.sh` writes, the deny `hooks-relay` writes and the deny the
daemon writes now choose that launcher by the same rule, so they always name
a command the exemption accepts. Regenerated forwarders hand the relay the
daemon root in `HOOKS_DAEMON_RELAY_DAEMON_ROOT`; a relay run from an older
forwarder assumes the client layout, `.claude/hooks-daemon`.
