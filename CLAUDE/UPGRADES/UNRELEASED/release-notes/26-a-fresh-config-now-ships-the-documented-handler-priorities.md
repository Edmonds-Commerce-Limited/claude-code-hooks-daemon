# Callout: a fresh config now ships the documented handler priorities

**Plan**: 00422
**Audience**: client projects

The config that `init` writes disagreed with the daemon's own priority
constants in four places. The environment indicator (`💻`/`🐳`/`📦`)
rendered before the repository name, when it should come after it. A fresh
config now ships `git_repo_name` at 3, `account_display` at 5 and
`host_hostname` at 6. `security_antipattern` moves from 15 to 14, the band
that holds the other guards against content leaving the project. Existing
configs are not rewritten. If your `.claude/hooks-daemon.yaml` still has the
old values (5, 6, 7 and 15) and you want the documented order, change them to
the new ones. A test now compares every priority in the template against the
constants, so the two cannot drift apart again without a failing test.
