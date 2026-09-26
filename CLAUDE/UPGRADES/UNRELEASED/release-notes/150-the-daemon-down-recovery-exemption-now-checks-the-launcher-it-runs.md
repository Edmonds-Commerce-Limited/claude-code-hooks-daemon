# Callout: the daemon-down recovery exemption now checks the launcher it runs

**Plan**: 00466
**Audience**: operators

While the daemon cannot be reached, `PreToolUse` denies every call except
the exact recovery command (`bin/hooks-daemon restart` and its siblings).
That exemption used to trust the command text, so a `bin/hooks-daemon`
planted in whatever directory the Bash tool was standing in ran while every
guard was down. It now resolves the launcher against the Bash tool's working
directory and exempts the call only when that is the project's own launcher
(a symlink to it counts). Run the recovery command from the project root; run
from anywhere else, or with no working directory in the hook input, it is
denied like any other call.
