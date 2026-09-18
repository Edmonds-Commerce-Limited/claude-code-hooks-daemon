# Plan 00445: acceptance harness honours the socket override

**Status**: Complete
**Created**: 2026-09-18
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

When the natural socket path exceeds the AF_UNIX limit, the daemon falls back
to `/tmp` and prints "Set `CLAUDE_HOOKS_SOCKET_PATH` to override". Following
that instruction fixes every surface except the test suite, and the suite does
not report the override as ignored — it hangs.

`tests/conftest.py`'s `isolate_daemon_path_overrides` is `autouse=True` and
`delenv`s `CLAUDE_HOOKS_SOCKET_PATH` for every test. That fixture is right and
stays: an ambient override makes path tests assert against a path they never
chose, which reads as CI flake because it depends on who is running it. Its
docstring already names the consequence — "the unset is inherited by every
subprocess a test spawns" — and that consequence is the defect.
`tests/acceptance/test_playbook_harness.py` dispatches each probe by spawning
the PRODUCTION wrapper, which resolves the socket itself, finds nothing live at
the default path, and lets `ensure_daemon` spend `DAEMON_STARTUP_TIMEOUT` (150
deciseconds) per probe. No event is ever sent. Across 224 executable probes
that is about an hour of silence.

Measured for ledger 00422 N6: a worktree whose socket path FITS runs the five
harness cases in 13.91s against `main`'s 14.3s; the same worktree with an
override pointed at another short path hangs. The full diagnosis, its three
controls and the two remedies below are in that ledger's N14-adjacent N6 entry.

## Goals

- The acceptance suites that dispatch through the production wrapper reach the
  daemon the fixtures ALREADY resolved, whatever the ambient environment.
- A probe that cannot reach a daemon fails fast and says so, instead of buying
  a daemon-start timeout per probe.

## Non-Goals

- No change to `isolate_daemon_path_overrides`. Weakening it to fix one suite
  would re-expose the path tests it exists for.
- Not fault 1. The socket-path preflight and the skip reason already shipped
  (Plans 00431, 00443); this is the second fault behind them.
- No change to any handler or to what a probe asserts. The verdicts are correct
  today when the harness can reach the daemon at all.

## Tasks

### Phase 1: the harness reaches the daemon it resolved

- [x] ✅ **Task 1.1**: RED — a test that fails while the bug is present.
  `tests/acceptance/test_wrapper_subprocess_env.py`, observed failing on
  `ImportError: cannot import name 'wrapper_subprocess_env'` before the fix.
  It carries its own control: `test_plain_inheritance_does_not_carry_it`
  pins the defect, so the file cannot pass by the leak it exists to replace.
- [x] ✅ **Task 1.2**: `tests/acceptance/conftest.py` exposes the socket path
  it already resolves for its skip logic as `wrapper_subprocess_env()`, a
  COPY of `os.environ` plus the override — never a mutation of it, which
  would put back for every later test exactly what the isolation fixture
  removes.
- [x] ✅ **Task 1.3**: Repointed `test_playbook_harness.py` (`_dispatch` and
  `_run_probe` now take the env) and `test_stop_hook_hard_block.py`
  (`_invoke_hook` takes the socket; its three tests moved from
  `daemon_running` to `daemon_socket`).
  `test_tool_use_error_recovery.py` needed NO change: it never spawns a
  wrapper, it calls the socket directly with a path it is already handed.
  N6 listed it only because it errored in the same run, which is a different
  fact from sharing the cause.

### Phase 2: an unreachable daemon fails fast

- [x] ✅ **Task 2.1**: The FIRST unreachable dispatch now aborts the loop,
  naming the socket the fixtures resolved and passed. `wrapper_unreachable_reason`
  reads the wrapper's OWN stderr channel (`HOOKS DAEMON ERROR [type]: detail`)
  rather than its stdout payload, where the same text lands in `systemMessage`
  and is indistinguishable from a handler advisory.
  This deliberately inverts the loop's batching rule: probe mismatches are
  collected because their shape side by side is the diagnosis, whereas an
  unreachable daemon repeated 224 times adds nothing to the first — and each
  repetition costs a `DAEMON_STARTUP_TIMEOUT`. Five unit tests, including a
  control that ordinary stderr is not read as unreachability.

### Phase 3: gate

- [x] ✅ **Task 3.1**: `llm_qa format`, README index row and statistics, then
  `llm_qa.py all` green with the daemon restarted after the last `src/`
  edit — 35/35.
- [x] ✅ **Task 3.2**: Record the outcome on Plan 00422's N6 entry; archive.

## Success Criteria

- [x] The RED test of Task 1.1 was observed failing before the fix and passes
  after it. Task 2.1's helper was RED first too, on the same shape.
- [x] The playbook harness completes in seconds with `CLAUDE_HOOKS_SOCKET_PATH`
  exported to a non-default path, having previously hung — the measurement that
  closes fault 2. Verified in a throwaway worktree at the delivery commit:
  **12 passed in 14.75s**, against a run killed at 480s before the fix.
- [x] `llm_qa.py all` green — 35/35.
- [x] This plan has no release-bound consequences: everything shipped is this
  repository's own acceptance suite plus one helper it calls. No handler, no
  config key, no wrapper and no installed artefact changes, so a client upgrade
  sees nothing — the same reasoning Plan 00443 recorded for its skip reason.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00445-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Phase 1 delivered at `c4eeebdf` — the dispatchers name their daemon.
- Phase 2 and the archive ship in the following commit: the first unreachable
  dispatch now aborts the loop instead of buying 224 daemon-start timeouts.
- Fault 2 closed by measurement, not by argument: **12 passed in 14.75s** in a
  throwaway worktree under the override, against a pre-fix run killed at 480s.
