# Callout: a wedged daemon no longer denies its own restart on the relay

**Plan**: 00466
**Audience**: operators

With the relay transport on, a daemon that accepts a `PreToolUse` call but
never answers made the relay deny every call, including the
`bin/hooks-daemon restart` its own deny message told the agent to run. The
relay now hands such a call to the bash forwarder, and `init.sh` judges it
with the same recovery exemption as every other transport failure. Only the
project's own launcher, run from the project root, gets through; everything
else is still denied, now without waiting on the daemon a second time.
Rebuild or redeploy the relay binary to pick this up.
