# Callout: the last venv build result is recorded per view

**Plan**: 00608
**Audience**: operators

`untracked/.venv-bootstrap.result` was one file written by every view of a checkout (a host and a container mounting the same tree), so the last writer replaced the other view's record. The result is now one file per view, `untracked/.venv-bootstrap-<fingerprint>.result`, keyed by the venv fingerprint exactly as the build log `untracked/.venv-bootstrap-<fingerprint>.log` is. The bash build paths (`venv.sh`, `venv_bootstrap.sh`) and the Python repair write it; the format and keys are unchanged.

The readers that run without a venv (`hooks-daemon status`, the wrapper's `diagnose` and failure output, the stop hook, the `probe` state) cannot cheaply tell which view they are, so they show the newest record of any view; its `log=` line names the fingerprint of the view it belongs to.

Upgrade: the old single `.venv-bootstrap.result` is neither written nor read any more, and no fallback read is kept. It is a diagnostic of the last build only, the next build in each view writes its own record, and reading a file that either view might have written is the defect this removes. A leftover old file is harmless and can be deleted.
