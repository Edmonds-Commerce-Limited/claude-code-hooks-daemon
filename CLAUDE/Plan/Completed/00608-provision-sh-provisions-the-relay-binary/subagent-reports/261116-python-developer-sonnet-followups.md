# Plan 00608 follow-ups (a)-(d): report

Branch `agent-a1b69a9efb19d326e-42302494`, pushed to origin, not merged, not released.

## Commits (each test-first, each with a release note, PLAN.md Phase 3 ticked)

- (b) 079: `relay_repair.start_relay_repair` now logs an ERROR on the mkdir/open failure branch (the one silent no-file exit). Test: `test_an_uncreatable_state_dir_is_logged`.
- (a) 080: new `install/relay_repair.repair_unusable_relay(root, transport, ...)` is the one judge-and-start decision; the SessionStart `relay_binary_checker` now calls it (behaviour unchanged) and `DaemonController` has a deferred start-up step `"relay repair"` (`_start_relay_repair`) that calls it after the socket is bound. Not run in non-deferred `initialise` (CLI, tests): it can spawn a build. Same `O_EXCL` once-per-cause claim and detached spawn, so a double trigger is harmless. Failures are logged (`log_and_continue` at ERROR, plus an ERROR for a notice carrying a failure); never fatal. New fail-open row in `scripts/qa/fail-open-boundaries.yaml`. Tests: `tests/unit/daemon/test_controller_relay_repair.py`, `TestRepairUnusableRelay`, deferred-startup step list.
- (c) 081: `hooks-daemon status` prints `Relay repair: <status> - <detail>` and `Relay repair log: <path>`, or `Relay repair: no attempt recorded for this cause (state file ...)`, beside the relay WARNING in both running and not-running outputs, via `relay_repair_status_lines` (reads the same state file).
- (d) 082: result record is per view: `untracked/.venv-bootstrap-<fingerprint>.result`, keyed like the build log. Writers: `scripts/install/venv.sh` (`venv_write_build_result` takes the fingerprint; `venv_build_result_path`, `venv_latest_build_result`), `scripts/venv_bootstrap.sh`, `daemon/venv_lock.py` (`write_build_result` takes the fingerprint, `build_result_path`), `daemon/cli.py` repair. Readers (`bin/hooks-daemon` and its template, `init.sh` bash and embedded Python, `venv_bootstrap.sh probe`, Python `status`) show the NEWEST record of any view, since they run without a venv and cannot tell which view they are; its `log=` names the view. No fallback read of the old single file (stated in the note): it is a last-build diagnostic and reading a file either view may have written is the defect.

## Decision to flag

Readers are not per-view, only writers are. Making the hot-path readers (stop hook, no-venv wrapper) view-aware would need the venv resolver or a slug re-implementation there; I judged that out of proportion. If strict per-view reads are wanted, the venv slug of the daemon dir path can select `.venv-bootstrap-<slug>-py*.result`.

## QA

`llm_qa.py changed --base origin/main --allow-unmapped` (second run, after fixing error_hiding, the fail-open inventory row and a semgrep caplog finding): 42/43 passed. semgrep passed here. The one failure, `tests/unit/install/test_bin_wrapper_project_anchoring.py::...::test_a_global_anchor_selects_the_tree_the_command_reads`, dies with `resolve_venv: no usable venv found under <worktree>/untracked/` (the worktree has no venv): an environment fault in this worktree, in code this work does not reach before the failure; not verified against origin/main. Unmapped (too-broad): `bin/hooks-daemon`, `init.sh`, `daemon/cli.py`, `daemon/controller.py` and similar.
