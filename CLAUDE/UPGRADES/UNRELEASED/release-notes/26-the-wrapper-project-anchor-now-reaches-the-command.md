# Callout: `bin/hooks-daemon`'s project anchor now actually reaches the command

**Plan**: 00374
**Audience**: operators

The wrapper anchors every invocation to the project it lives in by passing
`--project-root` ahead of the subcommand, and refuses to run at all rather
than let the CLI fall back to the working directory — "that would target
whichever project you happen to be standing in". The anchor never arrived.
Twenty-five subcommands declare their own `--project-root`, and argparse
writes a subparser's default into the namespace whether or not the flag was
supplied, so that `None` overwrote it and the fallback happened anyway. Two
more subcommands, `deploy-plan-workflow` and `agents`, defaulted the flag to
the working directory outright and could never receive the anchor at all.

If you run a wrapper by absolute path from another directory — a client
install from elsewhere, a worktree's wrapper from the main checkout — the
command now acts on the wrapper's own project, as documented. A
`--project-root` you supply yourself still wins.
