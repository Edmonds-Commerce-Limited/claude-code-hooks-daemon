# Plan 00529 Task 2c: implementation report (PARTIAL: ruling task 1 done, tasks 2 to 6 handed off)

Branch `worktree-529-relay-loud-fallthrough`. Delivered: commit `cfb39206c`, the safety core (ruling task 1 plus
its tests). I stopped there because this agent passed its context budget. The remaining tasks are in the
**Handoff** section below, with enough detail for a fresh agent to finish them.

## The facts, verified in `untracked/scratch/529c` before any code was written

The coordinator's fact-check is right on both points. The ruling's task 1 as written would not have closed the
hole.

| Binary at the path                   | Old guard under `set -euo pipefail`                                   |
| ------------------------------------ | --------------------------------------------------------------------- |
| corrupt ELF (`\x7fELF` then garbage) | exit 1, empty stdout                                                  |
| text with no shebang                 | **bash runs the file as a shell script** (ENOEXEC fallback), exit 127 |
| `\x7fEL` (3 bytes)                   | runs as a script, exit 127                                            |
| missing                              | silent fall-through, nothing records it                               |

- `shopt -s execfail` does nothing under `set -e`. `bash -c 'set -e; shopt -s execfail; if ! exec ./elf; then echo branch; fi'` exits 1, so a failed exec ends the script even inside an `if` condition. The same line
  without `-e` reaches `branch`.
- `execfail` also leaves the ENOEXEC behaviour alone. With it on, the text file still runs as a script.
- `set +e; exec ...; set -e` with execfail on: the shell survives, `$?` is 126 for a corrupt ELF and 127 for a
  missing file, and a later `false` still exits, so errexit is restored.

## Design (commit `cfb39206c`)

`build_relay_guard_block` (`src/claude_code_hooks_daemon/install/forwarder_generator.py`). The order of the
checks is unchanged: the `--no-relay` and `BASH_SOURCE` checks come first, so worktree copies are still inert.
After them:

```bash
    if [[ -S "$_rl_sock" ]]; then
        _rl_magic=""
        if [[ -x "$_rl_bin" && -f "$_rl_bin" ]] \
            && read -r -N 4 _rl_magic < "$_rl_bin" \
            && [[ "$_rl_magic" == $'\x7fELF' || "$_rl_magic" == '#!'* ]]; then
            _rl_opts="$-"
            shopt -s execfail
            set +e
            HOOKS_DAEMON_RELAY_DAEMON_ROOT="..." \
                exec "$_rl_bin" "$_rl_sock" --fallback "${BASH_SOURCE[0]}" \
                --timeout-ms "30000"
            shopt -u execfail
            if [[ "$_rl_opts" == *e* ]]; then set -e; fi
        fi
        HOOKS_DAEMON_RELAY_UNUSED="$_rl_bin"
    fi
```

- **Magic check: decided yes.** The guard execs only what the kernel's own `execve` runs: an ELF file (the musl
  relay) or a `#!` script. The `#!` case is needed because the test suite's stub relays are scripts, and the
  kernel, not bash, executes them. Anything else would reach bash's ENOEXEC fallback and run as shell. That is
  arbitrary code from a corrupt download, and it can print a forged `{}` allow. The check is the `read` builtin
  on 4 bytes: no fork, no subshell. A file that fails the check or cannot be read falls through to the marker.
- **No error hiding.** There is no `|| true` and no stderr redirect. A failed exec is a named branch: control
  reaches the marker assignment, and bash's own "cannot execute" line still goes to stderr. Errexit is lifted
  only around the exec, then restored from `$-`. It is not forced on, in case a forwarder ever runs without
  `-e`.
- **No socket means no marker.** The bash path below is the start-up path and reports loudly itself. This is the
  ruling's legitimate `-S` half.
- **Marker.** The marker is a plain shell variable, not exported. The constant is `RELAY_UNUSED_ENV` in
  `forwarder_generator.py`. Stdin is still unread when the guard falls through.

### Not covered (residual)

An ELF file with a valid header but corruption deeper in passes the magic check. The exec then either succeeds or
fails with ENOEXEC; the second case is handled. A relay that execs and then crashes is the relay's mid-exchange
contract, not this guard's. The ruling's task 7 is out of scope as instructed.

## Red output (before the guard change, constant only), `untracked/scratch/red-guard.txt`

```
E  assert 'MARKER=/tmp/.../bin/hooks-relay\n' in 'MARKER=<unset>\nSTDIN={"tool_name":"Bash",...}\nERREXIT=e\n'   [missing]
E  AssertionError: assert 'RAN-AS-A-SCRIPT' not in 'RAN-AS-A-SCRIPT\n'                                            [text-garbage]
E  assert 1 == 0   (... bin/hooks-relay: Success)                                                                  [corrupt-elf]
E  assert 1 == 0                                                                                                   [empty]
E  assert 127 == 0 (... line 1: $'\177EL': command not found)                                                      [short]
E  assert 'MARKER=...' in 'MARKER=<unset>...'                                                                      [non-executable]
8 failed, 2 passed
```

Green: `tests/unit/install/test_relay_guard_loud_fallthrough.py`, `test_forwarder_generator.py`,
`tests/integration/test_relay_guard_fail_open.py` and `test_relay_guard_foreign_checkout.py` all pass (56 skips
need a built relay under `untracked/relay-build/`, which this worktree does not have). One existing pin changed:
the daemon-root indentation in `test_guard_block_hands_the_relay_its_daemon_root`. The tests assert "exit 0 and
the marker, stdin whole", never a failing exit code. They cover a corrupt ELF, text garbage, a broken shebang,
empty and short files, a non-executable file, no socket, and a worktree copy.

