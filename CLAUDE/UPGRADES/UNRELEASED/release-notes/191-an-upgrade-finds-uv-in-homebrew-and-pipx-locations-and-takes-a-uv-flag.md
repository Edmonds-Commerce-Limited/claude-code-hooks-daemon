# Callout: an upgrade finds uv in Homebrew and pipx locations, and takes `--uv`

**Plan**: 00474
**Audience**: operators

The upgrade resets `PATH` to fixed system locations so nothing the caller
names can choose the `uv` that builds the venv, and it looked for `uv` only on
that `PATH` and in `~/.local/bin`. A `uv` installed anywhere else, such as a
Homebrew prefix, failed with "uv not found" (ledger 00474 N271).

The upgrade now also searches, after the trusted `PATH` and `~/.local/bin`:
`$PIPX_BIN_DIR` when it is set to an absolute path, `/opt/homebrew/bin`,
`/usr/local/bin` and `/home/linuxbrew/.linuxbrew/bin`. Each of these must be
owned by root or the running user and not group- or world-writable, so a
user-owned Homebrew prefix counts. A `uv` only the caller's own `PATH` names
is still never run.

For a `uv` elsewhere, pass it for that run: `scripts/upgrade.sh --project-root <path> --uv /absolute/path/to/uv`. It must be an absolute path to an
executable file, or the upgrade stops and says so. There is no config key for
it. The "uv not found" error now names both fixes.

`upgrade_approval_guard` denies an agent passing `--uv` or setting
`PIPX_BIN_DIR` on an upgrade command, as it does the other variables that steer
what builds the venv: run the upgrade yourself in your own terminal.
