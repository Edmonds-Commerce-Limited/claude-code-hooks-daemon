# Task 2.2 — upgrade path: D3, D11, D12

**Branch**: `agent-afd947b6a4f6108c3-e60e8b34` (worktree
`/workspace/.claude/worktrees/agent-afd947b6a4f6108c3-e60e8b34`)
**Commit**: `a0ac90f5` (code, tests, Plan 00291 ticks, release-notes callout)

## Worktree setup

`./scripts/setup_worktree.sh` creates a NEW worktree and refused this one
(the harness had already made it), so the venv was built the way the script
does it: `ensure_venv` from `scripts/install/venv.sh` on this checkout, then
`uv sync --frozen --extra dev` into the resulting
`untracked/venv-workspace_claude_worktrees_agent-afd-43f7-py311-81c29529/`.
The package imports from this worktree's `src/` (verified), and the
`tests/conftest.py` source-tree guard passed on every run.

## D3 (HIGH) — fresh-clone upgrade rolled back at Step 4

Reproduced exactly as the ledger says: extracting the real Step 4 block of
`scripts/upgrade_version.sh` and running it under `set -euo pipefail` with
`VENV_PYTHON=""` exits 1 with `stop_daemon_safe: venv_python parameter required`.

Fix: Step 4 guards the call — with an empty `VENV_PYTHON` it prints
`No existing venv, so no daemon to stop — skipping daemon stop` and moves on.
`stop_daemon_safe`'s own contract (empty argument is a caller error, exit 1)
is left intact and pinned by a test, so the guard stays load-bearing.

Test: `tests/integration/test_upgrade_fresh_clone_stop_step.py` (5 tests) —
runs the real block with the real `daemon_control.sh` sourced: empty venv
completes and logs the skip; a stale venv path still completes; the call
is not at column 0.

## D11 (MEDIUM) — `v` prefix rejected by three loaders

`truth_changes`, `config_migrations` and `release_notes` each had a private
`_parse_version` that split on `.` and cast to int. All three now delegate to
one shared module, `src/claude_code_hooks_daemon/install/version_parse.py`
(`parse_version_tuple`, `strip_tag_prefix`), and
`breaking_changes_detector.parse_version` is built on it as well (keeping its
strict three-component contract and error messages).

Test: `tests/unit/install/test_version_parse.py` (14 tests) — bare, `v`, `V`,
double-digit components, only-the-prefix-is-forgiven, and the tag form
through each of the three public range loaders and `run_check_truth_changes`.

## D12 (MEDIUM) — retained config kept silently on install

Reproduced: the real Step 7 block of `scripts/install_version.sh`, run with a
pre-v3.40-shaped config (`status_line.daemon_stats.enabled: true`, none of the
later keys), printed only `Config already exists, keeping existing configuration`.

Fix: when a config is retained, Step 7 runs `run_check_config_migrations`
from the EARLIEST known manifest to `INSTALLED_VERSION`. The installer has no
record of the version the config was written for (a fresh clone has no venv
stamp), so the output says which baseline it assumed rather than presenting a
guess as fact, prints the advisory text, and points at
`check-config-migrations` for a re-run. It never rewrites the config and
never aborts the install (a crash in the advisory is a warning).

Test: `tests/integration/test_install_version_retained_config_advisory.py`
(5 tests) — advisory surfaces and names `daemon_stats`; baseline is named;
config bytes untouched; fresh install deploys the default with no advisory;
an unparseable retained config does not abort.

## QA

- 174 passed, 1 skipped across the new tests plus
  `test_truth_changes`, `test_config_migrations`, `test_release_notes`,
  `test_breaking_changes_detector`, `test_upgrade_version_bootstraps_when_no_venv`,
  `test_config_migrations_integration`.
- `ruff check` and `ruff format --check` clean on every touched file
  (two pre-existing unformatted files in `install/`, `client_validator.py`
  and `relay_deploy.py`, are untouched and not mine).
- `mypy --strict` clean on touched sources and tests.
- `shellcheck` on both scripts: only pre-existing SC1091 "not following
  source" info notices; nothing on the changed lines.
- Daemon NOT restarted (per instruction).

## Not done / for the coordinator

- Callout is `CLAUDE/UPGRADES/UNRELEASED/release-notes/13-upgrade-path-fresh-clone-and-v-prefix.md`;
  renumber at merge if another agent took 13.
- Plan 00291 Tasks 1.2, 1.3, 2.3 and Phases 3–4 remain open (out of Task 2.2
  scope).
- The end-to-end dummy-client run (`scripts/dummy-client-repo.sh create`)
  was not executed here; Plan 00362 Task 3.1 covers the client-mode smoke.
