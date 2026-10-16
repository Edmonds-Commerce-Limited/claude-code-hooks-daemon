# Plan 00477 Phase 5 implementer: Tasks 5.2, 5.4 and 4.2

Worktree: `untracked/worktrees/worktree-p477-background-sync`. Commits, in order:

- `98c7ee990`: the first version, which launched the sync from Python.
- `55642216d`: error_hiding and black fixes.
- `7bcb35cf2`: the launch moved into shell (the coordinator's suppression-free route).
- `6bc2f5b45`: signal_targets, magic_values and the changed-tests map.
- The plan tick and this report are in the commit after those.

## Assumptions (for the coordinator to have ruled on)

1. **Only an UPGRADE is synced in the background.** A downgrade keeps the manual route. The Task 5.1 notice asks a human to confirm that a downgrade is intended, because a commit made from an older checkout looks the same as a deliberate downgrade. `provision.sh --background` refuses a downgrade itself.
2. **The background sync never provisions a fresh checkout.** The owner ruled that fresh provisioning is deliberate (Overview, Non-Goals). `--background` refuses when no clone exists.
3. **"Once per target version" means once, not once per success.** After a failure the sync is not retried in the background. Every session start reports the failure and names the state file to delete for a retry, and `bash .claude/provision.sh` to run by hand.
4. **A target whose pre-deploy gate wants the reading list confirmed is reported, not confirmed.** Task 5.3 keeps that confirmation, and a detached process has nobody to read. It records `needs-reading`.
5. **The sync waits up to 30 s for a running daemon before it touches the clone.** If none is running by then, it claims nothing and changes nothing, and a later session start retries. This keeps the guarantee that the old daemon serves until the new one is ready, and it prevents the sync from moving a clone that the same hook's `ensure_daemon` is starting from.

## The trigger point: the session-start forwarder, in shell

The first version had `version_check` start the sync with `subprocess.Popen`, which drew bandit B404/B603. The coordinator asked for a route needing no new suppression. That route exists and is implemented: Python starts no process at all.

- **Where:** the tracked `.claude/hooks/session-start` forwarder, directly after `SCRIPT_DIR=`. It starts `setsid bash "$SCRIPT_DIR/../provision.sh" --background` (`nohup` where there is no `setsid`) with stdin, stdout and stderr redirected, in the background, and goes on. The hook never waits on it.
- **Relay mode:** the relay guard is generated directly above `source "$SCRIPT_DIR/../init.sh"`. That is why `init.sh` itself was not a usable trigger: with the relay on, SessionStart never sources it. The launch sits above the guard, so it runs with the relay on or off. `test_the_start_comes_before_the_relay_hot_path` builds the relay-enabled forwarder and checks the order. The relay's `--no-relay` fallback re-enters the forwarder, so the launch is skipped on that pass.
- **Cost:** one detached bash per session start. `provision.sh --background` decides for itself whether there is anything to do. In the usual case the clone already matches and it exits ("nothing to do"). In the daemon's own repository it exits before sourcing `init.sh`.
- **Better than the Python route:** the forwarder and `provision.sh` are tracked files, so the commit that moved `daemon.expected_version` brings them in. The pull that changes the version is therefore enough, including the first move onto this release.
- **What Python does now:** `version_check` only READS the state the sync wrote (`install/background_sync.py`: paths and `read_sync_record`; no subprocess import, which a test asserts). With no state yet it says the sync was started this session. Otherwise it reports under way, failed, stopped for reading, or "recorded success yet still old".

The coordinator's guarantees, one by one:

| Guarantee                                        | How                                                                                                                                                                                             | Shown by                                                                                                                                                  |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Never inside a hook's time budget                | Detached `setsid ... &` with every fd redirected                                                                                                                                                | `test_a_pulled_upgrade_is_synced_after_the_hook_has_answered` (venv build slowed to 5 s; the hook returns before the state is `synced`)                   |
| The old daemon serves until the new one is ready | The sync waits for a running daemon (Assumption 5), and the restart is its last step; 5.2a's rollback on failure                                                                                | `test_a_sync_waits_for_a_running_daemon_and_otherwise_claims_nothing`; `test_a_sync_failure_keeps_the_old_daemon_and_records_why`                         |
| Failure is loud                                  | State `failed` or `needs-reading` with the reason; `version_check` shows it at every session start (`systemMessage` plus context) with the log, the manual command and the state file to delete | `TestTheBackgroundSync::test_a_refused_clone_is_recorded_as_a_failure` and siblings; `TestAPulledUpgradeIsReportedAsSyncingInTheBackground`               |
| One sync at a time                               | `mkdir` lock with the holder's pid, taken over when that pid is dead; a per-target state file as the once-only marker                                                                           | `test_a_sync_already_running_is_not_joined`, `test_a_lock_whose_holder_is_gone_is_taken_over`, `test_a_target_already_attempted_is_never_attempted_again` |
| The daemon's own repository never syncs          | `provision.sh` refuses before sourcing `init.sh`; `version_check` reports no drift in self-install mode                                                                                         | `test_the_daemons_own_repository_never_syncs`, `test_the_daemons_own_repository_never_reports_drift`                                                      |

**The old-daemon limitation, stated plainly:** 5.2a checks the tag out in place and moves the venv aside before the rebuild. The old daemon PROCESS keeps answering throughout, but a module it imports lazily during that window comes from the new checkout or fails to import. Removing that window would mean changing 5.2a's build design, not the trigger. I did not measure how much the daemon imports lazily.

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
- How much the daemon imports lazily during the in-place checkout window.
