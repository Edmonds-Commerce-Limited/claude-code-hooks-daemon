# Callout: provision repairs a stale venv

**Plan**: 00581
**Audience**: client projects

`bash .claude/provision.sh` reported "nothing to do" whenever the daemon clone was already at the expected version, even
when a pull had changed `pyproject.toml` or `uv.lock` and left the venv built for the old lock. The restart path warned
"DAEMON VENV NOT BUILT FOR THIS SOURCE" while provisioning said all was well. A foreground run now checks the venv's
lock hash; a stale (or unreadable) one is rebuilt through the existing bootstrap repair, and the output says so. A
`--background` run never rebuilds: it reports the stale venv and names `hooks-daemon repair`. A venv that matches is
unchanged, and the version-mismatch sync and fresh provisioning are unchanged. GitHub #168.
