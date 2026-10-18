# Callout: prune-venvs never selects the venv the daemon is running from

**Plan**: 00517
**Audience**: client projects

The live-venv guard behind `prune-venvs`, `list-venvs` and `disk-usage` took the live venv from the resolver's `bin/python` after following its symlink, which for a real venv is the system interpreter, so the guard compared against `/usr` and never matched the venv. A running venv whose fingerprint differed from the current one was therefore listed by `prune-venvs --all-except-current --dry-run` and removed by `--force`. The guard now identifies the live venv by its directory: the venv the resolver selects (without resolving the `bin/python` symlink) and the running interpreter's `sys.prefix`. No `prune-venvs` mode (`--all-except-current`, `--stale`, `--legacy`) can select either, and both are reported as current by `list-venvs`.
