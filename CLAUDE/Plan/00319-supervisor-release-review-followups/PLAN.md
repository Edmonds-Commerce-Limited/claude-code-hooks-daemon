# Plan 00319: supervisor release review followups

**Status**: In Progress (all ten supervisor findings closed; the five acceptance-run observations are in flight in a worktree)
**Created**: 2026-09-02
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The v3.60.0 release's Step 10 code-review gate returned 13 findings against
the supervisor and status-line work shipped by Plans 00316, 00317 and 00318.
Three were BLOCKING and were fixed before the release shipped (commit
`55dd5b2e`). The remaining ten are non-blocking: none of them makes the
release unsound, but RELEASING.md's "never drop a finding" rule requires every
surviving finding to be captured as a tracked MUST-FIX item rather than left
in a review transcript that nobody reads again. This plan is that tracked
capture.

The findings cluster into three themes. **Unbounded growth**: several
per-session artefacts (the worker error log, the `manual-model-changes/`
marker directory, a second `MtimeCachedFile` entry set) accumulate with no
reaper, which is the same shape of defect the project has already fixed
elsewhere. **Silent failure**: a marker write with no error guard, a decision
log line dropped on a branch collision, and a typed command lost across a
worker restart with no diagnostic trace — each is invisible when it happens,
which is exactly what makes it expensive to diagnose later. **Contract drift**:
a writer and a reader disagreeing on how a session id is stemmed, an audit
banner that bypasses the poster's own lock and rate limit, and mutable state
on a router-shared handler instance. One finding (F2) sits outside those three:
`budget_exhaustion_detector` still self-triggers on its own ledger, which is
the same self-reference gap Phase 4 records from the acceptance run.

Each finding below is self-contained: it names the file, what is wrong, and
why it matters. They can be fixed independently and in any order, so this plan
is a good candidate for parallel sub-agent execution once someone has decided
which of them are worth the change.

## Goals

- Every one of the ten surviving v3.60.0 review findings is either fixed with
  a TDD regression test, or explicitly closed as won't-fix with the reason
  recorded in this plan.
- No finding is closed by assertion alone: a fix lands with a test that fails
  against the current code.
- The unbounded-growth findings (F4, F5, F7) are fixed or bounded, because
  they degrade a long-lived session rather than failing once.

## Non-Goals

- Re-opening the three BLOCKING findings already fixed in `55dd5b2e`
  (`_MANUAL_MARKER_WINDOW_SECONDS` drift, the `input_line_empty` override,
  and raw-vs-canonical `/model` argument comparison). Those shipped.
- Redesigning the supervisor's two-tier host/worker split. Plan 00317 settled
  that boundary; these are defects within it, not arguments against it.
- Any change to the status-line banner's user-visible design. Plan 00318's
  countdown banner is confirmed working live.

## Tasks

### Phase 1: Silent-failure findings

- [x] ✅ **Task 1.1 (F1)** — already fixed: Plan 00328 (`4c0998336`)
  deleted `write_manual_model_marker` and its call site outright; there is
  no unguarded write left. Original text: `write_manual_model_marker` is called in the tick
  path (`.claude/ccy/claude-supervise.py`) without an error guard — it is
  the only unguarded write there. Every other write in that path reports
  its outcome. A failure here silently loses the manual-model marker, and
  the symptom surfaces much later as a false "downgraded" status
  indicator. Give it the same observable write outcome the failsafe-cron
  marker got in Plan 00314.
- [x] ✅ **Task 1.2 (F3)** — fixed at `422014c1`
  (`test_audit_banner.py::TestAuditFlushSurvivesAStandingAuthInjection`).
  Original text: the audit flush's `decision.log` line is dropped
  when the standing-authorisation branch injects on the same tick. The
  audit trail is the documented source of truth for what the supervisor
  did (see `CLAUDE/UPGRADES/truth-changes/v3.60.0.yaml`), so a tick that
  silently writes no line makes it an incomplete record.
- [x] ✅ **Task 1.3 (F8)** — fixed at `422014c1`: the drop now leaves a
  trace (`test_policy_worker.py`). Original text: a worker restart mid-line drops a typed
  `/compact` / `/model` with no diagnostic trace. The recognizer's buffer
  is reset by the reload, so a partially-typed command vanishes. Dropping
  it may be the right behaviour; doing so invisibly is not — emit a trace
  so the next person debugging "my /model did nothing" can see it.
