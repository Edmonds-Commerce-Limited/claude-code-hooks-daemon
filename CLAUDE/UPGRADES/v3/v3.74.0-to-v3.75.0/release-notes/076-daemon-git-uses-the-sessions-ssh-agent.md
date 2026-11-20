# Callout: the daemon's remote git calls use the session's SSH agent

**Plan**: 00594
**Audience**: operators

A daemon started by an upgrade or restart outside the session shell has no `SSH_AUTH_SOCK`, so its `git fetch`, `git push` and `git ls-remote` calls to an ssh remote could not authenticate. The daemon now reads `SSH_AUTH_SOCK`, and only that variable, from the connecting hook process's `/proc/<pid>/environ` when a remote git call is made, and passes it to that one git subprocess. The value is used only when it is an absolute path to a socket owned by the daemon's own uid; otherwise the daemon's own environment applies. It is never logged and never stored on the payload. `GIT_SSH_COMMAND`, `GIT_SSH`, `GIT_ASKPASS`, `SSH_ASKPASS` and `SSH_AGENT_PID` are never taken from a peer. The "daemon has no SSH_AUTH_SOCK" hint on a failed `ls-remote` is no longer shown when a socket was forwarded. No configuration is needed. The status-line background fetch and the version check are unchanged.
