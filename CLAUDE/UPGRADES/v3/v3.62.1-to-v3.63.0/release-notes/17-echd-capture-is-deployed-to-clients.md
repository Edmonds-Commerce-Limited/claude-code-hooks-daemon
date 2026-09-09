# Callout: echd-capture is deployed to clients, and guidance names its real path

**Plan**: 00362
**Audience**: client projects

The `echd-capture` output-capture helper that `pipe_blocker` recommends
instead of `| tail` is now installed and upgraded into
`.claude/hooks-daemon/bin/echd-capture` beside the CLI wrapper, so the
`echd-capture: command not found` a client hit is closed. The injected
CLAUDE.md guidance names the helper by its project-relative path, and only
when that file exists; otherwise it offers the redirect-to-file recipe alone,
and the post-install validator warns when the helper is missing.
