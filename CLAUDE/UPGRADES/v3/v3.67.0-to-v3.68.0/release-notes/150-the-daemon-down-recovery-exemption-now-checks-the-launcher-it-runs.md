# Callout: the daemon-down recovery exemption now checks the launcher it runs

**Plan**: 00466
**Audience**: operators

While the daemon cannot be reached, `PreToolUse` denies every call except
the exact recovery command (`bin/hooks-daemon restart` and its siblings).
That exemption used to trust the command text, so a `bin/hooks-daemon`
planted in whatever directory the Bash tool was standing in ran while every
guard was down. It now exempts a call only when it runs the project's own
launcher (a symlink to it counts):

- the project's launcher by absolute path, as every deny message prints it,
  works from any directory. A path that needs quoting is exempt only in the
  quoted form the message prints;
- the relative `bin/hooks-daemon` spelling works only from the project root.
  Run from anywhere else, or with no working directory in the hook input, it
  is denied like any other call.

The recovery subcommands are `restart`, `status`, `logs`, `stop`, `start`
and `repair`. `repair` rebuilds a broken venv, which a restart cannot fix.
Only spaces and tabs may surround the command: a newline or any other
control character before or after it is denied.
