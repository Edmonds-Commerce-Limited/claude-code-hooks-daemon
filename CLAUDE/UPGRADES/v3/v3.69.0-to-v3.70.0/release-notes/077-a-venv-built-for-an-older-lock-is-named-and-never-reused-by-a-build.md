# Callout: a daemon venv built for an older dependency lock is rebuilt by every build, and named when it still runs

**Plan**: 00474
**Audience**: client projects

A venv records the hash of the `pyproject.toml` and `uv.lock` it was built for. Every venv build (the upgrade, `install`, provisioning and the automatic first-venv build) now rebuilds a venv whose recorded hash differs from the current one, even when its daemon-version stamp matches. Before, a matching stamp let it be reused without a dependency the source had just added.

`restart` and a daemon started by a hook still do not build a venv. When the venv the daemon runs from was built for another lock, or records none, session start, `restart` and `status` now say so and name the fix: `bin/hooks-daemon repair`. `repair` also records the lock it synced for, so the daemon starts from the repaired venv and the notice clears.
