# Plan 00371: qa acceptance probes detect a stale daemon

**Status**: In Progress
**Created**: 2026-09-10
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

`./scripts/qa/llm_qa.py all` on `main` reported one failure —
`tests/acceptance/test_playbook_harness.py::TestTheDeclaredProbesBehaveAsDeclared::test_every_executable_probe_matches_its_expected_decision_and_reason`,
probe #116 `SelfMatchingProcessProbeHandler` denied for a reason that did not
match the expected patterns. The handler code on disk was correct; the
**running daemon still had pre-merge code loaded**, because the acceptance
harness dispatches every probe through the live daemon socket rather than
through in-process handler code. `bin/hooks-daemon restart` made the same
test pass with no code change. The harness silently grades the *deployed*
daemon while claiming to grade the working tree.

Both directions of this are dogfooding defects and both must be fixed:

1. **False failure** (what happened): code is right, the daemon is stale, QA
   fails and a human hunts a bug that does not exist.
2. **False pass** (the dangerous one): the working tree is broken, but a
   stale daemon still answers with the old, correct code, so the probes pass
   and a release gate waves a real regression through. This is the same
   class of failure `daemon_restart_verifier` exists to advise against at
   commit time — this plan closes the same gap at *QA-run* time, where
   nothing currently looks.

The fix is a **content fingerprint of the code a running daemon actually
loaded**, computed once at daemon startup from the package directory the
running interpreter imported (`Path(__file__).parent` inside the daemon's own
package — correct in both self-install and client-install layouts, because it
names wherever `import claude_code_hooks_daemon` actually resolved) plus the
project's `.claude/project-handlers/` tree (auto-discovered and loaded at the
same startup, so a change there is exactly as "stale" as a change to the
daemon's own source). The daemon exposes this fingerprint over its existing
`_system`/`health` socket action. Every acceptance test that dispatches
through the live daemon socket — four files were found doing this, each with
an independently copy-pasted socket-discovery block — computes the same
fingerprint fresh from the current working tree and compares it to what the
daemon reported, **failing loudly, by name**, on a mismatch, before any
probe-specific assertion can produce a confusing symptom instead. A new
`bin/hooks-daemon check-source-fresh` CLI verb reuses the identical
comparison so `scripts/qa/run_smoke_test.sh` — which already claims in its
own header comment to catch "the #1 dogfooding failure mode: daemon running
stale code" via 3 fixed behavioural probes, and provably does not (none of
the 3 covers probe #116's handler) — gets the same general-purpose check.

**Design decision: detect-and-fail, not auto-restart.** QA stays read-only:
it must never mutate a developer's (or an agent's) live environment as a
side effect of grading it, and — self-referentially — the daemon a QA run
inside *this* repository would be restarting is very often the same daemon
currently gating the live agent session running that QA, so an auto-restart
risks disrupting hook dispatch for in-flight tool calls mid-run. A detected
mismatch fails with the exact remediation (`bin/hooks-daemon restart`) named
in the failure message, matching the existing convention for a QA failure
report (e.g. `R-LINT-FAILURE`: "the write has already landed; this is a
failure report, not a rollback") rather than inventing a new
auto-remediating pattern.

## Goals

- A running daemon exposes a content fingerprint of the code it actually
  loaded at startup (its own package directory + the project's
  `.claude/project-handlers/`), over the existing `_system`/`health` socket
  action.
- Every acceptance test that dispatches through the live daemon socket
  detects a mismatch between that fingerprint and the current on-disk source,
  and fails with a named, actionable reason — never silently passing a stale
  daemon's answer off as a verdict on the working tree.
- The same comparison is reachable as a `bin/hooks-daemon check-source-fresh`
  CLI verb, and `scripts/qa/run_smoke_test.sh` uses it as a pre-check so the
  smoke test's own "catches daemon running stale code" claim becomes true in
  general, not only for the 3 probes it happens to hand-check.
- The socket-discovery helpers duplicated verbatim across 4 acceptance test
  files are centralised once in `tests/acceptance/conftest.py`, which is also
  where the fingerprint check is added — so the fix lands in one place
  covering all four dispatch sites, not four copy-pasted checks.
- A regression test reproducing the exact reported shape: a genuine live
  daemon whose reported fingerprint is compared against a deliberately wrong
  "current" value must fail with a message naming the mismatch.

## Non-Goals

- Auto-restarting the daemon from within a QA run (see Design decision
  above) — a human or agent restarts it, following the failure message.
- Detecting *config* drift (`.claude/hooks-daemon.yaml` changes without a
  restart) — this plan's fingerprint covers loaded **code** only (the daemon
  package's `.py` files and `.claude/project-handlers/`'s `.py` files), which
  is what silently produced the reported false failure. Config-only staleness
  is a different, already-advised-at-commit-time concern
  (`daemon_restart_verifier`) and is out of scope here.
