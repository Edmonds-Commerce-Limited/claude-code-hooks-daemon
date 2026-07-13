# Plan 00157: review followups perf wave

**Status**: Complete
**Created**: 2026-07-13
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The v3.38.0 release (performance-tuning wave, Plans 00154-00156) passed all
blocking release gates, but the Step 10 Code Review Gate and Step 11 CLAUDE.md
Guidance Audit surfaced non-blocking nits. Per the "reviews must not lose value"
rule, those findings were captured here as MUST-FIX-SOON items rather than
discarded as tech debt. They were deliberately NOT fixed during the release
because doing so mid-gate would have forced a full FAIL-FAST restart of the QA
and acceptance suites for cosmetic changes.

This plan closed the loop: it fixed the review nits immediately after the
v3.38.0 release shipped, and recorded a process-ordering improvement for the
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

- [x] ✅ **Task 1.1**: Remove the dead `pgrep` line in
  `scripts/install/daemon_control.sh`. The hyphenated `claude-hooks-daemon`
  pattern can no longer match the real daemon (which runs as the underscore
  module path `python -m claude_code_hooks_daemon...`) since the console-script
  entry was removed in v3.38.0; only the underscore `pgrep` detects it. Removed
  the dead line + updated the comment; `test_daemon_control_pgrep_portability.py`
  still passes (3/3).
- [x] ✅ **Task 1.2**: Correct the inaccurate reason string in `init.sh`'s
  `emit_hook_error`/`emit_error_json` for the malformed-Stop-payload case. The
  Stop/SubagentStop branch now branches on `error_type`: `invalid_hook_input`
  reports a malformed-payload reason ("daemon likely healthy; do not restart")
  instead of "daemon not running", still failing CLOSED (`decision: block`).
  RED→GREEN via new `test_malformed_payload_stop_reason_is_accurate` (4 params).
- [x] ✅ **Task 1.3**: Reviewed the two directory-bounded caches
  (`git_branch.py` render/per-repo dicts, `validation.py` repo-detection memo).
  Decision: KEEP as-is — key space is the small set of distinct project
  dirs/cwds a single daemon serves, both clear on restart, and they match
  existing patterns; an LRU bound would be premature (YAGNI). Documented the
  accepted trade-off in a comment on `git_branch.py`'s render cache.

### Phase 2: Guidance-audit follow-up

- [x] ✅ **Task 2.1**: Confirmed the 8 advisory PreToolUse handlers that return
  `None` from `get_claude_md()` but inject guidance inline via
  `context=`/`guidance=` are an intentional, defensible pre-existing pattern
  with no blocking gap (per the Step 11 audit). Resolution: accept as-is; no
  code churn across 8 handlers warranted. Recorded here rather than annotating
  each file.

### Phase 3: Release-cycle process improvement

- [x] ✅ **Task 3.1**: Added a "Review Early, Never Drop Findings" section to
  `CLAUDE/development/RELEASING.md` capturing (1) the recommendation to run the
  code review + guidance audit before the QA/acceptance gates so fixes don't
  trigger a downstream FAIL-FAST re-run, and (2) the non-negotiable rule that
  every review finding is either fixed pre-ship or captured as a tracked
  follow-up plan and fixed immediately after — never dropped into scrollback.

## Success Criteria

- [x] All Phase 1 code-review nits are fixed (or explicitly documented as
  accepted) with QA green and the daemon restarting RUNNING.
- [x] Phase 2 confirmed/annotated.
- [x] Phase 3 ordering improvement proposed (RELEASING.md updated).

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
- Decision: fixed immediately AFTER v3.38.0 shipped to close the loop without
  destabilising the release.
- Delivered on branch `fix/plan-00157-review-followups`: init.sh reason-string
  fix + RED→GREEN test, daemon_control.sh dead-line removal, git_branch.py
  cache-bound documentation, RELEASING.md review-ordering section. QA 13/13
  (9841 tests, coverage 95.6%); daemon restart RUNNING. Delivery commit hash(es)
  recorded on merge to main.
