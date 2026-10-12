# Callout: an upgrade now removes stale venvs, and only those it can show are stale

**Plan**: 00474
**Audience**: everyone

A normal client upgrade checks the target out first, so it always took the already-at-target path in `scripts/upgrade_version.sh`, which never cleaned up old venvs; installs kept a `venv-*` directory per past version. That path now calls `eager_cleanup_stale_venvs` after the verified restart and the post-install checks. The cleanup no longer removes every venv except the current one: a `venv-*` directory is removed only when its `.daemon-metadata.json` `lock_hash` is readable and differs from the current source's, and its name carries this checkout view's path slug or no slug. Another view's slugged venv (a host and a container sharing one checkout), a venv whose `lock_hash` matches, and a venv with missing or unreadable metadata are kept, each with a `Kept venv:` log line giving the reason. When the current `lock_hash` cannot be computed, nothing is removed. The decision lives in `paths.py list-stale-venvs`.
