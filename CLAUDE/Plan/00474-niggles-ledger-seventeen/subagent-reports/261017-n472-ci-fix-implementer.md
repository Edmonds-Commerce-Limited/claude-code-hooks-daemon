# N472 CI fix: implementer report

Three agents worked this in turn (two handed off at their context budget). Branch `worktree-ci-fix-472`, cut from main at 0a502fab9. All runs below are local Python 3.11 only; the host has no 3.12 or 3.13.

## Assumptions

- Protected files are excluded from the sweep fingerprint, as the guard test `test_no_module_reads_git_enumerated_content_unprotected` prescribes. The alternative (hash them without reading content) was not taken: the guard's intent is that a protected path is never touched by the sweep.
- The hard-coded status-line count of 17 was obsolete: Plan 00471 (d4425ac43) added the 18th handler, `spend_meter`. The test now compares against the registry instead of a number.
- No exclusion, allowlist entry or suppression was added anywhere.

## The 3.12 leg was not a hang

Job 117240770100 started 23:18:46 and was cancelled at 00:59:03 (101 min, under the 150 min job timeout, so a run cancel, not the timeout). It was progressing: 93% at 00:58:20, inside `tests/unit/utils/test_secret_file_matching.py`. The previous completed 3.12 job took 1:38:05 for pytest alone, so 3.12 is the slowest leg. At cancellation about 7% remained.

## Baseline

The "last green" main run 282f49765 (run 38978729873) ran the docs tier only; its Python matrix was skipped. The last run whose Python matrix passed is 38676627123 on c264f7a68 (2026-10-15), so every failure below is new since then. Runs on ac21f83d1 and 85d9b2655 already failed on items 1, 2, 4, 6 and 7, so those predate the Plan 00472 merge.

## Classification and outcome

| #   | Test                                                                                                     | On main, local 3.11                 | Class                               | Outcome                                                 |
| --- | -------------------------------------------------------------------------------------------------------- | ----------------------------------- | ----------------------------------- | ------------------------------------------------------- |
| 1   | `TestConfig::test_load_converts_recursion_error_to_value_error`                                          | fails                               | reproduces                          | fixed in `yaml_loading.py` (53510b4ac)                  |
| 2   | `TestDogfoodingHookScripts::test_hook_scripts_match_installer`                                           | fails                               | reproduces                          | fixed in `install.py` (86d62cd88)                       |
| 3   | `test_no_module_reads_git_enumerated_content_unprotected`                                                | fails (`sweep_cache.py` 165)        | reproduces                          | fixed in `sweep_cache.py` (86d62cd88)                   |
| 4   | `test_every_live_probe_is_marked`                                                                        | fails (`test_provision_sh.py` 1331) | reproduces                          | test payload marked `synthetic_source: test-probe`      |
| 5   | `test_the_zero_to_nine_row_names_what_ships_there`                                                       | fails                               | reproduces                          | `background_task_recorder` added to the 0-9 row         |
| 6   | `TestJsonOutput::test_json_output_parses_and_has_every_handler`                                          | fails (`18 == 17`)                  | reproduces                          | expectation was obsolete; now derived from the registry |
| 7   | `TestLiveGoToolchain::test_an_unused_variable_is_allowed_mid_edit`                                       | passes (local go 1.19.8)            | CI environment (newer Go), real bug | regex fixed in `go_strategy.py`                         |
| 8   | `TestDecision::test_unlistable_agent_directory_fails_open_and_is_recorded_unmeasured`                    | passes                              | CI environment: Python 3.13 only    | patch scoped to the `handle()` call                     |
| 9   | `test_forwarder_generator::test_every_real_deployed_hook_is_byte_identical_when_disabled[session-start]` | fails                               | reproduces                          | fixed with item 2                                       |

3.11 failed 8 (no resume guard test there), 3.13 failed 9.

## Causes, red output and fixes

