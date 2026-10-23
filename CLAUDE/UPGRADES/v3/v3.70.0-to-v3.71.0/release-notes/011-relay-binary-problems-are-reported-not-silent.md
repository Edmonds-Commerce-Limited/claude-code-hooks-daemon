# Callout: a missing relay binary is reported, and `transport on` says when it built one

**Plan**: 00529
**Audience**: operators

When `daemon.transport.relay_enabled` is true but the relay binary (`untracked/bin/hooks-relay`, or your `relay_binary` override) is missing or not executable, relay-eligible hooks run on the fallback transport, and until now only the status line said so. Three places now say it plainly. `bin/hooks-daemon transport on`, when it has to build or download the binary, prints `transport on: relay binary provisioned via <route> at <path>`, verifies the relay, and no longer prints "relay already enabled — nothing to do" after doing that work. `bin/hooks-daemon status` prints a `WARNING:` line naming the binary path and the fix `bin/hooks-daemon transport on`, whether or not the daemon is running; its exit code is unchanged and still means only running or not running (use `health` for a non-zero exit on a degraded state). A new SessionStart advisory, `relay_binary_checker` (on by default, priority 72), prints the same warning at the start of each session. Both are silent when the relay is disabled or the binary is executable. (reported as issue #131)
