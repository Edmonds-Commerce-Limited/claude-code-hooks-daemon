# Task 1.8 — optimise manifests on a client install; stale `daemon_stats` flagged

**Branch**: `agent-ac4aa94d7dab4d302-20ef3fa7` (worktree of main)
**Report section**: 8 (LOW)

## What was actually wrong

**(a)** The manifests were never missing from a client install. The daemon is
delivered as a git checkout, so `.claude/hooks-daemon/CLAUDE/UPGRADES/config-changes/`
is already there, and `config_migrations._default_manifests_dir()` already
resolves to it. The defect was confined to the optimise SKILL text:
`optimise-invoke.sh` told the procedure to read `CLAUDE/UPGRADES/config-changes/v*.yaml`
relative to PROJECT_ROOT and to "skip silently" when absent — which on every
client install it was. No packaging change was needed; pointing the
procedure at the installed path was the fix.

**(b)** The v3.43.0 manifest already carried a `changed` entry for
`daemon_stats` with `recommended_value: false`, but keyed on the HANDLER
MAPPING (`handlers.status_line.daemon_stats`). The comparison was therefore
`{enabled: true, priority: 30} != False` — true for every config, including
one with `enabled: false` and one with no block at all (`UNSET != False`).
Verified against the real CLI before the change: all three shapes produced
the suggestion. It was undifferentiated noise rather than a targeted flag.

## Changes

- `src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/optimise-invoke.sh`
  (and the deployed `.claude/skills/hooks-daemon/` copy, kept identical):
  resolves `DAEMON_DIR` alongside `DAEMON_CLI`, derives `MANIFESTS_DIR` and
  `RUN_STATE` from it, prints all three in the Detected Environment block.
  Step 0 now runs `DAEMON_CLI check-config-migrations --from <last run> --to <daemon version>`
  (the daemon's own reader) and reads manifests from `MANIFESTS_DIR`; a
  missing directory is reported as an incomplete install, not skipped.
- `optimise.md` and `CLAUDE/LLM-UPDATE.md`: name the installed path.
- `src/claude_code_hooks_daemon/install/config_migrations.py`: new optional
  `only_if_set` field on `changed` entries — when true, an absent key
  produces no suggestion (default already matches). Documented in
  `CLAUDE/UPGRADES/config-changes/SCHEMA.md`.
- `CLAUDE/UPGRADES/config-changes/v3.43.0.yaml`: entry re-keyed to
  `handlers.status_line.daemon_stats.enabled` with `only_if_set: true`. The
  migration note already carries the release-note reason (arrow moved to
  `upgrade_notifier`), so the upgrade summary prints
  `Recommended: enabled = false  (your config: true)` plus that note.
- Release-notes callout: `CLAUDE/UPGRADES/UNRELEASED/release-notes/13-optimise-reads-installed-manifests-and-flags-stale-daemon-stats.md`.

## Tests

- `tests/unit/scripts/test_optimise_invoke_manifests_dir.py` — runs the real
  script in a client-shaped and a self-install-shaped git repo, asserts the
  printed manifests dir is the daemon checkout's and exists; static checks
  that neither the script nor `optimise.md` carries the project-relative
  path, that Step 0 names `MANIFESTS_DIR` and `check-config-migrations`, and
  that the deployed copy matches source.
- `tests/unit/install/test_daemon_stats_migration_advisory.py` — against the
  REAL manifest tree for 3.41.0→3.62.1 (and from 3.39.0): enabled override
  flagged once, with `upgrade_notifier` in the note; disabled, absent, and
  block-without-`enabled` produce nothing; text output asserted.
- `tests/unit/install/test_config_migrations_recommend.py` — `TestOnlyIfSet`
  schema and behaviour cases.

Verification: 291 tests green across the manifest-tree consumers
(`test_config_migrations*`, `test_config_cli`, integration, repo hygiene,
docs corpus, all `tests/unit/scripts`); `ruff check`, `ruff format`,
`mypy --strict` clean on touched Python; `shellcheck` clean on the script.
Daemon not restarted (as instructed).

## Notes for the coordinator

- The worktree had no venv; `scripts/setup_worktree.sh` creates a NEW
  worktree rather than provisioning an existing one, so I ran its
  `ensure_venv` step directly and installed the `[dev]` extras
  (`uv sync --frozen` does not include them).
- Task 1.8's wording ("deploy them with the daemon") assumed the manifests
  were absent on clients; they are not. PLAN.md may want that line adjusted
  when the task is ticked.
