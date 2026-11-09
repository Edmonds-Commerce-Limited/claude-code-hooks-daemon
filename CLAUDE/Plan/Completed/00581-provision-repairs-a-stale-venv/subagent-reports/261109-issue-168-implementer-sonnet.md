# Issue 168 implementer report (Plan 00581)

## Change

- `provision.sh`: the equal-version branch now calls `_provision_equal_version`. It checks the venv with
  `venv_lock_hash_matches` (sourced from the clone's `scripts/install/venv.sh` in a child `bash -c`).
  - Proven match: "nothing to do", exit 0 (unchanged).
  - Not a proven match, foreground: `bash venv_bootstrap.sh repair`, then "The venv was rebuilt ...", exit 0. A failed
    repair fails with `PROVISION FAILED` naming `hooks-daemon repair`.
  - Not a proven match, `--background`: no rebuild; prints that the venv is stale and names
    `hooks-daemon repair`; exit 0 (as the other non-fatal background outcomes, e.g. "no daemon running").
- Unreadable lock hash (bad metadata, missing venv.sh, missing helper): treated as STALE (rebuilt in foreground,
  reported in background), never as a match.
- `.claude/provision.sh` is a symlink to root `provision.sh` in this repo, so they cannot differ. Client copies are
  made by `deploy_provision_script` in `scripts/install/hooks_deploy.sh` (plain copy); nothing to change there.
- Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/017-provision-repairs-a-stale-venv.md`.
- Not moved: version-mismatch sync, fresh provisioning, background-sync scope.

## Tests (tests/integration/test_provision_sh.py, class TestAnExistingCloneAtTheExpectedVersionWithAStaleVenv)

RED before the fix (first failure, `-x`; matching-venv test already passed):

```
AssertionError: assert 'rebuilt' in 'Provisioning the hooks daemon v3.61.0 ... The daemon clone is already at
v3.61.0, the expected version: nothing to do.\n'
```

GREEN: `test_provision_sh.py` + `test_background_sync.py` 97 passed; after black reformat the 5 equal-version tests
pass again.

## QA

`llm_qa.py changed`: 39 of 42 passed; `format` failed only because black auto-fixed the new test file mid-run (this
made `project_handlers` and `changed_tests` NOT MEANINGFUL; their counts were 300 and 427 passed, 0 failed). A re-run
of `llm_qa.py format` passed (0 files need reformatting). shell_check, lint, type_check, pyright: clean.

## Caveat

A foreground repair rebuilds the venv; it does not restart a running daemon, so the old process keeps serving until
its next restart.