- [x] ✅ **Task 1.4 (F2)** — fixed at `e63134d4` together with Task 4.5;
  the ledger's own record shape is stripped before matching and
  `"matched_fragment"` joined the marker list as belt and braces. Original
  text: `budget_exhaustion_detector` still self-feeds on
  its own ledger whenever the command does not spell the filename. Both
  guards key on the literal strings `budget-exhaustion-events.jsonl` and
  `budget_exhaustion_detector`, and a ledger LINE contains neither — so
  `cat untracked/*.jsonl`, `jq . untracked/budget*.jsonl` or
  `tail -n 20 "$LEDGER"` re-fire the detector on its own recorded
  `matched_fragment`, append a fresh entry, and inject a spurious advisory
  telling the agent to alarm the user about a budget that was never hit.
  Advisory-only and the ledger is capped, so this is noise rather than
  damage — but the brief's "must never self-trigger on its own ledger"
  requirement is not met. Add the ledger's unique JSON key
  `"matched_fragment"` to `_SELF_REFERENTIAL_RESPONSE_MARKERS`; a genuine
  harness budget message will never contain it. Same handler and same
  self-reference gap as Task 4.5 — fix them together.

### Phase 2: Unbounded-growth findings

- [x] ✅ **Task 2.1 (F4)** — fixed at `422014c1`: capped, and the human's
  typed lines are no longer recorded (`test_worker_error_safety_net.py`).
  Original text: `claude-supervise-worker.err.log` is uncapped and
  logs every submitted `/`-line verbatim. Two problems, one file: it grows
  without limit in a long session, and it records what the human typed.
  Cap it (rotate or truncate) and decide deliberately what belongs in it.
- [x] ✅ **Task 2.2 (F5)** — already fixed: the marker directory was
  deleted with F1's writer in Plan 00328. Original text: `manual-model-changes/` markers are never reaped.
  Each manual `/model` leaves a file behind and nothing removes it.
- [x] ✅ **Task 2.3 (F7)** — fixed at `0eab945a` with the existing bound
  shape (`test_paths_stale_cleanup.py`, `test_mtime_cache.py`). Original
  text: a second unbounded per-session `MtimeCachedFile`
  entry set was added without a bound. The project has already fixed this
  exact shape once; apply the same bound.

### Phase 3: Contract-drift findings

- [x] ✅ **Task 3.1 (F6)** — already fixed: the writer/reader pair was the
  Plan 00328-deleted mechanism, and no other supervisor-writer /
  daemon-`safe_session_stem`-reader pair exists. Original text: the marker
  writer uses the raw `session_id` while
  the daemon reads via `safe_session_stem()`. They agree today only
  because real session ids happen to be stem-safe. A session id that is
  not makes the marker unreadable — a silent miss, not an error. Use the
  same stemming on both sides.

