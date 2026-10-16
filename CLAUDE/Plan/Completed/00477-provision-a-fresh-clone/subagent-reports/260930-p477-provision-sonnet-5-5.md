# Plan 00477 Phases 1-2: provision a fresh clone (sonnet-5-5)

Branch `worktree-p477-provision`. Not merged.

## Config key

`daemon.expected_version`, strictly `X.Y.Z` (pydantic pattern on `DaemonConfig`). The top-level `version: "2.0"` (config schema) is untouched.

## What was built

- `install/expected_version.py`: text-level writer (keeps comments and layout), run as `python -m ...expected_version --project-root DIR [--version X.Y.Z]`. `scripts/install/expected_version.sh` wraps it; `install_version.sh` and `upgrade_version.sh` (both generate-docs spots) call it, non-fatal.
- `init.sh`: `_config_expected_version_raw` (awk, no python) and `_resolve_expected_version`. Order: config key, then `_tracked_deployed_version` (the header). Sets `_HOOKS_DAEMON_EXPECTED_VERSION` (`unknown` when unresolved) and `_SOURCE` (`config | tracked-doc | config-invalid`). A present but invalid key is reported as invalid, not overridden by the header.
- `provision.sh` (repo root, deployed to `.claude/provision.sh`, symlinked in this repo like `init.sh`), `deploy_provision_script` in `hooks_deploy.sh`, a `CLIENT_OWNED_ASSETS` entry and a row in the LLM-INSTALL boundary table. Flow: resolve, refuse if a clone or foreign content is present, `git init` + `fetch --depth 1 origin refs/tags/vX.Y.Z` + detached checkout into the existing `untracked/` skeleton, compare the clone's `version.py` with the requested version (abort and clean up on mismatch), `venv_bootstrap.sh repair` (foreground, existing lock), then `start_daemon` from `init.sh`.
- `/hooks-daemon provision` routes to the tracked script (`SKILL.md`, `provision.md`, both src and the dogfood copy).
- Release note 187 and a `daemon.expected_version` entry in the UNRELEASED config-changes manifest.

## Decisions worth knowing

- **init + fetch, not `git clone`.** Sourcing `init.sh` does `mkdir -p .claude/hooks-daemon/untracked` on every source, so the directory is never empty and `git clone` refuses it. The result is the same as a depth-1 clone of the tag (detached HEAD, `origin` set, so `upgrade` works).
- **Test seam.** The script never reads its URL from the environment. Tests point git at a local bare repo with `GIT_CONFIG_GLOBAL` and `url.<local>.insteadOf <trusted URL>`. A test asserts the script's URL equals `install.sh`'s `DAEMON_REPO` and that `DAEMON_REPO`, `DAEMON_BRANCH` and `HOOKS_DAEMON_CLONE_URL` in the environment are ignored.
- **Start through `start_daemon`, not `ensure_daemon`.** Under `CI=true` `ensure_daemon` passes through and returns 0 when the daemon is not installed, which would let provision claim success. `start_daemon`'s deadline (`_HOOKS_DAEMON_START_DEADLINE=15`, counted from source time) is reset to now+60 after the build.

## Tests (TDD; red quoted in the session)

- `tests/unit/install/test_expected_version.py` (writer, `main`, model): red was `ModuleNotFoundError`, now 25 passing.
- `tests/integration/test_init_sh_expected_version.py` (resolver): 15 passing.
- `tests/integration/test_provision_sh.py` (22 tests): red was the missing `provision.sh`. Covers exact tag not `main`, `git status --porcelain` empty before and after, venv built once, daemon started once, the next hook finds it running, wording ("No session restart is needed"; the no-hooks-in-settings variant says otherwise), header fallback, env ignored, refusals (unknown, malformed x6, clone present -> `upgrade`, no venv -> `repair`, missing tag, tag naming another version, daemon's own repo, failed build keeps the clone and names `repair`).
- `tests/integration/test_provision_install_wiring.py`: the install-lib function, both scripts call it, `deploy_provision_script` copy/refresh/self-install.
- Existing deploy fixtures (`test_hooks_deploy_permissions.py`, `test_hooks_deploy_relay_guard.py`) now seed a `provision.sh`, as they already do for `init.sh`.
- Also passing: `test_install_sh_end_to_end.py` and `test_guarded_branch_install.py` (real install, upgrade, through-a-link), client-owned asset lint, config tests, venv self-heal tests. 351 + 657 tests, 0 failed.

## QA

`llm_qa.py changed --base main --allow-unmapped`: 27 of 28 checks passed. The one red is `changed_tests`, which reported 0 passed, 0 failed, 0 skipped over 50 selected files (it ran nothing; cause not established, likely the runner declining the selection). Its tests were run by path instead, as listed above. The first run also flagged `canonical_callers` with 0 violations: its helper needs `untracked/scratch/`, which this worktree lacked; creating the directory made it pass.

## Unverified, and for the owner

- No real (non-stub) venv build or daemon start was run: the venv is built by a stub `uv`, and the stand-in daemon binds the socket. "The daemon answers on its socket after provision" is therefore proven at the `init.sh` level (`is_daemon_running` plus a bound socket), not against a real daemon process.
- A branch install records its base `__version__`; provision would then look for that tag. Branch installs are not specially handled.
- Bug in existing code, not fixed here: `_resolve_python_cmd` in `init.sh` ends with `local rv=$?` after an `if` with no `else`, so it returns 0 after a failed resolve and leaves `PYTHON_CMD` empty. `provision.sh` judges `PYTHON_CMD` instead. `validate_venv` is unaffected by luck.
- `SKILL.md`'s "Install Daemon ... on a fresh clone" wording and `LLM-INSTALL.md` routing are left for Phase 4 (Task 4.1). The UNRELEASED post-upgrade task (Task 4.2) is also left.
- The provisioning tag must ship `scripts/venv_bootstrap.sh` (Plan 00456); an older tag is refused and cleaned up, with a message.
