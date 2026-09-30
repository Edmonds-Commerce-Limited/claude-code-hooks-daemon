# Callout: self-install checkouts now expose the conventional CLI path

**Plan**: 00455
**Audience**: handler authors

A self-install (dogfood) checkout of this repository now also has the daemon
CLI at `.claude/hooks-daemon/bin/hooks-daemon` -- the same path every normal
client install already has -- alongside the existing `bin/hooks-daemon`.
It is a relative symlink the daemon creates for itself on first start (main
checkout or worktree), gitignored like the rest of `.claude/hooks-daemon/`.
External tooling that expects the conventional path no longer needs a
special case for this repository's own checkout.
