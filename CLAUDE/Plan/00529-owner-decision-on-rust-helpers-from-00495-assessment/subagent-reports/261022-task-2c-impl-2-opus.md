# Plan 00529 Task 2c: implementation report, part 2 (checkpoint plus handoff steps 1 and 3 of 6)

Continues `261022-task-2c-impl-opus.md`. Branch `worktree-529-relay-loud-fallthrough`. I stopped at a natural
break because this agent passed its context budget. The **Handoff** section lists what remains.

## Checkpoint (commit `516c295f8`, pushed)

- **(a) Format.** `./scripts/qa/run_autofix.sh` produced the one-file Black change in `forwarder_generator.py`.
  `black --check src tests` is clean.
- **(b) `test_hook_scripts_match_installer`.** The test regenerates for the roots the deployed forwarders
  already RECORD (`recorded_untracked_dir` and `recorded_project_root`), not this checkout's. The tracked files
  record `/workspace`. `regenerate_deployed_hooks` bakes its `project_root` as both roots, so I ran the
  project's generator with the main root and the worktree's hooks dir. The worktree venv imports the worktree's
  `src`:
  `python -m claude_code_hooks_daemon.install.forwarder_generator --project-root /workspace --hooks-dir .claude/hooks`.
  The two configs are identical, so the transport config is the same. It rewrote 27 forwarders, and no
  worktree path is baked. The test passes (3 passed). **Nothing needs regenerating on main after the merge**,
  so the first handoff's step 6 is resolved: the tracked forwarders already carry the new guard with
  `/workspace` roots.
- I had no SendMessage tool, so the "529 checkpoint" message was not sent. It is in this report and in the
  reply.

## Step 1 of the handoff: the marker reaches the daemon (commit `6368aded7`)

- `init.sh` captures `HOOKS_DAEMON_RELAY_UNUSED` into `_HOOKS_DAEMON_RELAY_UNUSED` and unsets it, beside
  `_HOOKS_DAEMON_RELAY_FAILED`.
- The nc rung is skipped while it is set. `send_request_stdin` passes it as the python rung's `sys.argv[6]`, and
  the envelope gets `relay_unused` only when the value is non-empty.
- `RequestEnvelopeField.RELAY_UNUSED = "relay_unused"` is in `constants/protocol.py`, pinned to the init.sh
  literal by a test.
- Test: `tests/integration/test_relay_unused_marker_reaches_daemon.py`. It covers missing, corrupt ELF, and text
  garbage that would print a forged `{}`. Each runs the real init.sh against `_RecordingSocketServer`, with nc
  ENABLED and a live answering nc socket. It asserts exit 0, a verdict byte-equal to the bash path's, the
  envelope field naming the binary, and nc never used. Two more tests check that no socket sends no marker, and
  that a child never sees the variable.

Red, before init.sh changed:

```
E       KeyError: 'relay_unused'            (x3: missing, corrupt-elf, text-garbage)
E       AssertionError: _: line 1: _HOOKS_DAEMON_RELAY_UNUSED: unbound variable
4 failed, 1 passed
```

The first draft's nc assertion was vacuous, because the forwarder gets the nc socket arg only with
`nc_enabled`. Once nc was enabled, I removed the skip temporarily to prove the assertion bites:

```
E  {'hookSpecificOutput': {'additionalContext': 'via-nc', ...}} != {... 'permissionDecisionReason': 'bash path verdict'}}
3 failed, 3 passed
```

Green: 6 passed. Neighbouring suites `test_relay_guard_fail_open.py` and
`test_init_sh_pretooluse_fail_closed.py`: 211 passed, 56 skipped (no relay build).

## Step 3 of the handoff: one defect check, and `transport on` repairs (commit `1cc5a8d7b`)

- `relay_deploy.relay_binary_defect(path) -> str | None` mirrors the guard exactly. The binary must exist, be a
  regular file, be executable and be readable. Its first 4 bytes must be `\x7fELF`, or start with `#!`. A file
  of fewer than 4 bytes fails, because the guard's `read -N 4` fails on it.
- Reasons are the `RELAY_DEFECT_*` constants, and `RELAY_RUNNABLE_MAGIC` is pinned against the generated guard
  text.
- `missing_configured_relay_binary` uses it, which covers the SessionStart checker, `status` and the installer.
  So does `ensure_relay_binary`, which means **`transport on` now re-provisions over a corrupt binary**. The
  null-`relay_source` failure names the defect.
- The warning reads "missing or cannot run". The checker's acceptance pattern and docstrings were updated.
- Three fixtures used a 1-byte `x` as a "working" binary. They now use an ELF header, since the guard never
  runs `x`. Those are `test_relay_deploy.py::test_enabled_without_source_but_binary_present_is_provisioned`,
  `test_cli_status_event_listeners.py` and `test_cli_status_relay_binary_warning.py::test_present_binary_is_silent`.

Red:

```
E   route: None != 'build'                                  [replaces_a_binary_that_cannot_run]
E   assert None is not None  (RelayProvision().failure)     [null_source_names_the_defect]
2 failed, 4 passed
```

Green: install, checker and CLI relay/status tests, 485 passed.

## QA

**There is no `llm_qa.py changed` result yet.** The run is started and writes to
`untracked/scratch/qa-529.txt` in the worktree. When this report was written, it was queued on the host-wide QA
lock behind another worktree's run (pid 365338, `worktree-issue-130-p3-dbf`), 20 minutes into its 60-minute
wait. Read its `QA:` line there; if the wait expired, re-run it.

The targeted pytest runs that did finish are listed under each step above, and `black --check src tests` is
clean.

## Handoff: what is left

1. **Daemon warning line (handoff step 2).** `DaemonController.process_request` (`daemon/controller.py`, near
   the `request_data.get("event")` at about line 1349).
   - When `request_data.get(RequestEnvelopeField.RELAY_UNUSED)` is set and the event is relay-eligible
     (`EventIDMeta.relay_eligible`), deep-copy `result.result` and `add_context("WARNING: " + relay_binary_missing_warning(Path(v), daemon_cli_command("transport", "on")))`
     before `to_json`. Leave the decision untouched.
   - Tests: the field adds the line; no field adds nothing; the decision is identical for allow, deny and ask; an
     ineligible event is unchanged.
   - Then extend the integration test in `test_relay_unused_marker_reaches_daemon.py` only if a real daemon is
     cheap. Otherwise the unit tests are the proof.
2. **Detached session-start repair (handoff step 4).**
   - Model it on `install/background_sync.py`. Key a state file by binary path plus the
     `relay_binary_defect` reason plus the daemon version, so each cause is tried once; take a lock.
   - The child runs `ensure_relay_binary` plus `regenerate_deployed_hooks`. Start it detached from
     `relay_binary_checker` when the predicate fires.
   - Inject `run_fn`/`fetch_fn`/spawn in tests.
   - Warning text: "repair started in the background; if the next session still warns, run `transport on`".
3. **Docs and release note (handoff step 5).**
   - `CLAUDE/Worktree.md:108-121` and the transport docs: "a missing or broken relay never changes a verdict;
     every answer says so until `transport on`".
   - Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/019-...md`. Main holds up to 018, and 017 is pending
     elsewhere. Re-check main before committing.
   - PLAN.md Task 2c status. Tick the second Success Criterion once steps 1 to 3 are merged.
4. Re-run the brief's `llm_qa.py changed` after these steps, and report the bench numbers. The first report
   measured the guard at about 52 us and zero spawns. No step here touches the healthy relay path.