1. **Deep nesting.** Plan 00495 Task 2.2 (d356d41bc) moved config parsing to `CSafeLoader`. libyaml recurses in C with no depth limit: 5000 deep parses to a list (a pydantic error instead of "nested too deeply"), 50000 deep segfaults the process (measured: 20000 ok, 50000 and 100000 SIGSEGV). Red: the child process returned `-11`, and `AttributeError` for the missing `C_LOADER_MAX_OPEN_BRACKETS`. Fix: a document with more than 1000 `[` plus `{` goes to the pure-Python `SafeLoader`. Tests: `tests/unit/config/test_yaml_loading.py::TestDeepNestingNeverReachesTheCParser`; 715 config tests pass.
2. **Installer and the session-start hook (items 2 and 9).** Plan 00477 Task 5.2 (7bcb35cf2) hand-added a `provision.sh --background` block to the tracked `.claude/hooks/session-start` but did not teach the installer to emit it. Its comment also said "relay hot path", the marker string the forwarder test requires to be absent when disabled. Red: the dogfooding diff showed the whole `# Plan 00477 Task 5.2 ... provision.sh --background` block missing from the installer's output; `test_forwarder_generator[session-start]` failed on `"relay hot path" not in result`. Fix: `install.py` gains `_SESSION_START_BACKGROUND_SYNC_BLOCK` and `_SESSION_START_EVENT_NAME`, and `create_forwarder_script` inserts the block under `SCRIPT_DIR` for SessionStart only; the comment now says "relay guard block" in both places. Tests: `tests/unit/install/test_background_sync.py::TestInstallerEmitsTheBackgroundSync`; 210 passed over dogfooding, forwarder generator, background sync and relay guard eligibility.
3. **Sweep fingerprint.** `tree_fingerprint` stated every path from `git ls-files`, protected ones included. Red: `assert 'id_rsa' not in ['.gitignore', 'A.md', 'id_rsa', 'mo...` and the fingerprint moved when the protected file was edited. Fix: skip `path_is_protected(...)` paths. Tests: `test_a_protected_path_is_never_stated`, `test_editing_a_protected_file_does_not_move_the_fingerprint` in `tests/unit/utils/test_sweep_cache.py`; the name is read from the live config (`_protected_name()`) because the secret guard blocks literal names in authored files.
4. **Probe marker.** Red: `tests/integration/test_provision_sh.py:1331: no synthetic_source`. Fix: `synthetic_source: test-probe` in the payload.
5. **Band row.** Red: `the 0-9 band row does not name what ships there: ['BACKGROUND_TASK_RECORDER']`. Fix: the row in `CLAUDE/HANDLER_DEVELOPMENT.md` names `background_task_recorder`.
6. **Status-line count.** Red: `assert 18 == 17`. The 18th is `spend_meter` (Plan 00471). The test now compares the JSON `class_name` set with the registry's status-line handlers.
7. **Go 1.20+.** vet prints `declared and not used: x`; `_UNRESOLVED_NAME` required the message to end at "used". Red (new mocked test `test_newer_go_declared_and_not_used_with_a_name_is_allowed` in `TestMockedShapes`, with `./c.go:3:12: declared and not used: x`): `AssertionError: assert 'deny' == 'allow'`. Fix: an optional `(?:: \S+)?` suffix. The live Go test cannot run here (go 1.19.8 prints the old wording), so the mocked shape stands in for it.
8. **Resume guard.** The test patched `os.scandir` for the rest of the test; on 3.13 `Path.iterdir` uses `os.scandir`, so `unmeasured_count` itself raised and returned 0. The handler is fine. Red could not be reproduced on 3.11 (it passes); the fix scopes the patch with `monkeypatch.context()` around the `handle()` call only. It passes on 3.11 with the change; 3.13 confirmation has to come from CI.

## Release note

`CLAUDE/UPGRADES/UNRELEASED/release-notes/080-ci-fixes-nested-config-session-start-sweep-fingerprint-go-vet.md` covers the four `src/` and installer changes.

## Not verified locally

Python 3.12 and 3.13 behaviour (item 8), and the live Go toolchain test with Go 1.20 or later (item 7).
