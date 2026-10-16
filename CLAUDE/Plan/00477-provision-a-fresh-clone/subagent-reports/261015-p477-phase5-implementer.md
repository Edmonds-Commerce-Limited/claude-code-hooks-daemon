# Plan 00477 Phase 5 implementer: Tasks 5.2, 5.4 and 4.2

Worktree: `untracked/worktrees/worktree-p477-background-sync`. Commits: `98c7ee990` (the work) and `55642216d` (targeted-QA fixes: error_hiding, black). The plan tick and this report are in the commit after those.

## STOP ITEM: a suppression is needed, and I did not add it

Targeted QA leaves two bandit findings on the one new process-spawn site. The handover rules forbid me adding a suppression and say to report it:

- `B404  src/claude_code_hooks_daemon/install/background_sync.py:22` (`import subprocess`)
- `B603  src/claude_code_hooks_daemon/install/background_sync.py:171` (`subprocess.Popen(`)

Starting a detached process is the task itself. Bandit flags every way of doing it: `subprocess` is B404 and B603, `os.fork` plus `os.exec*` is B606. No existing helper spawns a detached process that this could reuse. The project's sanctioned form is an inline `nosec` with its reason (owner ruling B2; `scripts/qa/check_inline_suppressions.py`; the same pair exists in `install/transport_verify.py:37,158` and `daemon/background_harvester.py:47,379`). Proposed lines, for the owner to add by hand:

```python
import subprocess  # nosec B404 - only to start the project's own tracked provision.sh, fixed argv, no shell
```

```python
            process = subprocess.Popen(  # nosec B603 - fixed argv: bash from PATH, the project's tracked .claude/provision.sh, --background; no shell, no user input
```

Because of this, **Task 5.2 is left unticked in PLAN.md**. Its code, tests and docs are complete, and it is done once those two annotations are in.

## Assumptions (for the coordinator to have ruled on)

1. **Only an UPGRADE is synced in the background.** A downgrade keeps the manual route. The Task 5.1 notice already asks a human to confirm that a downgrade is intended, because a commit made from an older checkout looks the same as a deliberate downgrade. Syncing it automatically would skip that confirmation. `provision.sh --background` also refuses a downgrade itself.
2. **The background sync never provisions a fresh checkout.** The owner ruled that fresh provisioning is deliberate (Overview, Non-Goals). Phase 5 covers only the case where a daemon is already present. `--background` refuses when no clone exists.
3. **"Once per target version" means once, not once per success.** After a failure the sync is not retried in the background. Every session start reports the failure and names the state file to delete for a background retry, and `bash .claude/provision.sh` to run by hand. This prevents a sync that fails the same way from running at every session start.
4. **A target whose pre-deploy gate wants the reading list confirmed is reported, not confirmed.** Task 5.3 keeps the gate's reading confirmation, and a detached process has nobody to read. It records `needs-reading`, and the notice tells the human or agent to run provision by hand. Provision prints the listing and the `--skip-reading-confirmation=<digest>` flag.

## The trigger point, and why

**Decision:** the SessionStart `version_check` handler, in the running daemon. When it detects UPGRADE drift and the project carries the tracked `.claude/provision.sh`, it starts `bash .claude/provision.sh --background` detached and returns. The process runs in a new session with stdin closed and output to the log, and a daemon thread reaps it.

Why there, and not in `init.sh`:

