# Callout: `list-venvs` and `prune-venvs` name the venv that is actually in use

**Plan**: 00474
**Audience**: client projects

`list-venvs` printed a "Current Python-env fingerprint" and `prune-venvs` printed "Current venv:" and "Current venv preserved:", all computed from the PROJECT root. Venvs are keyed on the daemon directory (`.claude/hooks-daemon/` in a client install), so the printed name belonged to no venv, and the venv the daemon was running from was not marked `current` by its name (GitHub issue 120). The same split showed in this project's own self-install, where the header named one fingerprint and the table marked another.

Both commands now ask the one resolver that the bootstrap and `ensure_venv` use. The first line of `list-venvs` reads `Current venv (the one the resolver selects): <fingerprint>` and names a venv that exists; the row for that venv carries the `current` marker. When a venv built now would get a different fingerprint (for example after a Python upgrade), `list-venvs` says so on a second line. `prune-venvs` reports the same name, and never selects the venv the resolver uses in either install mode.

The output text changed: anything that parses the old `Current Python-env fingerprint:` line needs updating. `list-venvs --json` is unchanged.
