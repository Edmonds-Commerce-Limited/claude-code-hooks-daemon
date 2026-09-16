# Task 1.2 — SessionStart action-tier mechanism

**Agent**: Sonnet 5, in worktree `worktree-00416-tier-mechanism`
**Branch**: `worktree-00416-tier-mechanism` (not merged to main, per instructions)

## What was built

1. **`src/claude_code_hooks_daemon/core/session_start_tiers.py`** (new module)
   `SessionTier` enum (`ACTION_REQUIRED` / `ACTION_SUGGESTED` / `INFO`),
   `SessionStartVerifiable` mixin (optional, gives a validated `declared_tier`
   restricted to the two declarable tiers plus a `verify_still_needed()`
   override point), `has_verifier()`, `compute_tier()`, and
   `prefix_context_with_tier()`.

   `compute_tier()` is the enforcement point: `ACTION_REQUIRED` iff a
   verifier exists (duck-typed check, not `isinstance`) AND
   `verify_still_needed()` returns `True`. A raising verifier is caught and
   logged, degrading to the declared tier — never propagates, never hides
   other handlers. A tampered `declared_tier` attribute (bypassing the
   mixin's constructor guard) is clamped back to `INFO` rather than trusted,
   so the anti-inflation guarantee holds "however it is configured", not
   just through the one blessed constructor path.

2. **`HandlerChain.context_transform`** (chain.py) — a new, fully generic
   optional hook applied to each matched handler's own context lines right
   after `handle()` returns, before they flatten into the merged response.
   This is the only point in dispatch where a context line is still paired
   with its producing handler. `chain.py` itself knows nothing about
   "SessionStart" or tiers.

3. **`EventRouter`** wires `session_start_tiers.prefix_context_with_tier` in
   for `SessionStart` only (`_SESSION_TIER_EVENTS`, mirroring the existing
   `_ALLOW_IS_FINAL_EVENTS` pattern). Every SessionStart advisory line is now
   tagged `[ACTION_REQUIRED]` / `[ACTION_SUGGESTED]` / `[INFO]` — including
   INFO, deliberately: the must-do set stands out by contrast against the
   tagged majority, not by being the only tagged item. Asserted directly
   that every other event's chain has `context_transform is None`.

4. **`bin/hooks-daemon session-actions`** (`--json` supported) — lists
   exactly the currently-`ACTION_REQUIRED` SessionStart items, discovered via
   the registry the same way `status-line-explained` walks status-line
   handlers (no running daemon required). A handler that fails to
   instantiate or is disabled by config is silently excluded rather than
   reported as an error.

## Design constraint respected, not re-opened

`test_handler_bases.py::test_the_known_assignments_hold` asserts
`handler_base_for_event("SessionStart") is AdvisoryHandler` by object
identity — `SessionStartHandlerBase` is a bare alias shared with SessionEnd,
Notification, Status, both worktree events, etc. That ruled out making a new
subclassed `SessionStartHandlerBase` carry the verifier interface: it would
either break that identity or require every SessionStart handler to be
reparented. Instead the verifier check in `has_verifier`/`compute_tier` is
duck-typed on the method itself, not gated on inheriting
`SessionStartVerifiable`. Consequence: Task 2.1/2.2 can add
`verify_still_needed()` to an existing shipped handler directly, with no
reparenting, and the CLI test proves this by monkeypatching two real shipped
handler classes (`project_handler_load_checker`,
`docs_qa_sweep`) rather than only a synthetic fixture.

## TDD

Every slice was red-first: test file written and run to a real collection/
assertion failure before the source file existed or the behaviour was wired.
Representative RED output (full transcripts were captured per-slice, not
retained beyond the session):

```
ModuleNotFoundError: No module named 'claude_code_hooks_daemon.core.session_start_tiers'
...
TypeError: HandlerChain.__init__() got an unexpected keyword argument 'context_transform'
...
assert None is not None
 +  where None = <HandlerChain>.context_transform
...
ImportError: cannot import name 'cmd_session_actions' from 'claude_code_hooks_daemon.daemon.cli'
```

## Required test cases — all present and passing

- `tests/unit/core/test_session_start_tiers.py::TestAntiInflationGuarantee` —
  no verifier (absent method, mixed-in-but-not-overridden, and a
  directly-tampered `declared_tier` attribute) can never produce
  `ACTION_REQUIRED`, asserted directly across every `SessionTier` value.
- `TestVerifierDrivesTheTier` — passing verifier != REQUIRED; failing
  verifier == REQUIRED; duck-typed (non-mixin) verifier recognised too.
- `TestVerifierDegradesSafely` — a raising verifier does not propagate, falls
  back to the declared tier, and is logged.
- `tests/unit/daemon/test_cli_session_actions.py` — `session-actions` lists
  exactly the failing-verifier item and nothing else (baseline against this
  repo's real 25 handlers is an empty list, since none has a verifier yet —
  Task 2.1/2.2's job); a raising verifier on one real handler does not hide
  a genuine `ACTION_REQUIRED` item on another real handler.
- `tests/unit/core/test_chain_session_start_tiers.py` /
  `test_router_session_start_tiers.py` — the render-into-the-block wiring,
  and proof every non-SessionStart chain is untouched.

## QA

`./scripts/qa/llm_qa.py all` in this worktree, `QA_EXIT=$?` read
immediately after on its own line, as instructed:

First full run (before two fixes below): `QA: 26/30 PASSED, 4/30 FAILED`.
Two of the four were real, both introduced by this slice:

- `magic_values`: bare `priority=50` in a test fixture — fixed to
  `Priority.DEFAULT`.
- `error_hiding` (`log-and-continue` in `_collect_session_action_entries`):
  fixed by adding a documented exclusion entry in
  `scripts/qa/error_hiding_exclusions.json`, identical shape and
  justification to the pre-existing entry for
  `_collect_status_line_segment_entries` immediately above it in the same
  file (both degrade an unreadable/invalid `hooks-daemon.yaml` to
  `event_config={}` rather than failing the whole command).

The other two were **not** from this slice and were left alone:
`docs_qa`'s 2 advisory (not block) findings are pre-existing dead links in
Plan 00413's `NIGGLES.md` pointing at `DESIGN-cron-enforcement.md`
(unrelated ledger housekeeping). The 11 `tests` failures in that first run
(`test_playbook_harness.py`, `test_stop_hook_hard_block.py`,
`test_tool_use_error_recovery.py`, plus
`test_audit_error_hiding.py::test_repo_is_clean_under_widened_scope`, which
*was* mine) were resource-contention flakes from four sibling worktrees on
this host running full coverage suites concurrently — every one of them
passed when re-run in isolation, and the `test_audit_error_hiding` one also
cleared once the exclusion above was added.

Re-run after both fixes:

```
QA_EXIT=1   (magic_values error_hiding docs_qa subset — docs_qa's
             pre-existing advisory findings are the only remainder)
✅ magic_values: 0 violations
✅ error_hiding: 0 violations
❌ docs_qa: 2 findings (0 block, 2 advise)   <- pre-existing, unrelated
```

Full test suite re-run separately (`./scripts/qa/llm_qa.py tests`, run
in background — the same command the plan asks for, just isolated to
confirm the flakes were contention, not a regression):

```
QA_EXIT=0
✅ tests: 23766 passed, 0 failed, 22 skipped | coverage: 95.3%
```

Daemon restart verified: `./bin/hooks-daemon restart` → `Daemon started successfully`, `./bin/hooks-daemon status` → `31/31` event listeners active.

## Boundaries respected

- No verifier was implemented for `persistent_cron_assertor`; Stop/
  SubagentStop untouched.
- None of the 25 shipped SessionStart handlers were reclassified — the
  mechanism is proven against synthetic fixtures plus two real handler
  classes monkeypatched in tests, never given a permanent verifier.
- SessionStart still cannot block: `AdvisoryResult`/`AdvisoryHandler` and
  the whole decision-tier machinery from `core/result_types.py` /
  `core/handler_bases.py` are untouched.

## Files changed

- `src/claude_code_hooks_daemon/core/session_start_tiers.py` (new)
- `src/claude_code_hooks_daemon/core/chain.py`
- `src/claude_code_hooks_daemon/core/router.py`
- `src/claude_code_hooks_daemon/daemon/cli.py`
- `scripts/qa/error_hiding_exclusions.json`
- `tests/unit/core/test_session_start_tiers.py` (new)
- `tests/unit/core/test_chain_session_start_tiers.py` (new)
- `tests/unit/core/test_router_session_start_tiers.py` (new)
- `tests/unit/daemon/test_cli_session_actions.py` (new)

No disagreement with the owner's Option B design to report — it held up
cleanly through implementation. The one real constraint it collided with
(the `SessionStartHandlerBase is AdvisoryHandler` identity) was resolved
without touching that identity, by making the verifier interface duck-typed
rather than inheritance-gated; noted above because it is the reason a
future handler does not need reparenting onto a new base to grow a
verifier.