- **SessionStart usually never reaches `init.sh`.** The generated forwarders `exec` the relay binary whenever the relay socket exists (`.claude/hooks/session-start`, "relay hot path"), and the relay socket exists while the daemon runs. A trigger in `init.sh` would therefore miss the common case: an old daemon that is still running, or one that `init.sh` starts successfully from the old clone.
- **The handler already makes the drift decision** (Task 5.1), from local facts only, before the cache or the network. Starting the sync there adds one `Popen` to a decision that is already made. The hook's time budget is not touched.
- **The sync logic is the PULLED version's.** The handler runs the tracked `.claude/provision.sh`, which the pull brought in. So the sync steps are the target's, even though an old daemon's handler starts them.
- **The cost:** only an installed daemon at this release or later starts the sync, so the first move onto this release is still a manual `bash .claude/provision.sh` (or the upgrade itself). The release note says so.
- **A clone too broken to start** (`init.sh`'s stale-clone path after a failed start) is not synced in the background. It still gets the 5.1/5.2a message naming provision. There is no old daemon to keep serving in that case, and the hook would have to spawn the process inside its own budget path.

**Lock and marker** (`provision.sh`, `_provision_background_claim`):

- Lock: `mkdir .claude/hooks-daemon/untracked/background-sync/lock.d` (atomic), holding the pid. A lock whose pid is dead is taken over. A live holder makes the new run exit 0 without claiming anything, so a later session tries again.
- Marker: `v<version>.state`, written under the lock. If it already exists, the run stops ("already attempted"). The state then moves from `running` to `synced`, `failed` (with the `PROVISION FAILED` reason) or `needs-reading`, written by an EXIT trap from the exit status. The handler also checks the state's pid: a `running` state whose process is gone reads as `failed`, for example after a reboot.
- Both live under the clone's `untracked/`, which a checkout never touches and which the dirty-clone check excludes.

**Reuse:** `--background` is a flag on 5.2a's own sync path (`_provision_sync_clone`). Nothing in the sync was duplicated. It adds the claim before the sync, the trap after it, and the two refusals (downgrade, fresh checkout).

## What "the old daemon keeps serving" does and does not mean

The old daemon PROCESS is not stopped until `bin/hooks-daemon restart`, the last step, so it answers hooks throughout the fetch, the gate and the venv build. A failure before the restart never stops it. A failure after the checkout restores the commit and venv and restarts it, which is 5.2a's existing rollback. **The limitation, stated plainly:** 5.2a's sync checks the tag out in place and moves the venv aside before the rebuild. A module the old process imports lazily during that window would come from the new checkout, or fail to import. Code it imported at startup (the handlers and the server) is unaffected. Removing that window would mean building the target in a separate directory and swapping, but the clone's own build path keys the venv on the clone's path. That is a change to 5.2a's design, not to the trigger, so I did not make it. I did not measure how much the daemon imports lazily.

## Delivered

- `src/claude_code_hooks_daemon/install/background_sync.py` (new): names the state and log files, reads a state back (`SyncRecord`), and starts the detached process (`launch_background_sync`). An unreadable state, an unknown status or a dead `running` pid reads as FAILED, never as silence.
- `src/claude_code_hooks_daemon/handlers/session_start/version_check.py`: drift detection (`_expected_drift`, no side effects; `matches()` on a resume uses it, so it starts nothing) is split from the notice (`_drift_context`). The notice now starts the sync, or reports the recorded outcome, for an upgrade. STARTED and UNDER WAY are informational. FAILED, STOPPED, "recorded success yet still old", and COULD NOT START are loud and each names the reason, the log, `bash .claude/provision.sh` and the state file to delete. SessionStart context is emitted as `systemMessage` too, so the human sees it.
- `provision.sh` (`.claude/provision.sh` is a symlink to it): `--background`, `SYNC_STATE_DIR_NAME`, lock, claim, EXIT-trap outcome, and `_PROVISION_FAIL_REASON` recorded by `_provision_fail`.
- Docs: the `provision` skill page (both copies, kept identical), "In the background, after a pull"; a TROUBLESHOOTING paragraph under the version-drift entry.
- Task 4.2: release note `066-a-pulled-daemon-version-upgrade-syncs-itself-in-the-background.md`. Post-upgrade task `02-commit-the-expected-version-and-provision-sh.md` (an upgraded project gains the key and the tracked `provision.sh`, and must commit both for other checkouts to follow), indexed in the post-upgrade README. The key and `provision.sh` themselves shipped in v3.68.0 (notes 187 and 193, `config-changes/v3.68.0.yaml`), so the new note is about the background sync, and the task covers committing what the upgrade added.

## TDD: red before green

- `tests/unit/install/test_background_sync.py` before the module existed: `ImportError: cannot import name 'background_sync' from 'claude_code_hooks_daemon.install'` (collection error).
- `tests/integration/test_provision_sh.py::TestTheBackgroundSync` before `provision.sh` changed: 10 tests failed, with `PROVISION FAILED: unknown argument: --background`.
- `tests/unit/handlers/session_start/test_version_check_drift.py` before the handler changed: `AttributeError: <module '...version_check'> does not have the attribute 'launch_background_sync'`.
- `TestTheLauncherVersionCheckUses` (launcher plus real `provision.sh --background`, end to end in the sandbox) was written after the parts it joins were green, so it has no red run.

## Task 5.4 tests (the three cases the plan names)

| Case                                      | Tests                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ----------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A pulled newer version syncs and restarts | `test_provision_sh.py::TestTheBackgroundSync::test_a_pulled_newer_version_syncs_restarts_and_records_it`; `::TestTheLauncherVersionCheckUses::test_a_launched_sync_finishes_on_its_own_and_restarts_the_daemon` (detached, launcher returns under 2 s, state `synced`, clone at the new tag, one restart); `test_version_check_drift.py::TestAPulledUpgradeIsSyncedInTheBackground::test_the_first_session_starts_the_sync_and_says_so` |
| A sync failure keeps the old daemon       | `::test_a_sync_failure_keeps_the_old_daemon_and_records_why` (clone and venv back, old daemon restarted, state `failed` naming the venv); `::test_a_refused_clone_is_recorded_as_a_failure`; `::test_a_target_that_needs_reading_is_recorded_and_changes_nothing`; handler: `test_a_failed_sync_is_reported_loudly_with_the_command_and_not_retried` and its STOPPED, recorded-success and could-not-start siblings                     |
| The daemon's own repository never syncs   | `test_provision_sh.py::TestTheBackgroundSync::test_the_daemons_own_repository_never_syncs`; `test_version_check_drift.py::TestSilentWhenNothingDrifted::test_the_daemons_own_repository_never_reports_drift_or_syncs` (launcher never called)                                                                                                                                                                                           |

Also covered: once per target (`test_a_target_already_attempted_is_never_attempted_again`), no overlap (`test_a_sync_already_running_is_not_joined`, `test_a_lock_whose_holder_is_gone_is_taken_over`), no downgrade (provision and handler), no fresh checkout, no launch from `matches()`, and a dead `running` pid read as a failure.

Runs, all in the worktree venv:

- `pytest tests/integration/test_provision_sh.py tests/unit/install/test_background_sync.py`: 72 passed (before the launcher test was added). `-k 'Launcher or Background'` after it: 11 passed.
- `pytest tests/unit/handlers/session_start/ tests/unit/install/test_background_sync.py`: 894 passed.
- `pytest tests/integration/test_upgrade_task_schema.py tests/integration/test_post_upgrade_tasks_are_reachable.py`: 54 passed.
- `ruff check` and `mypy --strict` on the two source files: clean.

## Targeted QA

`./scripts/qa/llm_qa.py changed` from the worktree, with `FULL_QA_LOCK_WAIT_SECONDS=3000` because other worktrees held the host-wide lock. The first attempt timed out on the lock without running.

- Run 1 (on `98c7ee990`): 34/40 passed. It failed `format` (black restyled three new tests; committed in `55642216d`), `error_hiding` (two `return-none-on-error`, fixed in `55642216d` by returning after the `except`, as `bebed359c` did), `security` (below) and `plan_qa`.
- Run 2 (on `55642216d`), the final verdict: **QA: 36/40 PASSED, 2/40 FAILED, 2/40 NOT MEANINGFUL, exit 1.**
  - `security`: the two bandit findings in the STOP ITEM above.
  - `plan_qa`: one ADVISE finding, `journal-freshness` for Plan 00471, which is not this plan and not this branch.
  - `changed_tests`: 2945 passed, 0 failed, 5 skipped (60 test files from 14 changed files, 0 unmapped). `project_handlers`: 238 passed. Both are marked NOT MEANINGFUL only because a detector above failed.

## Success Criteria

- **After a pull that changes `daemon.expected_version`, the next session runs the daemon at the new version without a manual step:** LEFT UNTICKED. It holds for an UPGRADE, where the installed daemon is at this release or later, the project carries `provision.sh`, and the target's gate does not stop for reading (the tests above). It does not hold for a downgrade (manual by Assumption 1), for a target whose gate wants its reading confirmed (Task 5.3 keeps that confirmation), or for the first move onto this release. The criterion as written covers every pull, so I cannot show it. The coordinator may rule that the upgrade case is what was meant.
- **In a fresh clone of a configured fixture project, the first session shows the human a message naming `provision` and the expected version:** TICKED. `tests/integration/test_init_sh_needs_provision.py::TestSessionStartAndUserPromptSubmit::test_human_and_agent_both_get_the_provision_message` (SessionStart `systemMessage` carries "NEEDS PROVISIONING", 3.68.0 and the command); the class passed in this worktree.
- **Running provision brings up the daemon at exactly that version, with no restart and no change to any tracked file:** TICKED. `test_provision_sh.py::TestProvisioning`: `test_installs_exactly_the_tag_the_config_names_never_main`, `test_builds_the_venv_and_starts_the_daemon`, `test_says_no_session_restart_is_needed`, `test_the_next_hook_finds_the_daemon_already_running` and `test_writes_no_tracked_file` all passed in this worktree.
- **Provision never clones `main` when the config names a version:** TICKED. `test_installs_exactly_the_tag_the_config_names_never_main` and `TestSyncingAnExistingClone::test_a_bare_tag_ref_is_fetched_and_nothing_else`.

## Plan state after this branch

Tasks 4.2 and 5.4 are ticked, citing the commits. Task 5.2 is unticked (STOP ITEM). Success Criteria 2-4 are ticked, citing their tests. Criterion 1 is unticked (above).

## Not verified

- A real daemon starting the sync and being restarted by its own detached child. The end-to-end test uses the sandbox's stand-in daemon, with pytest as the launcher. `start_new_session=True` is what makes the child survive the restart, and `test_the_sync_runs_in_its_own_session` checks it.
- The relay path during the restart window.
- How much the daemon imports lazily during the in-place checkout window (see above).