- [x] ✅ **Task 3.2 (F9)**: fixed — but NOT by either remedy the finding
  offered, and the reason matters more than the fix.

  **"Route it through the poster" cannot work.** `StatusMessagePoster`
  serialises with a `threading.Lock` and rate-limits on an instance attribute,
  both of which are PROCESS-LOCAL. The two writers are in different processes:
  the audit banner is written by `decide_once` inside the `--worker`
  subprocess, while every keystroke notice is written by the PTY host. Giving
  the worker its own poster would rate-limit the worker against itself and
  would not touch the host/worker clobber the finding actually names.

  **"State why the bypass is correct" is also wrong**, because it is not
  correct — the clobber is real, and Plan 00355 made it materially more likely
  by giving all ~122 escapes per session a banner each.

  **What does arbitrate across processes is the message file itself.** Every
  host notice posts at WARNING (Ctrl+C, Ctrl+Z, Ctrl+`\`, DROP ANCHOR) and the
  audit banner is the only INFO writer, so the precedence rule is exact and
  needs no new state: an INFO write does not replace a WARNING that has not yet
  expired. `_live_warning_present` reads the file, and fails OPEN — an absent,
  unreadable or unparseable message is treated as no warning, so corrupt state
  cannot wedge the channel shut until an unreadable TTL elapses.

  The read-then-write is not atomic across processes, so a race can still
  clobber. That is worth stating plainly rather than hiding: losing the race
  reproduces exactly today's behaviour, so the change is strictly an
  improvement and introduces no new failure mode.

  **A suppressed banner no longer DISCARDS its audit.** The flush previously
  cleared the pending items unconditionally, which was defensible when a failed
  write was exceptional; with suppression now routine it would silently lose
  notices. Items are retained for the next tick — which is also what lets a
  stack accumulate into Plan 00355's `esc (20)` rather than vanishing one at a
  time. `arm_audit` caps the list, so this cannot grow without bound.

  Covered by `TestAnInfoMessageYieldsToALiveWarning` (6 tests) and
  `test_a_yielded_banner_keeps_its_items_for_the_next_tick`.

- [x] ✅ **Task 3.3 (F10)** — fixed at `02d48f2b`, merged over the Task 4.5
  redesign at `5ad0d539`: the fragment is re-derived from the event in both
  `matches()` and `handle()`, nothing per-event lives on the instance.
  Original text: `_cached_fragment` is mutable state on a
  router-shared handler instance. Handlers are shared across events, so
  per-event state on the instance leaks between events.

### Phase 4: Non-blocking observations from the v3.60.0 acceptance run

4.1 to 4.4 and 4.6 fixed with tests in one worktree pass (`079904fb`,
`c5daeda1`, `cbe66c39`, `ab5fb4d5`), merged at `1c00aced`. 4.6 is the
substantial one: `AcceptanceTest` gained a structured `hook_input` payload,
and `tests/integration/test_acceptance_contract.py` drives every BLOCKING
acceptance test's declared input through a real handler and asserts each
declared pattern matches the reason produced — 170 of 170 covered, with no
ratchet allowlist, so a handler declaring a pattern its deny text cannot
produce now fails CI rather than a release gate.

- [x] ✅ **Task 4.1**: `bin/hooks-daemon secret-meta <path> | head -20` is
  DENIED by `pipe_blocker`, while the unpiped command passes. The
  `secret-meta` helper is the documented alternative offered by the
  secret-file guard's own deny message, so having it blocked when piped
  is a sharp edge in the recommended recovery path. Decide whether
  `secret-meta` belongs in `pipe_blocker`'s whitelist.

- [x] ✅ **Task 4.2**: acceptance Tests 66 and 67 share one disclosure budget
  and therefore cannot both pass as declared. `sensitive_content` emits its
  verbose rationale once per transcript; Test 66 spends it, so Test 67 —
  which declares the verbose-only pattern `deliberately not shown` —
  necessarily sees the terse form. The handler is right and the tests are
  individually right; they just cannot both hold in one transcript. Either
  drop the verbose-only pattern from whichever test runs second, or give
  the pair distinct transcript paths. Test 67's substantive contract (deny,
  cite only an index, leak neither the term nor the raw command line) was
  met in full during the v3.60.0 run.

- [x] ✅ **Task 4.3**: `pipe_blocker` labels the producer of
  `python -m pytest ... | tail` as "python is expensive", while the
  project's own CLAUDE.md states it "names `pytest` as its producer,
  because `-m` there means module". The REMEDIATION it prints does name
  the real module (that is what Plan 00222 fixed) — only the label
  disagrees. Cosmetic, but it made an acceptance runner report a false
  FAIL, so either the label or the doc sentence should move.

- [x] ✅ **Task 4.4**: `Type: CLI Feature` tests carry no
  `Requires Main Thread` field, so a runner that routes by that field —
  which is exactly what RELEASING.md Step 12.4 instructs — silently drops
  them into neither the delegable batches nor the main-thread set. Three
  tests (274, 275, 276) went unexecuted in two consecutive v3.60.0
  acceptance passes before a count reconciliation caught it. Playbook
  SKIP-marked tests (25, 26, 139, 141) also lack the field, but they are
  explicitly resolved and so are harmless. Either emit the routing field
  for every executable test, or have `generate-playbook` state the routing
  rule for `CLI Feature` explicitly. The silent-drop shape is the defect:
  a dropped test is indistinguishable from a passing one in the totals.

- [x] ✅ **Task 4.5** — designed and fixed at `e63134d4`, design in
  `BUDGET-DETECTOR-DESIGN.md`: a delivered message is distinguished from
  quoted text STRUCTURALLY — sub-agent dispatch responses are composed prose
  and are excluded, a Bash response whose every pipeline stage is a
  content-passthrough verb (`cat`, `grep`, `jq`, `tail`, ...) can only
  reproduce bytes already on disk and is excluded, and the handler's own
  ledger records are stripped before matching. Genuine delivered messages
  keep firing (46 tests). Original text: `budget_exhaustion_detector` fires on the release
  gate's own machinery. During the v3.60.0 run it triggered twice on text
  that merely QUOTED its Test 187 fixture: once on `grep` output from the
  generated playbook, once on a sub-agent dispatch prompt that cited the
  fixture string. Both are working-as-designed — the guard keys on two
  literal markers (the handler name, its ledger filename) and neither
  quotation carried one, and the CHANGELOG says plainly that prose
  discussing budget exhaustion without naming the detector is still
  matched. But the handler's advisory demands a prominent user-facing
  banner, so every false fire spends a real banner on a non-event and
  trains the reader to discount the next one.

  **Owner ruling (asked during the v3.60.0 gate): do this properly — a
  robust, clean solution, explicitly not a quick workaround.** Two options
  were put to the owner and are therefore REJECTED: leaving it as won't-fix,
  and smuggling one of the guard's literal markers into the Test 187 fixture
  string so the gate's own quotations self-exclude. The second is a
  workaround precisely because it fixes the symptom at one known quotation
  site while leaving every other quotation of a budget message —
  documentation, a bug report, a transcript excerpt — still false-firing.

  So this is a DESIGN task before it is a code task. The real question is
  how the detector distinguishes a budget message the harness is DELIVERING
  to this agent now from one that merely APPEARS as text in something the
  agent read. The current marker list is a proxy for that distinction and is
  too narrow to carry it. Whatever is designed must not be a keyword
  blocklist grown one string at a time, and must not weaken detection of a
  genuine exhaustion message — that remains the failure that actually costs
  the user something. Write the approach down and get it agreed before
  implementing.

- [x] ✅ **Task 4.6**: FOUR handlers were found declaring acceptance patterns
  their own deny reasons cannot produce — `quarantine_artefact_read_guard`
  and `sensitive_content` (stale `RuleFormatter`-era headers),
  `sed_blocker` (declares "forbidden", a word that appears only in
  `get_claude_md()` and in neither the verbose nor the terse block), and
  `write_clobber_guard` (declares "would destroy a file you have not read",
  which appears nowhere). All four were fixed during the v3.60.0 release,
  but they were found ONE AT A TIME, each costing a FAIL-FAST cycle, and
  each looked like a release blocker until inspected. That is the signal
  that a systemic check is missing.

  ```
  A static check was attempted during the release and is NOT good enough
  to ship: patterns are matched against the deny text, which is assembled
  at runtime from the `Rule` fields, the `RuleFormatter` header and
  handler-appended literals, so checking a pattern against handler source
  alone produced 87 candidates that were overwhelmingly false positives.
  The only reliable oracle is EXECUTING the handler, which is exactly what
  the acceptance gate does — too late, and only for handlers whose test
  happens to run.

  Design the real thing: a CI-time contract test that, for each handler,
  drives it with the input its own acceptance test describes and asserts
  every declared pattern matches the reason produced. The obstacle is that
  `AcceptanceTest.command` is prose, not an executable payload, so the
  test cannot currently synthesise the input. Solving that — a structured
  payload alongside the prose, or a per-handler fixture — is the actual
  unit of work here. Do NOT settle for a heuristic scanner.
  ```

## Success Criteria

- [x] All sixteen items (F1 through F10 and the six Phase 4 acceptance-run
  observations) are closed — each either fixed with a
  regression test that fails against the pre-fix code, or marked won't-fix
  with a recorded reason (merged at `5ad0d539` and `1c00aced`).
- [ ] `./scripts/qa/llm_qa.py all` passes 25/25 after the changes.
- [x] For any supervisor change: the worker hot-reload is verified by pid, per
  the contract in the global `CLAUDE.md` — a `ps` check showing a NEW
  `--worker` pid before any behaviour is tested (pid 683611 after `5ad0d539`).
- [x] Every release-bound consequence is in the pending-release holding area:
  `UNRELEASED/release-notes/11-supervisor-review-followups-closed.md`.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00319-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Findings captured from the v3.60.0 Step 10 review gate; the three BLOCKING
  siblings shipped separately in `55dd5b2e`.