## Bench (healthy path)

No in-tree bench runs without a live daemon and the built relay. The nearest are
`CLAUDE/Plan/Completed/00290-rust-socket-relay-forwarder/assets/bench_relay_forwarder.sh` and
`Completed/00154-.../assets/bench_forwarder.sh`. I measured the guard's added work directly, in a bash loop of
20,000 iterations against the real 672 KB relay:

- old check (`-x` only): 0.144 s, about 7 us per call;
- new check (`-x -f`, the `read` of 4 bytes, the magic test, and the option save and restore): 1.178 s, about
  59 us per call.

That adds **about 52 us per call and zero spawns**: one `open` and one `read` syscall. Against the 4.3 to 5.6 ms
of client CPU per relay call (task-3 report), that is about 1%. The coordinator should still run
`bench_relay_forwarder.sh` on main after merge for the end-to-end number.

## QA

Targeted pytest only (above). The brief's `llm_qa.py changed` run has **not** been made yet. It belongs to the
handoff agent, after steps 2 to 6.

## Handoff: what is left (ruling tasks 2 to 6)

1. **init.sh** (root `init.sh`; `.claude/init.sh` is a symlink to it).
   - Beside lines 113-119, capture the marker with `_HOOKS_DAEMON_RELAY_UNUSED="${HOOKS_DAEMON_RELAY_UNUSED:-}"; unset HOOKS_DAEMON_RELAY_UNUSED`. It is a shell variable, but the unset still matters because
     `start_daemon` must never see it.
   - Skip the nc rung when it is set: add `-z "$_HOOKS_DAEMON_RELAY_UNUSED"` to the condition at about line 2980.
     The nc rung sends a raw payload to the per-event socket, with no envelope to carry the field.
   - Pass it to the python transport as a new argv (`sys.argv[6]`, after `HOOKS_DAEMON_ROOT_DIR` at about
     line 3644), and add it to the envelope at about line 3540 as `{'event', 'hook_input', '<field>': path}`.
     Only add the field when it is non-empty.
   - Integration test, modelled on `test_binary_missing_falls_through_to_legacy_path` in
     `tests/integration/test_relay_guard_fail_open.py`. Bind a listening `pre-tool-use.sock` in a short events dir
     through `HOOKS_DAEMON_EVENTS_DIR`. Put each of missing, corrupt ELF and text garbage at the binary path. Run
     the real init.sh against `_RecordingSocketServer`. Assert exit 0, stdout equal to the canned verdict (the
     same verdict as the bash path), and an envelope field naming the binary.
2. **Daemon.**
   - Add an envelope-field constant, for example `RequestEnvelopeField.RELAY_UNUSED = "relay_unused"`, in
     `constants/protocol.py`. Pin it equal to the init.sh literal with a test, as `_CHAIN_DEADLINE_DEFAULT_SECONDS`
     is pinned.
   - In `DaemonController.process_request` (`daemon/controller.py:1321`), after `process_event`: when
     `request_data` carries the field and the event is relay-eligible (`EventIDMeta.relay_eligible`), deep-copy
     `result.result` and `add_context("WARNING: " + relay_binary_missing_warning(Path(v), daemon_cli_command("transport", "on")))` before `to_json`. `to_json` already shapes context per event. The
     decision stays untouched. `HookEvent` ignores extra keys (pydantic default), so validation is unaffected.
   - Tests: the field adds the line; no field adds nothing; the decision is identical for allow, deny and ask; an
     ineligible event (Status, WorktreeCreate) is unchanged.
3. **The warning text and the repair predicate.** `relay_binary_missing_warning` says "missing or not executable",
   which is wrong for a corrupt file. `missing_configured_relay_binary` and `ensure_relay_binary`
   (`transport_toggle.py:330`) both treat any executable file as fine. **`transport on` therefore does NOT
   repair a corrupt binary today**, and the fix command the warning names would be a no-op. Add one predicate
   in `relay_deploy.py` (for example `relay_binary_defect(path) -> str | None`: missing, not a file, not
   executable, no ELF or `#!` magic). Use it in both places so that `ensure_relay_binary` re-provisions over a
   defective file. Reword the warning to "missing or cannot run". Update the pins in
   `tests/unit/install/test_relay_deploy.py:455-490` and the acceptance pattern in `relay_binary_checker.py`.
4. **Session-start repair**, modelled on `install/background_sync.py`. A state file is keyed by binary path plus
   daemon version, so a failed build is tried once per cause; a lock stops concurrent builds. Start it detached
   from `relay_binary_checker` when the predicate fires: `ensure_relay_binary` plus `regenerate_deployed_hooks`,
   which is `transport on` without the toggle. Inject `run_fn`/`fetch_fn` in its tests. The SessionStart warning
   then reads "repair started in the background; if the next session still warns, run `transport on`".
5. **Docs and release note.**
   - `CLAUDE/Worktree.md:108-121` and the transport docs: "a missing or broken relay never changes a verdict;
     every answer says so until `transport on`".
   - The release note goes in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`, numbered above 018, after checking
     main.
   - PLAN.md: mark Task 2c, and tick the second Success Criterion once steps 1 to 3 are merged.
6. **Regenerate the deployed forwarders on main after merge**, not in this worktree:
   `regenerate_deployed_hooks` bakes the checkout root, and a worktree would bake its own path. `transport on`, or
   the generator's `main` run from `/workspace`, does it. Until then `/workspace/.claude/hooks/*` carry the old
   guard.
