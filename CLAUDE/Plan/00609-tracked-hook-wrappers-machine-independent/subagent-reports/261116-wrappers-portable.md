# Plan 00609: wrappers made machine independent

## Task 1.1 measurement (before the fix)

Method: `generate_forwarder_content` over every `.claude/hooks/*` file, in three synthetic roots (short, medium, 60 characters of nesting), for the relay transport and the nc-only transport, root-normalised, then diffed. Host and uid are the measuring machine's (uid 1000, one host), so the host/uid parts below are read from the generated text, not varied.

Every byte that differs, by kind:

| Site (relay block, all 28 relayed wrappers)                               | Value kind             |
| ------------------------------------------------------------------------- | ---------------------- |
| `BASH_SOURCE` prefix test `== "<root>/.claude/hooks/"*`                   | absolute checkout path |
| `_rl_dir="<root>/untracked"` (or `<root>/.claude/hooks-daemon/untracked`) | absolute checkout path |
| `_rl_bin` default `<root>/untracked/bin/hooks-relay`                      | absolute checkout path |
| `HOOKS_DAEMON_RELAY_DAEMON_ROOT="<root>"`                                 | absolute checkout path |
| status-line fast path: same four sites                                    | absolute checkout path |

Second, shape-changing branch, taken when `<untracked>/events-<host>` plus the longest socket name exceeds 104 bytes (the medium and deep roots here): the whole `_rl_sfx` / `_rl_events_dir` computation is replaced by one baked line, for example `/run/user/1000/hooks-daemon-ffe4d7dc-3d967e-events`. The peer's report is CONFIRMED. Its three parts:

- `/run/user/1000`: the runtime directory and uid of the generating machine (`XDG_RUNTIME_DIR`, else `/run/user/<uid>`, else `/tmp`).
- `ffe4d7dc`: md5 of the untracked dir path, first 8 hex characters (differs per root).
- `3d967e`: md5 of the hostname suffix, first 6 hex characters (differs per host).

The same baked path also reached the nc rung: with `nc_enabled`, every wrapper's last call line carried it as the trailing events-dir argument (`send_request_stdin "PreToolUse" "" "pre-tool-use" "/run/user/1000/hooks-daemon-...-events"`), including the stop and subagent-stop wrappers that have no relay block. That is 28 of 31 wrappers on a long root with nc on, not only the relay ones.

Not found: no other value. The hostname-dependent suffix `-$HOSTNAME` is computed at run time already, and the timeout is config.

## Task 1.2 defence test

`tests/unit/install/test_forwarder_machine_independent.py`. It generates every wrapper under relay, nc and both transports for a short root and a root far past the AF_UNIX limit, with a different `XDG_RUNTIME_DIR` and hostname for each, and asserts byte identity plus no machine-specific absolute path (`surviving_absolute_paths`). Committed first and confirmed failing on the old generator (commit before the fix on this branch).

## Fix

