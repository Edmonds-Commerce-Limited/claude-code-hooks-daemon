# Callout: a wedged daemon no longer denies its own restart on the relay

**Plan**: 00466
**Audience**: operators

With the relay transport on, a daemon that accepts a `PreToolUse` call but
never answers made the relay deny every call, including the
`bin/hooks-daemon restart` its own deny message told the agent to run. The
relay now hands such a call to the bash forwarder, and `init.sh` judges it
with the same recovery exemption as every other transport failure. The
hand-off can only end in that exemption or a deny:

- it never starts the daemon or asks it again;
- an install, venv or CI state that would otherwise let a call through
  cannot answer it;
- the relay accepts only a complete deny or the exemption's own answer from
  the forwarder, and denies anything else itself;
- it has its own 10-second deadline, after which the relay denies.

The relay's own deny now names the project's launcher by absolute path.

`transport.timeout_seconds` is now capped at 45. The relay's wait, the
10-second hand-off and a 5-second margin must end before the 60-second hook
timeout the daemon registers, because Claude Code lets a `PreToolUse` call
run unjudged when its hook times out. A config above the cap is rejected
with that reason. Rebuild or redeploy the relay binary to pick this up.
