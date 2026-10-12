# Task 5.2a (#78): provision syncs an existing clone

Branch `worktree-plan-00477-sync`. Targeted tests, black, ruff, mypy and shellcheck are clean (shellcheck reports only the pre-existing SC1091 info on `source`).

## What changed

- `provision.sh` (source of truth; `.claude/provision.sh` is a symlink to it). The clone-present branch now compares `_clone_version` with the expected version. Equal: "already at vX.Y.Z", exit 0. Different: `_provision_sync_clone`.
  - Refusals, nothing touched: no `.git` / not its own toplevel; `remote.origin.url` (raw config, so insteadOf does not hide a foreign URL) not equal to `PROVISION_REPO_URL`; `git status --porcelain --untracked-files=all` outside `untracked/` not empty (gitignored files are fine); a leftover set-aside venv from an earlier sync. Each names the reason and the manual route (`/hooks-daemon upgrade`, or move the dir aside).
  - Records HEAD, fetches exactly `refs/tags/vX.Y.Z` (depth 1) from the fixed URL, verifies the TAG's `version.py` with `git show` before any checkout (a tag it fetched is removed again if it lies), checks out, runs the gate, sets the current venv aside, `scripts/venv_bootstrap.sh repair`, `bin/hooks-daemon restart`.
  - `_provision_sync_abort` on any failure after the checkout: checks the recorded commit out again, puts the set-aside venv back (or rebuilds), restarts the old daemon, and fails with "The previous version vX is back in place".
  - New flag `--skip-reading-confirmation[=digest]`; any other argument is refused.
- Header comment updated (usage, sync paragraph, "What it never does").
- Drift advisories now name `bash .claude/provision.sh` for a version-drift sync, and say `upgrade` is for moving the project: `init.sh` (`ensure_daemon` mismatch message, config source and header-behind case; header-ahead keeps the regenerate remedy), `version_check._drift_context`, `daemon_sync_after_merge` (new path when the pull touched the config and `daemon.expected_version` differs from the running version; the marker-doc advice is unchanged otherwise).
- Docs: skill `provision.md` and `SKILL.md` (source and deployed copies kept byte-equal), `docs/guides/TROUBLESHOOTING.md` (new version-drift entry), release note `031` (`# Callout: `).
- Tests: `tests/integration/test_provision_sh.py` (fixture origin now has a gated tag `v3.62.0` with the real gate files and a guide for 3.61.0 to 3.62.0, a `.gitignore`, and a changed `uv.lock` on main), `tests/venv_bootstrap_sandbox.py` (stub `restart` handled like `start`), updated assertions in the three advisory test files, new daemon_sync tests. Written RED first (the equal-version test failed against the old script).
- PLAN.md: Task 5.2a ticked; 5.2 stays open.

## How the gate is invoked (as `scripts/upgrade_version.sh` does)

`upgrade_gate_standalone.py` of the target tree, under `env -i PATH=$GATE_SAFE_PATH`, with a Python 3.11+ found by `find_latest_python` in the trusted path (HOOKS_DAEMON_PYTHON and VENV_PATH unset), `timeout 300`, a nonce-headed verdict file in a fresh `mktemp -d -p /tmp`, `--to/--target-stamp/--target-ref vX.Y.Z`. FROM side: the clone's own venv stamp (`.daemon-version`, only when the venv is one of the clone's `untracked/venv-*`), else `--from <version before the sync>`. `env_sanitise.sh` and `python_discovery.sh` are sourced from the target tree in a subshell. A constants test pins the python floor, timeout and stop code equal to upgrade's. Exit 3 (NEEDS_ACKNOWLEDGEMENT) prints the listing and the exact `bash .claude/provision.sh --skip-reading-confirmation=<digest>`, restores the clone and exits 3.

## Deviations from the brief, and why

1. **Gate runs after the checkout, not before.** The gate reads the target's `CLAUDE/UPGRADES` tree and records its receipt against the daemon dir, and `upgrade_version.sh` also runs it once the daemon dir sits on the target. Running it against a temp export would bind the receipt to the wrong directory, so a later same-version upgrade would see an unknown range. A gate stop (or a gate failure) restores the recorded checkout, so HEAD and the working tree are as before; no venv was touched and the daemon was not restarted. The fetched tag ref and objects stay in the clone, as with any fetch (a tag refused for a lying `version.py` is removed again).
2. **Target predating the gate:** if `upgrade_gate_standalone.py` is absent from the target tree the sync prints "predates the pre-deploy gate, so there is none to run" and goes on. That mirrors upgrade: the target's own `upgrade_version.sh` has no gate either.
3. **Venv set aside.** `ensure_venv` rebuilds by `rm -rf` of the fingerprint venv, so a failed build leaves none. The sync therefore moves the clone's own venv to `untracked/.sync-backup-<name>` before the build and moves it back on failure (then runs the old `repair` to verify). Removed on success. Not in the brief; needed for "restore its venv".
4. **Restart on rollback** happens when the venv phase had begun (the old daemon may have lost its venv under it), not for a gate stop.
5. The gate subshell runs with errexit suspended (it is called inside `||`), so its steps are checked explicitly; the verdict-file rule is the same as upgrade's.

## Not done

- The gate receipt is recorded on PROCEED before the venv build, as in upgrade; a sync that then fails leaves a receipt for a version that did not install (same as an upgrade that fails after the gate).
- The status-line text "VERSION MISMATCH - upgrade needed" (`init.sh`, documented in `CLAUDE/Architecture/StatusLine.md`) still says upgrade: it was not among the three messages named.
- `CLAUDE/LLM-UPDATE.md` does not cover this case, so it is unchanged.
- Task 5.2's background sync and "old daemon serves until the new one is ready" are out of scope.
