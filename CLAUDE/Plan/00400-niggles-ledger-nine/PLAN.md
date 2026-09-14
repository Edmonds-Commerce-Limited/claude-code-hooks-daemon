# Plan 00400: niggles ledger nine

**Status**: In Progress
**Created**: 2026-09-14
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The open niggles ledger. Small defects get recorded here the turn they are
found, so that noticing something and doing something about it are never the
same decision. Ledger eight ([Plan 00397](../Completed/00397-niggles-ledger-eight/PLAN.md))
is complete, so this one opens.

An entry is either fixed in place, ruled NOT A DEFECT with the evidence that
settles it, or graduated to its own plan when the fix turns out to be a ruling
rather than an edit.

## Goals

- Every niggle found is written down with the evidence that makes it checkable
  by someone who was not there.
- Each entry reaches a terminal state: fixed, ruled not-a-defect, or graduated.

## Non-Goals

- Fixing anything that needs an owner ruling — that graduates to its own plan.

## Tasks

### Phase 1: Entries

- [x] ✅ **N1**: The QA suite writes into the LIVE supervisor runtime directory.

  **Found**: while reading `untracked/supervise/decision.log` as forensic
  evidence for [Plan 00398](../Completed/00398-critical-compaction-blocked-by-the-idle-gate/PLAN.md).

  **Evidence.** Test-authored lines interleave with live supervisor decisions in
  the live log:

  ```text
  2026-09-14T09:44:47 supervisor active (dry-run (injects marker)); polling /workspace/untracked/context-sidecar every 2.0s; wrapping: ['echo', 'SUPERVISED_OK']
  2026-09-14T09:48:10 noop: session busy (composing) [red]
  2026-09-14T09:51:41 would-compact: red at 43% + idle -> would inject /compact
  ```

  `wrapping: ['echo', 'SUPERVISED_OK']` is a test fixture, not this session.
  Separately, the live sidecar directory holds a test-authored sidecar:

  ```json
  {"session_id": "socket-stdin-test", "window_size": 0, "pct": 0.0, "writer_pid": 345, "seq": 45277}
  ```

  It shares `writer_pid` and the `seq` counter with this session's real sidecar
  (`seq: 45318`), so the **daemon** minted it: a test opened the daemon socket
  with `session_id: "socket-stdin-test"` and the daemon wrote a sidecar for it
  into the live directory.

  **Impact is diagnostic, NOT behavioural — established, not assumed.** The
  decision path is protected by Plan 00166's own-session filter: `_scan_sidecars`
  skips any sidecar whose `session_id` is not in the learned set, the set is
  built by scanning `/proc` environs for `CLAUDE_CODE_SESSION_ID`, and it fails
  safe (empty set ⇒ act on nothing). `socket-stdin-test` can never be learned
  because no process in this container carries that id. Both live call sites
  (`claude-supervise.py:6021`, `:6708`) do pass `own_sessions=cached_own_session_ids()`
  — checked at the call sites, not inferred from the comment.

  So the cost is that the live `decision.log` is the primary forensic record for
  supervisor behaviour, and it is contaminated by test output. This session
  measured tick populations from that file; those particular counts survive
  because the test lines have a distinct shape, but that is luck rather than
  isolation.

  **RESOLVED — and the two halves turned out to have different answers.**

  **The sidecar half is NOT A DEFECT.** `tests/integration/test_forwarder_socket_stdin.py`
  runs the DEPLOYED forwarder against the LIVE daemon on purpose — that is
  precisely what it tests (the transport when stdin is a socket). The sidecar is
  the daemon correctly serving a genuine request. It is inert for decisions
  (Plan 00166's own-session filter) and `reap_stale_sidecars` removes it after
  its TTL, so it self-heals. Isolating that test would mean not testing the
  thing it exists to test.

  **The decision-log half WAS a defect, now FIXED.**
  `test_cli.py::TestSystemPythonRuntime` runs the real supervisor script as a
  subprocess, so unlike the in-process tests it cannot pass `--log`. With no
  isolated `CLAUDE_PROJECT_DIR` it inherited the developer's, and
  `_resolve_decision_log(None)` resolved to the LIVE
  `untracked/supervise/decision.log`.

  **Measured scale**: the live log already held **1,132** `SUPERVISED_OK`
  lines — this had happened 1,132 times, interleaved with genuine supervisor
  decisions in the file used as primary forensic evidence for Plan 00398.

  **Fix**: an `_isolated_env` helper redirecting `CLAUDE_PROJECT_DIR` into
  `tmp_path` for every subprocess in that class, which isolates the whole
  untracked tree. Proven by measurement rather than asserted: the live log held
  1,132 such lines before the run and 1,132 after. Added
  `test_supervising_writes_no_log_outside_the_isolated_project_dir`, which
  asserts the log lands under `tmp_path` — the isolation is load-bearing, so it
  is checked rather than trusted.

- [x] ✅ **N2**: FIXED — a test whose result depended on the time of day, red on
  `main` and not noticed.

  **Found**: checking CI after pushing Plan 00398, which surfaced that the
  PREVIOUS commit on `main` (`c1f2ee82`) had already failed CI — across all
  three Python versions — and nobody had looked.

  **The failure**: `test_plan_qa_edit.py::TestHandleJournal::test_pure_append_is_silent`
  asserts a pure journal append produces no advisory. It appends an entry
  stamped `## 10:00` to a day-file named for TODAY, and leaves the clock free:

  ```text
  E  assert not ["Plan QA drift report:\n- [advise] journal-entry-future-dated ..."]
  ```

  CI ran at **09:24 UTC**, so `10:00` had not arrived yet and
  `journal-entry-future-dated` fired — correctly. My own full QA run passed the
  same test because it ran nearer 10:00. **The handler is right; the test was
  wrong**, and it fails any run starting more than 30 minutes (the check's
  tolerance) before 10:00 — roughly the first 40% of each day.

  **Why it survived**: the `_journal_file` helper already dodged one time-bomb
  by generating TODAY's date rather than hardcoding one, and its comment says
  so. Fixing the date dependence while leaving the TIME fixed swapped a bomb
  that fires once for one that fires daily, on a schedule nobody was watching.

  **Fix**: `journal_entry_future_dated._now` exists precisely so tests can pin
  it ("isolated so tests can pin it") and no test did. An autouse fixture on
  `TestHandleJournal` pins it to 23:59 today — late enough that every fixed
  entry time is in the past, while keeping the day-file name valid for
  `journal-dayfile-naming`, which accepts only today/yesterday. Added
  `test_future_dated_entry_advises_regardless_of_run_time`, which pins 09:24
  deliberately and asserts the finding DOES fire, so the behaviour CI caught by
  accident is now asserted on purpose.

- [x] ✅ **N3**: FIXED (comment) / NOT A DEFECT (behaviour) — `qa.yml` asserted a
  per-sha guarantee the config does not provide, and kept asserting it after the
  claim had already been corrected in the plan that introduced it.

  **Found**: checking CI before archiving Plan 00398, whose implementation
  commit turned out to have no CI evidence at all.

  **The claim, in `.github/workflows/qa.yml`**:

  ```yaml
  cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}
  # ... With this false, a later push QUEUES behind the
  # running job rather than killing it, so every sha on main gets a result.
  ```

  **The counter-example, observed live**:

  ```text
  09:56:49  e495227b  starts RUNNING
  10:00:53  ec18062d  created -> PENDING
  10:05:13  8867803e  created -> ec18062d CANCELLED, jobs: 0
  ```

  `gh run view 34830966652` reports `conclusion: cancelled`, `jobs: 0` — it
  never started.

  **Mechanism**: `cancel-in-progress: false` protects the run that is ALREADY
  RUNNING. GitHub permits only ONE pending run per concurrency group, so a newer
  arrival evicts the older pending one. A sha pushed while another run is in
  progress, and superseded before it starts, gets no result whatsoever. The
  guarantee holds for two concurrent pushes and fails from the third onward —
  which is why it reads as correct and survived review.

  **Why it matters, not merely tidy**: Plan 00359's release-slate gate requires
  HEAD's EXACT sha to be CI-green, and plan completion criteria cite specific
  commits. `ec18062d` is Plan 00398's implementation commit; citing it as
  delivery evidence would cite a run that does not exist.

  **CORRECTION — I presented this as needing an owner ruling between three
  options. It did not: the behaviour was ALREADY RULED.**
  [Plan 00393](../Completed/00393-niggles-ledger-seven/PLAN.md) N2 observed the
  identical eviction (`268cbc77` and `57d6b435` both cancelled while pending,
  `a64dca90` surviving three pushes), corrected the "every sha gets a result"
  claim in place, and judged it explicitly:

  > The PRODUCT behaviour is fine — Plan 00359's gate needs HEAD's exact sha
  > green, HEAD is always the newest pending run, and that one executes.
  > Intermediate commits lacking CI is ordinary.

  **Verified against this session's own runs rather than taken on trust** —
  every cancellation was followed by the next sha running:

  ```text
  ec18062d  cancelled  ->  8867803e  ran
  a06bd799  cancelled  ->  764d7c2f  ran
                           a7d0fb7b  success
  ```

  HEAD always gets a run. The release-slate gate is therefore never starved, and
  a plan that wants delivery evidence cites a later green sha containing the
  work — which is exactly what Plan 00398 did.

  **So the behaviour is NOT A DEFECT, and what actually survived was narrower**:
  a documentation-SSoT failure. Plan 00393 corrected the claim in its PLAN.md but
  never corrected `qa.yml`, so the artefact a reader actually sees kept asserting
  the falsehood. The truth lived in a closed plan while the lie lived in the
  config.

  **FIXED**: the comment now states what the config does — `false` protects the
  RUNNING run only, one pending run per group, the property holds for two
  concurrent pushes and breaks from the third on — and says to cite a later
  green sha that contains the work.

  **The pattern, recorded because this is its second appearance.** Plan 00393's
  journal named it: "I stated a result one step beyond what I had observed."
  Here I observed one sha with no run and claimed a live defect needing a
  ruling, without checking whether it had already been ruled. The check that
  would have caught it — grep the claim's own wording before filing — costs one
  command.

## Success Criteria

- [ ] Every entry above reaches a terminal state (fixed / not-a-defect /
  graduated) with its evidence recorded.
- [ ] Any fix made here is covered by a test that fails against today's code.
- [ ] Full QA passes and CI is green.
- [ ] The plan is archived into the holding area (`Completed/`) with the README
  row and statistics updated in the same commit.

## Delivery & Milestones

- Opened when N1 was found while investigating Plan 00398.
