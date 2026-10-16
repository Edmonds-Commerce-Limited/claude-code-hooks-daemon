# Plan 00477 Phase 5 implementer: Tasks 5.2, 5.4 and 4.2

Worktree: `untracked/worktrees/worktree-p477-background-sync`. Commits, in order:

- `98c7ee990`: the first version, which launched the sync from Python.
- `55642216d`: error_hiding and black fixes.
- `7bcb35cf2`: the launch moved into shell (the coordinator's suppression-free route).
- `6bc2f5b45`: signal_targets, magic_values and the changed-tests map.
- `3d36de429`: Task 5.2 tick and the report.
- `cd8b8e315`: the target staged and trial-built beside the live daemon, and the switch only at restart (the coordinator's venv-swap follow-up).
- `840f5addc`: report update for `cd8b8e315`.
- `79ca131e4`: coordinator review round 2. The target is built in a stage that is a clone of its own, its venv rebound to the live path, and swapped in by rename; the old clone is kept until the new daemon answers; an interrupted switch is undone by the next run. This replaces the in-place switch of `cd8b8e315` (section "Review round 2" below).
- This report's update is in the commit after that.

## Assumptions (for the coordinator to have ruled on)

1. **Only an UPGRADE is synced in the background.** A downgrade keeps the manual route. The Task 5.1 notice asks a human to confirm that a downgrade is intended, because a commit made from an older checkout looks the same as a deliberate downgrade. `provision.sh --background` refuses a downgrade itself.
2. **The background sync never provisions a fresh checkout.** The owner ruled that fresh provisioning is deliberate (Overview, Non-Goals). `--background` refuses when no clone exists.
3. **"Once per target version" means once, not once per success.** After a failure the sync is not retried in the background. Every session start reports the failure and names the state file to delete for a retry, and `bash .claude/provision.sh` to run by hand.
4. **A target whose pre-deploy gate wants the reading list confirmed is reported, not confirmed.** Task 5.3 keeps that confirmation, and a detached process has nobody to read. It records `needs-reading`.
5. **Gitignored build caches outside `untracked/` are not carried to the new clone** (review round 2). By the daemon repository's own `.gitignore` they are caches (`__pycache__`, `.mypy_cache`, `*.egg-info` and the like). They stay with the old clone and are removed with it. Everything under `untracked/` is carried.
6. **An interrupted swap is always rolled back, never forward** (review round 2). The run that would have confirmed the new daemon is gone, so nothing proves it. A background sync so undone is recorded as failed and not retried in the background (Assumption 3).
7. **The sync waits up to 30 s for a running daemon before it touches the clone.** If none is running by then, it claims nothing and changes nothing, and a later session start retries. This keeps the guarantee that the old daemon serves until the new one is ready, and it prevents the sync from moving a clone that the same hook's `ensure_daemon` is starting from.

## The trigger point: the session-start forwarder, in shell

The first version had `version_check` start the sync with `subprocess.Popen`, which drew bandit B404/B603. The coordinator asked for a route needing no new suppression. That route exists and is implemented: Python starts no process at all.

- **Where:** the tracked `.claude/hooks/session-start` forwarder, directly after `SCRIPT_DIR=`. It starts `setsid bash "$SCRIPT_DIR/../provision.sh" --background` (`nohup` where there is no `setsid`) with stdin, stdout and stderr redirected, in the background, and goes on. The hook never waits on it.
- **Relay mode:** the relay guard is generated directly above `source "$SCRIPT_DIR/../init.sh"`. That is why `init.sh` itself was not a usable trigger: with the relay on, SessionStart never sources it. The launch sits above the guard, so it runs with the relay on or off. `test_the_start_comes_before_the_relay_hot_path` builds the relay-enabled forwarder and checks the order. The relay's `--no-relay` fallback re-enters the forwarder, so the launch is skipped on that pass.
- **Cost:** one detached bash per session start. `provision.sh --background` decides for itself whether there is anything to do. In the usual case the clone already matches and it exits ("nothing to do"). In the daemon's own repository it exits before sourcing `init.sh`.
- **Better than the Python route:** the forwarder and `provision.sh` are tracked files, so the commit that moved `daemon.expected_version` brings them in. The pull that changes the version is therefore enough, including the first move onto this release.
- **What Python does now:** `version_check` only READS the state the sync wrote (`install/background_sync.py`: paths and `read_sync_record`; no subprocess import, which a test asserts). With no state yet it says the sync was started this session. Otherwise it reports under way, failed, stopped for reading, or "recorded success yet still old".

The coordinator's guarantees, one by one:

| Guarantee                                        | How                                                                                                                                                                                                                                                                | Shown by                                                                                                                                                                                                             |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Never inside a hook's time budget                | Detached `setsid ... &` with every fd redirected                                                                                                                                                                                                                   | `test_a_pulled_upgrade_is_synced_after_the_hook_has_answered` (venv build slowed to 5 s; the hook returns before the state is `synced`)                                                                              |
| The old daemon serves until the new one is ready | The sync waits for a running daemon (Assumption 7); the target is built in a stage that writes nothing else of the live clone; it is swapped in by rename only after the old daemon stops, and the old clone is kept until the new daemon answers (review round 2) | `test_a_sync_waits_for_a_running_daemon_and_otherwise_claims_nothing`; `TestTheSwitchIsADirectorySwap`; `TestAnInterruptedSwitchIsRecoveredByTheNextRun`; `test_a_sync_failure_keeps_the_old_daemon_and_records_why` |
| Failure is loud                                  | State `failed` or `needs-reading` with the reason; `version_check` shows it at every session start (`systemMessage` plus context) with the log, the manual command and the state file to delete                                                                    | `TestTheBackgroundSync::test_a_refused_clone_is_recorded_as_a_failure` and siblings; `TestAPulledUpgradeIsReportedAsSyncingInTheBackground`                                                                          |
| One sync at a time                               | `mkdir` lock with the holder's pid, taken over when that pid is dead; a per-target state file as the once-only marker                                                                                                                                              | `test_a_sync_already_running_is_not_joined`, `test_a_lock_whose_holder_is_gone_is_taken_over`, `test_a_target_already_attempted_is_never_attempted_again`                                                            |
| The daemon's own repository never syncs          | `provision.sh` refuses before sourcing `init.sh`; `version_check` reports no drift in self-install mode                                                                                                                                                            | `test_the_daemons_own_repository_never_syncs`, `test_the_daemons_own_repository_never_reports_drift`                                                                                                                 |

## Review round 2: a staged build swapped in by rename (`79ca131e4`)

The coordinator asked for: the target built in a staging location beside the live clone with its own venv; the live clone never touched while the old daemon serves; then stop, swap the directories by rename, keep the old copy until the new daemon answers, swap back on failure; an interrupted swap recovered by the next run; the venv's embedded paths surviving the rename, shown with evidence; and a test that the live clone is byte-identical during the staged build. All of it is implemented and tested. The previous round's claim that a venv "cannot be moved into place" was wrong: it can, once it is rebound (below).

**Where the stage is.** `.claude/hooks-daemon/untracked/sync-stage`. It has to be gitignored and on the same filesystem as the live clone for a rename. The only gitignored place in a client project is under `.claude/hooks-daemon/` (root `.gitignore` names `.claude/hooks-daemon/` and nothing else), so a sibling such as `.claude/hooks-daemon.next` would show in the project's `git status` for the whole build. A sibling exists only for the instant between two renames (below).

**Nothing of the live clone is written during the build.** The stage is NOT a `git worktree` of the live clone any more: that wrote `.git/worktrees/` and the fetched tag into the live `.git`. It is `git init` + `remote add origin <fixed URL>` + `fetch --depth 1 origin refs/tags/vX:refs/tags/vX` + checkout, exactly as fresh provisioning makes a clone. The tag's `version.py` is checked before checkout. The target's gate runs from it, and its venv is built in it by its own `scripts/venv_bootstrap.sh repair <stage>`.

**How the venv survives the rename.** A venv is bound to its build path in two ways, both of which I measured on a real `uv` 0.13.1 build of this branch's daemon:

1. Its NAME: `venv-<slug of the daemon dir>-pyMM-<hex>`. The stage's slug differs from the live one's, and the resolver refuses a slug that is not its own.
2. TEXT files that spell the path. On the real build, exactly 11 non-bytecode files: the editable `.pth` (`<stage>/src`), `direct_url.json`, the three console scripts' shebangs (`mdformat`, `jsonschema`, `markdown-it`), five activate scripts, and `.daemon-metadata.json` (python_path, fingerprint). `bin/python` is a link to `/usr/bin/python3.11`, outside both paths; `pyvenv.cfg` names only `/usr/bin`. 75 `.pyc` files also embed the path, but importlib does not trust a cached code object's path: it rewrites `co_filename` to the path the module was loaded from (`_imp._fix_co_filename`), shown below.

So `_provision_rebind_stage_venv` (before the old daemon is stopped, in the stage only): computes the stage and live fingerprints with the target's own `python_fingerprint.sh`, checks the built venv carries the stage one, rewrites the stage path (logical and physical spellings, full venv path first) and the fingerprint to the live ones in every text file (`grep -rlIF`, byte-exact, mode kept), renames the venv for the live slug, and fails unless `grep` then finds the stage path in no text file. Renaming the whole stage onto the live path then makes every path it names true.

Evidence (`untracked/scratch/exp-venv/rebind.bash`, run against a real `uv`-built venv, sourcing provision.sh's own three functions, then doing the swap's two renames):

```
The venv for v-experiment was rebound to .../exp-venv/proj/.claude/hooks-daemon (11 files named the stage).
== venv now: .../proj/.claude/hooks-daemon/untracked/venv-workspace_untracked_worktrees_worktr-01e8-py311-2a519198
== .pth:  .../proj/.claude/hooks-daemon/src
== text files naming the stage path (expect none): (none)
== import from the live path:
.../proj/.claude/hooks-daemon/src/claude_code_hooks_daemon/__init__.py
.../proj/.claude/hooks-daemon/src/claude_code_hooks_daemon/daemon/cli.py     <- co_filename, though the .pyc was written in the stage
== console script runs: mdformat 1.0.0 (mdformat-gfm 1.0.0)
== the resolver finds it for the live path: .../hooks-daemon/untracked/venv-...-01e8-py311-2a519198/bin/python
== uv sees nothing to change (dry run): Checked 19 packages ... Would make no changes
```

The stage venv was named `...-344f-...` before, the live one `...-01e8-...`.

**The switch** (`_provision_switch`), only after the stage is built and rebound:

1. The switch marker (provision's pid) is written into the live `untracked/` and the stage's, and an empty manifest `.sync-carried` into the stage. The manifest records that the switch has begun.
2. The old daemon is stopped.
3. The stage's `untracked/` keeps only the rebound venv. Every entry of the live `untracked/` (the daemon's state, logs, other views' venvs, the background-sync record and its open log) is moved into it, each name appended to the manifest first. The exceptions are the stage, the marker and the old venv, which stays with the old clone.
4. Three renames: live -> `.claude/hooks-daemon.sync-previous` (the sibling, for one instant); `<aside>/untracked/sync-stage` -> live; aside -> `<live>/untracked/sync-previous`.
5. `bin/hooks-daemon restart` (which returns 0 only once the started daemon answers on its socket, `cli._await_started_daemon`), then `is_daemon_running` on its PID file.
6. Marker and manifest removed; the old clone renamed to `sync-previous.discard` and removed. The rename comes first so that a removal cut short is never taken for an old clone to put back.

Two details: `_provision_rename` refuses an occupied destination, and if a directory appears there first (a hook's `mkdir -p untracked` in the gap) it undoes mv's move-into and fails. `_provision_rename_onto_live` clears the live path first only when it holds nothing but init.sh's `untracked/` skeleton (no checkout, no source, no venv).

**Undo, on failure and after a kill** (`_provision_recover_switch`, run by every provision before anything else, and by the sync's own abort). It tells the state apart by what exists:

| What exists                                             | Killed                      | Undo                                                                             |
| ------------------------------------------------------- | --------------------------- | -------------------------------------------------------------------------------- |
| aside, and no checkout at the live path (or a skeleton) | between renames 1 and 2     | aside -> live, then as the last row                                              |
| aside, and a checkout at the live path                  | between renames 2 and 3     | aside -> `untracked/sync-previous`, then as the next row                         |
| `untracked/sync-previous`                               | after the swap, unconfirmed | stop the daemon running from it; reverse the three renames; then as the last row |
| the stage's manifest                                    | after the stop, not swapped | move every manifest entry back; remove the stage                                 |
| `sync-previous.discard`                                 | while removing the old one  | remove it                                                                        |

Then: the marker is removed, a background record left `running` by a dead pid becomes `failed` ("killed during the switch; the previous version was put back"), the old daemon is restarted, and it prints `RECOVERED: ... v<old> is back in place`. An unconfirmed swap is always rolled back, never forward: the run that would have confirmed it is gone. If any marker names a LIVE process other than itself, provision does not recover; it says another provision (pid N) is switching and changes nothing (exit 0 in the background).

**Not carried:** gitignored files of the old clone outside `untracked/` (`__pycache__` and other caches by the daemon repository's `.gitignore`). The preflight already refuses anything else outside `untracked/`. Assumption 5 above.

**One fix found on the way.** init.sh's `is_daemon_running` proves at most one pid per process with the daemon's helper (`_HOOKS_DAEMON_HELPER_KEY` cache), and answers "not proven" for any other. A sync asks about the old daemon and then the new one, so the second answer was always "not running". provision now asks through `_provision_daemon_running`, a subshell that starts with the cache empty.

**Tests** (`tests/integration/test_provision_sh.py`; red first, 12 failed and 1 passed in `untracked/scratch/red-directory-swap.txt`):

- `TestTheSwitchIsADirectorySwap::test_the_live_clone_is_byte_identical_while_the_target_is_built`: a uv wrapper snapshots every path of the live clone (sha256 of each file, link targets) during the staged build, and a CLI hook snapshots it again at the stop. The only exclusions are what the sync itself writes: `untracked/sync-stage`, `untracked/background-sync` and the marker. Both equal the snapshot taken before the run. Every build's target is in the stage, and the old daemon was up during it. Red: the old worktree stage changed `.git`.
- `test_the_staged_venv_is_moved_into_place_bound_to_the_live_path`: the stub uv now writes the files a real uv embeds the path in (`UV_EMBEDDED_PATH_FILES`). Afterwards the venv is `venv-{python_venv_fingerprint(live)}`, none of those files names the stage, the `.pth` is `<live>/src`, the shebang names the live venv, the metadata names the live interpreter and fingerprint, the resolver resolves, and there was exactly one build (no in-place build).
- `test_the_previous_copy_is_kept_until_the_new_daemon_answers`: at the restart, `untracked/sync-previous` holds the old `version.py`; afterwards nothing of the switch is left.
- `test_the_daemons_untracked_state_is_carried_across`: a state file and another view's venv come through byte for byte.
- `test_a_target_venv_that_cannot_be_built_never_stops_the_old_daemon`: now also byte-identical.
- `test_a_new_daemon_that_does_not_start_is_swapped_back`: the restart of the new version fails. The live clone is byte-identical to before, the old daemon is started again, and nothing of the switch is left.
- `TestAnInterruptedSwitchIsRecoveredByTheNextRun::test_the_previous_version_is_put_back[4 shapes]`: provision is `kill -9`ed at the restart (the "swapped-unconfirmed" state). The other three shapes are made from it by undoing one rename at a time, which is exactly what a kill between those renames leaves. The gap shape also gets a hook's skeleton at the live path. The next run prints `RECOVERED`, and the live clone is byte-identical to before.
- `test_an_interrupted_sync_is_recovered_then_completed`, `test_an_interrupted_background_sync_is_recorded_and_not_retried` (state `failed`, "put back"), `test_a_switch_another_live_process_is_making_is_left_alone`.
- `tests/unit/install/test_background_sync.py::test_reads_the_status_provision_recorded[running-running]` assumed pid 42 was alive; it is not in this container, so the reader correctly turned "running" into "failed". It now uses the test's own pid.

Result: `tests/integration/test_provision_sh.py` and `tests/unit/install/test_background_sync.py` 85 passed.

## Review round 3: the relocated venv is checked, and rebuilt when it fails

The rebind is proven on today's uv only. A later uv that writes the build path into a binary, or into a file the rewrite misses, would otherwise go unnoticed until the new daemon failed to start. So the venv is now checked after the swap and before that start (`_provision_venv_healthy`, in `_provision_switch`):

1. **init.sh's own pre-start check, reused.** `validate_venv` is what `start_daemon` runs before it starts a daemon: the canonical resolver (`_resolve_python_cmd` -> `resolve_venv.sh`), then `python -c "import claude_code_hooks_daemon"`. It runs in a subshell with `PYTHON_CMD` cleared, so the resolver runs afresh against the swapped-in clone.
2. **The resolver/fingerprint check.** The interpreter the resolver chose must be the rebound venv, `<live>/untracked/venv-<live fingerprint>/bin/python`, and not the old venv or another view's.
3. **The package loads from the live `src`.** The package's `__file__`, resolved physically, must lie under `<live>/src`.

**If the check fails,** the venv is removed and rebuilt in place by the clone's own `scripts/venv_bootstrap.sh repair <live>`, with the daemon down. The old venv is safe in `untracked/sync-previous`. The rebuilt venv must pass the same check. The outcome records the fallback and its reason. The background record becomes `synced` with "...; the relocated venv failed its check (<reason>) and was rebuilt in place", and a manual run prints it as a `Note:` under `SYNCED`.

**If the rebuild fails, or the rebuilt venv fails the check,** the sync aborts through the existing rollback: the swap is undone and the old daemon is started again. The failure reason names both the check's reason and the failed rebuild, and a background run records it as `failed`.

Tests (`TestARelocatedVenvThatFailsItsCheckIsRebuilt`). The red run (`untracked/scratch/red-r3.txt`) had 2 failures: the sync ended in "the daemon did not start" and no rebuild was attempted.

- **Setup.** The stub uv's new `binary_pth` writes the editable `.pth` with a NUL byte. To `grep -I` it is binary, so the rebind leaves it naming the stage. This is exactly the case of "a path written where a text rewrite cannot see it".
- **Stub interpreter.** The stub `bin/python` now reads `.pth` files as Python does for a `-c` that imports the package. A `.pth` that names a directory that does not exist makes the import fail, and `__file__` is under the directory the `.pth` names. A `-c` that does not touch the package is unaffected, as with real Python.
- `test_a_path_the_rebind_cannot_see_is_rebuilt_and_the_sync_completes` (background). It ends on the new version with one in-place build. The rebuilt `.pth` names `<live>/src`. The record is `synced` and says "rebuilt" and "Cannot import". The new daemon is started once.
- `test_a_rebuild_that_fails_too_ends_on_the_old_version` (background, with every in-place build failing). It ends on the old version. The live clone is byte-identical to before. The old daemon is started again. The record is `failed` and says "rebuilding" and "Cannot import".
- Targeted QA on `20183d293` (`FULL_QA_LOCK_WAIT_SECONDS=3600 changed --allow-unmapped`): **QA: 37/40 PASSED, 1/40 FAILED, 2/40 NOT MEANINGFUL, exit 1**. The one failure is again plan_qa's ADVISE `journal-freshness` for Plan 00471. changed_tests: 4008 passed, 0 failed.
- All nine test files built on the sandbox, plus the background_sync unit tests: 219 passed. The session-start end-to-end test now builds with `embed_build_paths` so its venv carries the `.pth` the check reads.

## Superseded: the in-place switch (`cd8b8e315`)

Everything in this section was replaced by review round 2, above. It is kept for the record of the previous decision.

The coordinator's follow-up: 5.2a checked the tag out in place and rebuilt the venv in place while the old daemon was still running. That broke "the old daemon keeps serving until the new one is ready". It is fixed: nothing the running daemon imports from changes until that daemon has been stopped.

**What can and cannot be built beside the live daemon.** Venvs here are not keyed on the daemon version. The name is `venv-<slug>-py{MM}-{hex}`, where the slug comes from the daemon directory's path and the hex from the interpreter. `uv sync --project <daemon_dir>` installs the package EDITABLE, pointing at `<daemon_dir>/src`, and a venv's interpreter links and `.pth` are absolute. So a venv is bound to the path it was built for. The hooks always look for the daemon at `.claude/hooks-daemon`, which the live daemon occupies. A venv built elsewhere therefore cannot be renamed into place, and a second venv for the same path and interpreter would take the live one's name. A true "flip a pointer at restart" needs a layout change, such as versioned clone directories behind a symlink. That would change install, upgrade and every path resolver, so it is the owner's call and I did not make it.

**What I implemented instead, the strongest version the current layout allows.** The sync now runs in two phases.

1. **Beside the live daemon, which nothing here touches:**
   - The tag is fetched.
   - The tag is checked out into its OWN git worktree, `.claude/hooks-daemon/untracked/sync-stage`. This answers the shared-checkout question: the live checkout does not move in this phase.
   - The tag's `version.py` is checked.
   - The target's pre-deploy gate runs from the stage.
   - The target's venv is trial-built in the stage by the TARGET's own `scripts/venv_bootstrap.sh`. This proves the target builds on this machine, with these interpreters and this network, and it fills uv's cache.
   - Any failure in this phase removes the stage and stops. It never stops or changes the old daemon, and the message says so ("never stopped").
2. **The switch, at restart:**
   - A marker holding provision's pid is written (`untracked/.provision-switching`).
   - The old daemon is stopped through the clone's `bin/hooks-daemon stop`.
   - Only then does the clone check out the tag and its venv get rebuilt in place, by the clone's own build path, from the warm cache.
   - The marker is removed and the new daemon is started.
   - A failure in this phase restores the previous commit and its venv and starts the old daemon again.
3. **No hook starts a daemon mid-switch:** `init.sh`'s `start_daemon` asks `_daemon_switch_in_progress`, only on the start path, so a running daemon pays nothing. While the marker names a live process, the hook starts nothing and answers as for a daemon still starting ("the daemon is starting; retry"; fail-open, or deny where `ci_enabled` already denies). A marker left by a killed sync, with a dead pid, does not block.

**What is left:** the switch window. Between stopping the old daemon and starting the new one, the in-place venv build runs, from the warm cache, so without network. Hooks in that window get the "starting; retry" answer, not a daemon. That window is the restart itself, made as short as the in-place build allows. Removing it entirely needs the versioned-layout change above.

Tests (red first, then green):

- `TestTheSwitchHappensOnlyAtRestart::test_the_target_is_built_beside_while_the_old_daemon_serves_unchanged`: a uv wrapper records, for every build, the clone's HEAD and whether the old daemon process exists. The staged build comes first, with the live HEAD unmoved and the old daemon up. The in-place build comes after, with the old daemon down. No stage or marker is left.
- `test_a_target_venv_that_cannot_be_built_never_stops_the_old_daemon`: no restart, the old pid still alive, the clone and venv untouched.
- `test_a_failure_after_the_stop_restores_and_restarts_the_old_version`: a uv wrapper that fails only the in-place build. The old commit and venv are restored and the old daemon is started again.
- `TestNoHookStartsADaemonMidSwitch`: with a live marker, the hook attempts no start and answers "starting". With a dead marker, it goes on to start.
- The red run had 5 failures: 4 of those tests, plus the background failure test, which now expects the old daemon never stopped (`starts() == 1`).

The sandbox's stand-in daemon gained a `stop` (`tests/venv_bootstrap_sandbox.py`). It ends the stand-in only when its environment names that sandbox's PID file, the check `cleanup()` already makes. Before this, `stop` reached the real CLI, which fails in a fixture project without an `origin` remote.

## TDD: red before green

- First version: the module tests failed with `ImportError: cannot import name 'background_sync'`. `TestTheBackgroundSync` failed 10 tests with `PROVISION FAILED: unknown argument: --background`. The handler tests failed with `AttributeError: ... does not have the attribute 'launch_background_sync'`.
- Shell rework, before the forwarder, `provision.sh` and module changed: 5 failed. These were `test_the_session_start_forwarder_starts_the_same_flag`, `test_the_module_does_not_import_subprocess`, `test_a_pulled_upgrade_is_synced_after_the_hook_has_answered` ("did not finish within 60.0s"), `test_the_start_comes_before_the_relay_hot_path` ("substring not found") and `test_a_sync_waits_for_a_running_daemon_and_otherwise_claims_nothing`.

## Targeted QA

`./scripts/qa/llm_qa.py changed` from the worktree, with `FULL_QA_LOCK_WAIT_SECONDS=3000` (other worktrees held the host-wide lock).

- On `7bcb35cf2`: 35/40 passed. `security` passed, with no bandit finding. It failed `magic_values` (two literal timeouts in the new test), `signal_targets` (the test's `terminate()`; it now goes through `safe_signal.stop_verified_daemon`), `changed_tests` (`.claude/hooks/session-start` mapped to no test; declared in `scripts/qa/changed_tests_map.yaml` with the three test files that run it, which adds coverage and exempts nothing) and `plan_qa`.
- On `6bc2f5b45`, plain `changed`: only `plan_qa` and `changed_tests` failed. `changed_tests` failed solely because `.claude/hooks/session-start` is "too-broad": through `daemon/cli.py` its tests reach 100+ files, "the suite by another name". The handover rule allows `--allow-unmapped` for that case.
- Final, on `6bc2f5b45`, `changed --allow-unmapped`: **QA: 37/40 PASSED, 1/40 FAILED, 2/40 NOT MEANINGFUL, exit 1.**
  - The one failure is `plan_qa`: an ADVISE finding (`journal-freshness`) for Plan 00471, not this branch.
  - `security`, `signal_targets`, `magic_values`, `error_hiding` and every other code check pass.
  - `changed_tests`: 3673 passed, 0 failed, 5 skipped (83 test files from 16 changed files). `project_handlers`: 238 passed. Both are marked NOT MEANINGFUL only because `plan_qa` failed.
- Final after review round 2, on `79ca131e4`, `FULL_QA_LOCK_WAIT_SECONDS=3600 changed --allow-unmapped`: **QA: 37/40 PASSED, 1/40 FAILED, 2/40 NOT MEANINGFUL, exit 1.**
  - The one failure is again `plan_qa`'s ADVISE `journal-freshness` for Plan 00471, not this branch.
  - `shell_check`, `shell_audit`, `security`, `error_hiding`, `signal_targets`, `magic_values`, `docs_qa` and every other check pass.
  - `changed_tests`: 4006 passed, 0 failed, 5 skipped (93 test files from 19 changed files, 2 unmapped). `project_handlers`: 238 passed. Both are NOT MEANINGFUL only because `plan_qa` failed.

## Task 5.4 tests (the three cases the plan names)

- **A pulled newer version syncs and restarts:** `test_provision_sh.py::TestTheSessionStartHookStartsIt::test_a_pulled_upgrade_is_synced_after_the_hook_has_answered` runs the real forwarder end to end: the state becomes `synced`, the clone is at the new tag, there is one restart, and the log reads `SYNCED`. Also `TestTheBackgroundSync::test_a_pulled_newer_version_syncs_restarts_and_records_it`.
- **A sync failure keeps the old daemon:** `test_a_sync_failure_keeps_the_old_daemon_and_records_why` (clone and venv back, old daemon restarted, state `failed` naming the venv). Also `test_a_refused_clone_is_recorded_as_a_failure`, `test_a_target_that_needs_reading_is_recorded_and_changes_nothing`, and the handler's FAILED, STOPPED and recorded-success reports.
- **The daemon's own repository never syncs:** the two tests named in the table above.

## Success Criteria

- **After a pull that changes `daemon.expected_version`, the next session runs the daemon at the new version without a manual step:** LEFT UNTICKED. It holds for an UPGRADE in a project carrying `provision.sh`, where the target's gate does not stop for reading. It does not hold for a downgrade (manual, Assumption 1) or for a target whose gate wants its reading confirmed (Task 5.3). The criterion as written covers every pull. The coordinator may rule that the upgrade case is what was meant.
- **The fresh-clone message names `provision` and the version:** TICKED. `test_init_sh_needs_provision.py::TestSessionStartAndUserPromptSubmit::test_human_and_agent_both_get_the_provision_message`.
- **Provision brings up exactly that version, with no restart and no tracked change:** TICKED. `test_provision_sh.py::TestProvisioning`.
- **Provision never clones `main`:** TICKED. `test_installs_exactly_the_tag_the_config_names_never_main`, `test_a_bare_tag_ref_is_fetched_and_nothing_else`.

## Not verified

- A real daemon, rather than the sandbox stand-in, being restarted by a sync the forwarder started.
- `nohup` without `setsid` (macOS), which only ignores SIGHUP. Whether Claude Code kills a finished hook's process group there is not tested.
- The real `hooks-daemon stop` and `restart` in the switch. The sandbox stand-in's are tested, not the real CLI's, which needs a project with an `origin` remote. The switch window is now the stop, the moves and three renames, and the restart; no build runs in it.
- The venv rebind is proven on a real `uv` venv (the experiment above) and on the stub's imitation of its files in the tests, but no test builds a real venv: the suite has no network or real `uv`. A future `uv` that writes the build path into a file not covered (a binary, or a new text file) is caught for text files by the post-rebind check and the sync fails before the stop; a binary one would not be caught.
- macOS: `_provision_rename` uses plain `mv` and checks for a move-into afterwards, written for BSD `mv` too, but it ran only on Linux here.
