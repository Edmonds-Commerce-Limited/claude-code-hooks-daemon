# Callout: a worktree's hooks now reach the worktree's own daemon

**Plan**: 00364
**Audience**: everyone

A deployed forwarder's relay hot path bakes absolute paths on purpose — it
must not compute anything at hook-run time — so a git worktree, which
inherits the tracked `.claude/hooks/*` byte for byte, dialled the MAIN
checkout's relay socket and was answered by the main checkout's daemon. Every
hook event in a worktree agent's session was judged by another checkout's
config, handlers and project handlers, with no error anywhere to say so. The
guard now also records the hooks directory it was generated for and checks
`${BASH_SOURCE[0]}` against it, so a copy running from another checkout
declines the relay and falls through to `init.sh`, which resolves that
checkout's own socket. No environment override is needed, and if you set
`HOOKS_DAEMON_RELAY_BINARY` to work around this you can drop it. The cost is
one legacy-transport round trip per hook in a copy, in exchange for the answer
coming from the right daemon.

A hook invoked by a RELATIVE path now takes the same fall-through, because the
baked literal is absolute. Claude Code always invokes hooks absolutely through
`$CLAUDE_PROJECT_DIR`, so this affects hand-run probes only.

The "Hooks daemon not installed" answer now names the checkout it is answering
for. That answer is `decision: block` for Stop and SubagentStop, which is
exactly what a working stop gate returns, so an uninstalled checkout used to
be indistinguishable from a protected one at the point where it mattered most.
