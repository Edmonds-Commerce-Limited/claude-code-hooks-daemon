# Callout: deny messages and advice name the daemon wrapper that exists in a client install

**Plan**: 00556
**Issue**: #147
**Audience**: operators

A client install keeps the daemon's command-line wrapper at `.claude/hooks-daemon/bin/hooks-daemon`, and has no `bin/` directory at the project root. Many deny reasons, fix lines, advisories and CLI hints named `bin/hooks-daemon`, the self-install form, so the command they told the reader to run did not exist on a client install. Examples:

- the secret guard's `secret-meta` suggestion;
- the "Full detail" pointer on every rule;
- the generated CLAUDE.md block;
- `clear-goal`, `usage-pause clear` and the remote-docs fix lines.

Every runtime message now names the wrapper for the install mode in use:

- `.claude/hooks-daemon/bin/hooks-daemon` on a client install;
- `bin/hooks-daemon` on a self-install.

A test now fails on any new bare `bin/hooks-daemon` string in runtime code outside a short allowlist of self-install-only sites. The messages baked into the generated hook forwarder are unchanged, because no install mode is known when they run.

Nothing to do on upgrade. The generated CLAUDE.md block picks up the client form at the next daemon restart.
