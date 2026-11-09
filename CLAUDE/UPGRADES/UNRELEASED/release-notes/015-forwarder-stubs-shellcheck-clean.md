# Callout: generated forwarder stubs pass shellcheck

**Plan**: 00577
**Audience**: client projects

Every generated `.claude/hooks/*` forwarder stub assigned `HOOKS_DAEMON_RELAY_UNUSED` in its relay hot path without
`export`. `shellcheck --severity=warning` reported SC2034 (appears unused) on it, once per stub, so a client that lints
its shell scripts failed after every upgrade, and the stubs are regenerated on every upgrade, so the client could not fix
it locally. The assignment is now `export HOOKS_DAEMON_RELAY_UNUSED=...`, the form shellcheck treats as used externally.
Behaviour is unchanged: `init.sh` reads the variable and unsets it before the stub starts the daemon. A test now
shellchecks the stub generated for every event. GitHub #163.