- Changing `daemon_restart_verifier` itself (Plan 00370 owns its
  project-handler migration).

## Tasks

### Phase 1: source fingerprint capability

- [x] ✅ **Task 1.1**: New module
  `src/claude_code_hooks_daemon/daemon/source_fingerprint.py`:
  `daemon_package_root()`, `compute_source_fingerprint(*roots)`,
  `compute_daemon_identity_fingerprint(project_root)`,
  `describe_fingerprint_mismatch(running, current) -> str | None`. Unit tests
  first (`tests/unit/daemon/test_source_fingerprint.py`): deterministic
  across call order/iteration, sensitive to a single byte changing, sensitive
  to a file rename, tolerant of a missing `project-handlers/` dir, and the
  three `describe_fingerprint_mismatch` cases (match / mismatch / no running
  fingerprint).
- [x] ✅ **Task 1.2**: `DaemonController` computes
  `self._source_fingerprint` once in `initialise()` (best-effort: `OSError`
  during hashing logs and leaves it `None`, matching the existing
  `_sync_agent_assets` fail-open convention — never fatal to daemon startup)
  and reports it as a new `source_fingerprint` key from `get_health()`. Unit
  tests in `tests/unit/daemon/test_controller.py` first.

### Phase 2: expose + CLI verb

- [x] ✅ **Task 2.1**: `bin/hooks-daemon check-source-fresh` — resolves the
  project's socket, sends a `_system`/`health` request, compares against
  `compute_daemon_identity_fingerprint`, prints the verdict, exits 0 fresh /
  1 stale-or-unreachable. Unit tests in `tests/unit/daemon/test_cli.py`
  first (mock `send_daemon_request`).

### Phase 3: wire the acceptance harness

- [x] ✅ **Task 3.1**: Centralise `_socket_is_alive` / `_discover_socket` (byte-
  identical across `test_playbook_harness.py`, `test_absolute_path_socket_deny.py`,
  `test_stop_hook_hard_block.py`, `test_tool_use_error_recovery.py`) into
  `tests/acceptance/conftest.py`, add `assert_daemon_source_fresh(socket_path)`
  there, and fold it into shared `daemon_running`/`daemon_socket` fixtures
  (both names are already used, unchanged, across the 4 files) so removing
  each file's local copy is the only per-file change.
- [x] ✅ **Task 3.2**: Regression test proving detection actually fires:
  query the real running daemon's reported fingerprint over the socket, feed
  it to `describe_fingerprint_mismatch` against a deliberately wrong "current"
  value, assert the named-mismatch message. A companion test asserts the
  positive path — the running daemon's fingerprint equals
  `compute_daemon_identity_fingerprint(REPO_ROOT)` right now — which is the
  literal regression reproduction: it fails today (before Task 3.1 lands) if
  run against a deliberately-stale daemon, and passes once the daemon is
  fresh.

### Phase 4: smoke test parity

- [x] ✅ **Task 4.1**: `scripts/qa/run_smoke_test.sh` calls
  `bin/hooks-daemon check-source-fresh` before its 3 behavioural probes;
  a non-zero result writes the same JSON failure shape the script already
  uses for "daemon not running", naming staleness instead.

### Phase 5: docs + QA

- [ ] ⬜ **Task 5.1**: Release-notes callout under
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/` (next free number).
- [ ] ⬜ **Task 5.2**: `./scripts/qa/llm_qa.py all` green in the worktree
  (daemon restarted first); pyright clean on every file this plan touches.

## Success Criteria

- [x] A daemon started from code at commit A, then queried after the working
  tree changes to commit B with no restart, reports a `source_fingerprint`
  that no longer equals `compute_daemon_identity_fingerprint` computed
  against B. (Verified live: appended a comment to `controller.py` without
  restarting, `check-source-fresh` reported STALE DAEMON naming both
  fingerprints.)
- [x] `tests/acceptance/test_playbook_harness.py` (and the 3 other live-socket
  acceptance files) fail with a named "stale daemon" reason, not a
  probe-specific symptom, when the running daemon predates the working
  tree. (Verified live: every test in the stale module failed with the
  named reason, not a probe-specific symptom.)
- [x] `bin/hooks-daemon check-source-fresh` exits 0 against a freshly
  restarted daemon and 1 against a deliberately stale one.
- [x] `scripts/qa/run_smoke_test.sh` fails fast, by name, on a stale daemon
  instead of only on the 3 probes it happens to hand-check. (Verified live.)
- [ ] Full QA green in the worktree after a daemon restart; new files
  pyright-clean.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00371-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
