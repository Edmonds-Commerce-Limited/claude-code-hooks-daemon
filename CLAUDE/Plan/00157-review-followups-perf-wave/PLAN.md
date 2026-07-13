# Plan 00157: review followups perf wave

**Status**: Not Started
**Created**: 2026-07-13
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The v3.38.0 release (performance-tuning wave, Plans 00154-00156) passed all
blocking release gates, but the Step 10 Code Review Gate and Step 11 CLAUDE.md
Guidance Audit surfaced non-blocking nits. Per the "reviews must not lose value"
rule, those findings are captured here as MUST-FIX-SOON items rather than
discarded as tech debt. They were deliberately NOT fixed during the release
because doing so mid-gate would have forced a full FAIL-FAST restart of the QA
and acceptance suites for cosmetic changes.

This plan closes the loop: it fixes the review nits immediately after the
v3.38.0 release ships, and records a process-ordering improvement for the
release cycle (review + fix should happen EARLY, before the QA/acceptance gates,
so findings can be fixed without destabilising an in-flight release).

## Goals

- Fix every non-blocking finding from the v3.38.0 code-review and guidance-audit
  gates so none becomes lingering tech debt.
- Record a concrete release-cycle ordering improvement (move review + fix earlier
  than Step 10) for RELEASING.md.

## Non-Goals

- No new features or performance work — this is cleanup of already-shipped code.
- No change to the shipped v3.38.0 runtime behaviour beyond the cosmetic/dead-code
  fixes listed below.

## Tasks

### Phase 1: Fix code-review nits

- [ ] ⬜ **Task 1.1**: Remove the dead `pgrep` line in
  `scripts/install/daemon_control.sh` (~line 36). It is now-unreachable dead
  code flagged by the release code review. Verify nothing depends on it, delete
  it, run shellcheck + shell_audit QA.
- [ ] ⬜ **Task 1.2**: Correct the cosmetically-inaccurate reason string in
  `init.sh`'s `emit_hook_error` for the near-impossible malformed-Stop-payload
  case, so the emitted `reason` accurately describes that specific branch.
  Add/extend a test in `tests/integration/test_emit_hook_error_jqless.py` or
  `test_forwarder_jq_free.py` pinning the corrected string.
- [ ] ⬜ **Task 1.3**: Review the two directory-bounded caches (the
  `git_branch.py` status-line render cache and the `validation.py` memoisation).
  They match existing project patterns, so decide per-cache: either add an
  explicit bound/eviction, or document why the directory-bounded growth is
  acceptable. No silent unbounded growth left undocumented.

### Phase 2: Guidance-audit follow-up

- [ ] ⬜ **Task 2.1**: The 8 advisory PreToolUse handlers that return `None` from
  `get_claude_md()` but inject guidance inline via `context=`/`guidance=` are a
  defensible pre-existing pattern (no blocking gap). Confirm this is intentional
  and, if worth it, add a one-line comment on each so a future audit does not
  re-flag them. Low priority.

### Phase 3: Release-cycle process improvement

- [ ] ⬜ **Task 3.1**: Propose moving the Code Review Gate + fix loop EARLIER in
  the release pipeline (before the QA Verification and Acceptance Testing gates),
  so review findings can be fixed without triggering a FAIL-FAST restart of the
  downstream gates. Capture the rationale and, if agreed, update
  `CLAUDE/development/RELEASING.md` step ordering.

## Success Criteria

- [ ] All Phase 1 code-review nits are fixed (or explicitly documented as
  accepted) with QA green and the daemon restarting RUNNING.
- [ ] Phase 2 confirmed/annotated.
- [ ] Phase 3 ordering improvement proposed (and RELEASING.md updated if agreed).

## Notes & Updates

### 2026-07-13

- Plan scaffolded to capture v3.38.0 release-review findings so no review value
  is lost (per user directive: "either fix now or fix soon; must not lose value
  from reviews").
- Source findings:
  - **Code Review Gate (Step 10)** — APPROVE, no blocking issues; 3 nits:
    dead `pgrep` line in `scripts/install/daemon_control.sh:36`; cosmetic
    reason string for the malformed-Stop-payload case in `init.sh`; two
    directory-bounded caches consistent with existing patterns.
  - **CLAUDE.md Guidance Audit (Step 11)** — PASS, no missing/inaccurate
    guidance; 8 advisory handlers return `None` but inject guidance inline
    (defensible pre-existing pattern).
- Decision: fix immediately AFTER v3.38.0 ships to close the loop without
  destabilising the in-flight release.
