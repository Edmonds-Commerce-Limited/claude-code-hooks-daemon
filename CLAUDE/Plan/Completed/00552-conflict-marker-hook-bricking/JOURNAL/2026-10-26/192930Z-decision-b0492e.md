## 19:29 · decision · —

Decision: a NEW verb `repair-install`, not an extension of `repair`.

`repair` (Plan 00099, 00456) fixes the venv: it takes the venv build lock, stops the daemon, runs `uv sync` and imports the package. Its failure modes are a missing uv and a missing toolchain. The conflict-marker case needs none of that, and a user whose hooks are bricked should not be asked to have uv, wait for a sync, or have a daemon stopped. The two repairs also fail independently: a healthy venv with a conflicted stub, and a broken venv with healthy stubs, are both real. Overloading `repair` with flags would give one verb two unrelated preconditions. `reconcile-settings` is the other prior art: a small verb with a `--check` dry run, which `repair-install` mirrors.

Shape: `bin/hooks-daemon repair-install [--project-root P] [--check] [--reconcile-settings]`. The logic lives in `install/repair_install.py`; `cmd_repair_install` in cli.py only prints and sets the exit code.

- Redeploy goes through `generate_forwarder_content` (the installer's generator), so the Phase 1 parse guard and any relay guard are included. Sources are `<daemon dir>/.claude/hooks/*` and `<daemon dir>/init.sh`; a self-install is checked, not rewritten, because its tracked stubs are the templates.
- Every hook and init.sh gets `bash -n`; each is reported OK or BROKEN. settings.json is parsed; a file with conflict markers is reported and never rewritten, even with `--reconcile-settings`, and the human is told to resolve it by hand.
- `--reconcile-settings` is the only path that touches settings.json (Plan 00175: the daemon never rewrites it on its own). It delegates to `cmd_reconcile_settings`, so the backup and atomic-write guards stay in one place.
- `--check` writes nothing and exits 1 when anything is broken OR a file differs from what a redeploy would write (drift), like `reconcile-settings --check`. A real run exits 1 only while something is still broken.
