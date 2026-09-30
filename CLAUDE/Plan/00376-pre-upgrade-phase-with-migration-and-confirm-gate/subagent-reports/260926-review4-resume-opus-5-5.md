# Plan 00376: review 4 resume (260926, Opus 5.5)

Branch `worktree-d-00376`. Resumed after the previous agent was lost
mid-round. The worktree held only the untracked review report
(`260925-plan376-review4.md`); `src/` and `tests/` had no uncommitted work,
so there was nothing partial to judge. The report was committed unchanged
(`3ec0b8e8d`).

Every finding is fixed with a test that was RED first. The gate was NOT
queued: an independent review comes next.

## Findings and fixes

| Finding   | Fix                                                                                                                                                                                                                                                                                                                                                                                                             | Pinned by                                                                                                                                                                                                                               |
| --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| BLOCKER 1 | `scripts/upgrade.sh` forwards `HOOKS_DAEMON_UPGRADE_PREVIOUS_VERSION`, `HOOKS_DAEMON_OLD_DEFAULT_CONFIG`/`_PID` and `HOOKS_DAEMON_OLD_DEFAULT_SETTINGS` through `env -i`                                                                                                                                                                                                                                        | `TestLayer1HandsItsBaselinesToLayer2` (real Layer 1; a stub Layer 2 reads each variable and the preserved files' contents, and checks the baseline owner is alive)                                                                      |
| MAJOR 1   | The guard treats every spelling as steering: a non-read mention of a steering name, a `declare`/`typeset`/`local` flag with `x`, an `export` with a flag or computed operand, and a computed assignment name. On a command already recognised as the upgrade, `set -a`/`-o allexport`, `eval` and sourcing another file count too                                                                               | `TestEverySpellingOfSteeringIsSteering` (all five reviewer spellings, plus computed-name variants) and allow cases (dotenv `set -a`, `eval "$(ssh-agent)"`, a plain run)                                                                |
| MAJOR 2   | Layer 2 sets the trusted `PATH` again after its last library source. venv.sh reaches uv through `_venv_uv` (PATH first, then `$HOME/.local/bin/uv` by name). The source-time prepend stays for install_version.sh and setup_worktree.sh, which run a bare `uv`                                                                                                                                                  | `TestLayer2PathAfterEveryLibrarySource` (the real Layer 2 head through its last source, with a planted `~/.local/bin`), `TestUvIsResolvedByName`                                                                                        |
| MAJOR 3   | The wholesale drop of the global git config is gone. Layer 1 unsets `GIT_CONFIG_COUNT`/`KEY_*`/`VALUE_*`/`PARAMETERS`, requires exactly one origin URL, and refuses a fetch that config rewrites (any scope, or an include) to a different repository (`_remote_identity`). The guard denies writes into `.claude/hooks-daemon/.git/`, which closes the local-config redirect route left open since review-3 m2 | `TestLayer1FetchesOnlyFromOrigin` (safe.directory clone via `GIT_TEST_ASSUME_DIFFERENT_OWNER`; global, include, clone-local and env routes; a same-repository rewrite passes), `TestRemoteIdentity`, `TestDaemonCloneGitMetadataWrites` |
| m1        | The UV index/find-links/config/python names, CA bundles, proxies and `HOOKS_DAEMON_OLD_DEFAULT_*` join `_UPGRADE_STEERING_VARS`. `PIP_*` is no longer forwarded                                                                                                                                                                                                                                                 | `TestInstallerSteeringVariables`, `TestLayer2EnvAllowlistIsDecidedPerSetting`                                                                                                                                                           |
| m2        | The allowlist is named per group in upgrade.sh, each group with its reason. Kept: venv build/lock tuning, `CI`, `VERBOSE`, `HOOKS_DAEMON_VENV_PATH`, plus `HOSTNAME`, `XDG_RUNTIME_DIR`, `CLAUDE_HOOKS_*`, `HOOKS_DAEMON_MODE`/`EVENTS_DIR`/`LOG_LEVEL`/validation (the daemon Layer 2 restarts listens where the hooks look only with these). Dropped with reasons: internal pass state, test seams, `PIP_*`   | `TestLayer2EnvAllowlistIsDecidedPerSetting` (23 kept, 7 dropped)                                                                                                                                                                        |
| m3        | The `_gate_dir_is_trusted` test drives a stubbed `stat` (GNU `-c` and BSD `-f`) by directory name under any uid. It no longer returns early off root                                                                                                                                                                                                                                                            | Proven RED by removing the owner check in a `git archive` copy                                                                                                                                                                          |
| m4        | The seven callouts are now one (`180-upgrades-stop-before-deploying-...`, renumbered into this dispatch's range at merge). It says the guard is the only barrier on a direct Layer 2 call                                                                                                                                                                                                                       | `test_pending_release_notes_holding_area.py`                                                                                                                                                                                            |
| n1        | Header: "The gate does not know which version this project last installed, so every upgrade guide up to vX is listed"                                                                                                                                                                                                                                                                                           | `test_the_header_says_why_every_guide_is_listed`                                                                                                                                                                                        |
| n2        | "(from the none)" is now "(no venv stamp names it, and .claude/HOOKS-DAEMON.md carries no release)"                                                                                                                                                                                                                                                                                                             | `test_no_source_is_said_in_words`                                                                                                                                                                                                       |

## Found and fixed along the way

- `tests/acceptance/test_guarded_branch_install.py` had failed since review 2
  (aea39196). It recorded the target itself as the installed release, which
  that gate rule rightly refers to the owner. It now records the release
  before the branch.
- The skill's `upgrade.md` cited `CLAUDE/LLM-UPDATE.md` unqualified in a file
  deployed to clients. The citation now names the daemon clone's copy, and the
  deployed copy is redeployed.
- The quiet `install_package_editable` branch discarded uv's output. It now
  prints that output on failure. The error-hiding exclusion it needed is
  removed.
- The guard's script reader returned None from an `except` with a debug log.
  It now raises; the caller logs at WARNING and returns an explicit "cannot
  tell" verdict. A relative script with no `cwd` is "cannot tell" too, which
  closes the gap its docstring had called "pre-existing".
- After the merge, `check_daemon_dir_cd_in_docs.py` (this branch) now meets
  main's 00466 N26 walker contract (`walk_files`, and it fails on an empty or
  missing root). Main's note 059 carries the checker's `BLOCKED-EXAMPLE`
  marker. Main's post-upgrade task 05 had `Severity: notification`, outside
  the enforced schema; it is now `optional`. A test URL no longer names
  another GitHub org.

## Owner decision (written into PLAN.md, decision (e))

Upgrading through a `url.<mirror>.insteadOf <github-url>` rewrite is now
refused, with the rewrite named and the remedy printed (point origin at the
mirror). That is fail-closed option A, and it is implemented. The PLAN lists
B (warn and allow) and C (a trusted-mirror list) for the owner.

## Merge

- `git merge --no-ff main` (`22b3c021a`).
- Ledger resolved with `merge_ledger_table.py`, then the N1 row touched so
  the table re-aligned. N37 keeps this branch's Remedied status.
- Generated docs taken from main, then `regenerate-docs`.
- LLM-UPDATE keeps the project-root hook path plus main's `synthetic_source`.
- RELEASING keeps pre-upgrade-tasks plus main's `NNN` callouts.
- v3.67.0 config-changes and truth-changes keep both sides' entries. The
  guard's entry now describes this round's names and routes.
- No `src/` conflicts.

## Verification

- `tests/unit`: 25136 passed and 2 failed on the first post-merge run; both
  were fixed (`b5d55e820`). The rerun result is below.
- `tests/integration`: 4928 passed, 7 skipped, 4 failed; all four were fixed
  (`4cd9bb82a`) and rerun green, targeted.
- `tests/daemon`: 190 passed.
- `tests/acceptance/test_guarded_branch_install.py`: passed.
- ruff, black, mypy `--strict` and pyright are clean on every changed Python
  file.
- `audit_error_hiding.py` is clean.
- The reviewer's `probe_376r4_guard.py`, rerun: every reproduced spelling is
  DENY.
- Daemon restarted and RUNNING before each commit that touched `src/`.

`tests/unit` rerun at `4cd9bb82a` (after every fix): 25141 passed, 0 failed.

## Files both this branch and `worktree-upgrade-scripts` touch

This matters for the owner's "the upgrade must never break" rule. Measured
as `main...` on both branches: `scripts/upgrade.sh`,
`scripts/upgrade_version.sh`, `scripts/install/venv.sh`,
`scripts/lib/resolve_venv.sh`, both copies of the skill's `upgrade.sh`,
`upgrade.md` and `SKILL.md`, `CLAUDE/LLM-UPDATE.md`,
`scripts/qa/error_hiding_exclusions.json`, the handler/priority/rule-id
constants, `daemon/cli.py`, `init_config.py`, `.claude/hooks-daemon.yaml*`,
`CLAUDE/UPGRADES/README.md`, `upgrade-template/README.md`, `RELEASING.md`,
the 00466 ledger, and the tests `test_guarded_branch_install.py`,
`test_upgrade_recovery_hints.py`,
`test_upgrade_runs_the_target_versions_steps.py`,
`test_venv_sh_sync_is_frozen.py`, `test_claude_md_guidance_coverage.py` and
`test_blocking_handler_evasion.py`.

The real collision is venv.sh. Both branches fix the MAJOR 2 class
differently:

- **This branch**: `_venv_uv` falls back to `$HOME/.local/bin/uv` by name,
  and Layer 2 re-pins `PATH`.
- **`worktree-upgrade-scripts`**: resolves `UV_BIN` once at source time, never
  consults `~/.local/bin`, and rewrites the same frozen-sync test's source
  scan and PATH-ordering comment.

Whichever branch lands second must pick one design, not merge both.

## Tooling defects seen (not this plan's code)

- `secret_file_guard` denied three routine calls:
  - `TooManyToEnumerateError` on a Bash `grep ... install/*.sh` and on
    commands naming the `untracked/venv-*` glob;
  - `TimeoutError` on a long `git mv`/`git rm` chain;
  - a false positive: `*.vault-password` matched on an Edit whose text ran
    from an apostrophe in a comment to a later quote.
- The first `hooks-daemon restart` after a commit printed "Daemon failed to
  start (no PID file created)" while status showed RUNNING (a start race); a
  second restart was clean.