- Root: `_rl_src="${BASH_SOURCE[0]}"`, require `/*/.claude/hooks/*`, `_rl_root="${_rl_src%/.claude/hooks/*}"`, `_rl_dir="$_rl_root/<layout>"`. The layout (`untracked` or `.claude/hooks-daemon/untracked`) is the only thing written and is computed with `relative_to`, failing fast if the untracked dir is not below the root. The relay binary default is `$_rl_dir/bin/hooks-relay`, the daemon root `${_rl_dir%/*}`. An explicit configured relay binary path is still written (config, not machine state). Markers are unchanged, so the existing strip regex converges an old block.
- Overflow case: cannot be computed in bash without a spawn (md5). The daemon now publishes `untracked/events<host-suffix>.location` (line 1: the untracked dir it was written for, line 2: the events dir) from `server.py` where it binds the event sockets (`paths.publish_events_dir_location`, atomic, removes a stale file when the layout is natural). The wrapper tries the natural dir first, consults the file only when the natural dir is absent and `HOOKS_DAEMON_EVENTS_DIR` is unset, and trusts it only when line 1 equals its own `_rl_dir` (so a copied checkout never trusts another's file). Builtins only, inside an `if` so errexit cannot trip; bash 3.2 safe.
- nc: the trailing events-dir argument is always `""` now (slot kept for positions); `init.sh`'s nc rung reads the same location file when the argument and env override are empty. A non-empty argument in an older wrapper is still honoured.
- Removed as dead: `PROJECT_ROOT_PLACEHOLDER`, `normalise_project_root`, `recorded_untracked_dir`, `recorded_project_root`, `unexpected_absolute_paths` (their only consumer was the dogfood test, which now compares exactly with no normalisation) and `tests/unit/install/test_forwarder_root_normalisation.py`. `surviving_absolute_paths` stays and is used by the new test and the dogfood test.
- This worktree's `.claude/hooks/*` (28 files) were regenerated with the generator CLI and committed; a second CLI run rewrites nothing.

## Behaviour changes to know about

1. A copy of a wrapper (git worktree) used to skip the relay guard; it now resolves its own root and dials its own checkout's socket, finding none unless that checkout runs a daemon. It still never dials the original's socket. Test `test_a_worktree_copy_never_dials_the_originals_socket` replaces the old skip test.
2. A relative `BASH_SOURCE` still takes the legacy path.
3. On an overflowing layout, an older daemon (no location file) means the wrapper falls through to the legacy transport until the daemon restarts. Previously the baked fallback path worked immediately after a regenerate.

## Verification

Targeted only: `tests/unit/install/{test_forwarder_generator,test_forwarder_generator_cli,test_forwarder_generator_raw_stdout,test_forwarder_init_parse_guard,test_forwarder_events_dir_suffix,test_forwarder_machine_independent,test_relay_guard_loud_fallthrough,test_relay_deploy,test_transport_verify}.py`, `tests/unit/constants/test_event_budgets.py`, `tests/integration/test_dogfooding_hook_scripts.py`, `tests/integration/test_hooks_deploy_relay_guard.py` (518 passed), `tests/unit/daemon/{test_events_dir_location,test_event_socket_paths,test_event_socket_listeners,test_server_coverage}.py` (passed). ruff and mypy clean on the touched source. `bash -n init.sh` clean. The new runtime tests execute the generated bash against a real AF_UNIX socket and a fake relay in two roots from one generation.

Not done: no end-to-end test of `init.sh`'s nc location lookup (only syntax-checked and mirrored from the tested wrapper lines); no server-level test that `start` calls the publisher; `llm_qa.py changed` and the full gate not run (coordinator's). `tests/unit/install/test_bin_wrapper_project_anchoring.py` fails in this worktree for an unrelated venv reason and was not touched.

Pre-existing open question: the legacy `daemon<suffix>.socket-path` discovery file has no recorded-untracked-dir confinement; I mirrored the safer design for the new file only.

## Follow-up: the two coordinator gaps (closed)

1. Server test, `tests/unit/daemon/test_event_socket_location_publish.py` (5 tests, real `HooksDaemon.start`/`shutdown`): an overflowing layout publishes the untracked dir then the events dir; a natural layout and a disabled transport publish nothing; after shutdown the file remains but its events dir is gone (nothing to dial, so a forwarder falls through; a file naming another checkout is ignored, covered by the wrapper and nc tests); a restart overwrites a stale file.
2. Executable nc test, `tests/integration/test_init_sh_nc_location.py` (3 tests): sources a copy of the real init.sh and runs the real `send_request_stdin` with a stub `nc` that reports its socket, against a real listening socket. A location naming its own untracked dir is used; one naming another checkout's dir is ignored; an existing natural events dir wins without consulting the file.
3. Found while checking: `tests/unit/install/test_forwarder_status_fast_path.py` still asserted the old literal guard; updated to the derived-root form (it was not in my first targeted run).

`tests/unit/install/test_bin_wrapper_project_anchoring.py::TestTheAnchorReachesTheCommand::test_a_global_anchor_selects_the_tree_the_command_reads` fails identically on a fresh detached worktree of origin/main (1 failed, 14 passed), so it is not caused by this branch.

Note: 56 relay-guard integration tests skip here for lack of a built relay binary; they could not be exercised locally.

## Worktree without a daemon: measured before and after

Method: two real `git worktree add --detach` checkouts of this repository (origin/main and this branch), no daemon running in either, a PreToolUse payload for a destructive git command piped into the checkout's own `.claude/hooks/pre-tool-use`, the main checkout's daemon live throughout.

| Question                            | (a) origin/main wrapper                                         | (b) this branch                                             |
| ----------------------------------- | --------------------------------------------------------------- | ----------------------------------------------------------- |
| Relay path taken                    | no (baked-root guard fails in a copy), falls to init.sh         | own checkout's events dir; absent, so falls to init.sh      |
| Daemon auto-started in the worktree | attempted by init.sh; not ready within 15s here                 | identical                                                   |
| Outcome with no daemon              | fail closed: `permissionDecision: deny`, daemon_startup_failed  | identical                                                   |
| Silent allow                        | no                                                              | no                                                          |
| Reached the MAIN checkout's daemon  | no (own sockets derived from the script location)               | no (own checkout's events dir only)                         |

Conclusion: (b) is no worse than (a); no fix needed. Pinned by `test_a_worktree_copy_without_a_daemon_still_fails_closed` (a copy beside a live original socket and relay: no relay exec, no allow, init.sh's start-or-deny reached). The probe worktrees and their disposable ignored files were deleted before `git worktree remove`.
