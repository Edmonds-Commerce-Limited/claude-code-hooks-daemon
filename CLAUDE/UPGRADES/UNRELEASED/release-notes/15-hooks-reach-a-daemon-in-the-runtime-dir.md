# Callout: hooks reach a daemon whose socket fell back to the runtime dir, and an upgrade always serves the project it was given

**Plan**: 00291
**Audience**: everyone

Two defects the php-qa-ci canary exposed on a deep project path.

When a project's default socket path is longer than the AF_UNIX limit, the
daemon puts its socket and its PID file in the runtime directory
(`$XDG_RUNTIME_DIR` or `/run/user/<uid>`) and leaves a discovery file
behind. The hook launcher in `init.sh` followed that file for the socket
but kept looking for the PID file at the long default path, so it decided
no daemon of ours was running, refused to take over a live socket that was
"not ours", and every hook reported `daemon_startup_failed` while
`hooks-daemon status` showed the daemon RUNNING. The launcher now follows
the PID file to the same place as the socket. A client whose project sits
deep enough in the filesystem to trigger the fallback had no working hooks
after an install or upgrade until now.

Separately, both Layer 2 install and upgrade orchestrators invoked the
daemon CLI without naming a project, so the daemon they started and
verified belonged to whatever directory the shell was standing in. Driven
from another project's checkout, an upgrade reported a clean success for a
client it had not started a daemon for. Both scripts now anchor themselves
at the project root they were given before their first step.
