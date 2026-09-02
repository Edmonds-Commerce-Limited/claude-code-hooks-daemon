# Plan 00317 — python-developer report

## Summary

All four tasks (1.1, 2.1, 2.2, 2.3, 3.1) complete. Audit produced 10
classified host-tier responsibilities; only typed-command recognition was
moved worker-side. Ctrl+C gate audited and confirmed to stay host-side (byte-
level swallow must act before forwarding) — documented, no code change
needed there beyond the audit itself. QA is 25/25 with no suppressions.

## What changed

- `.claude/ccy/claude-supervise.py`:
  - New `RawInputTap` class (bounded, fail-open byte buffer).
  - `TickFacts.human_raw_input: str = ""` (base64), round-tripped in
    `_facts_to_json`/`_facts_from_json`.
  - `_forward_io` gained an optional `raw_tap` param, fed the same forwarded
    bytes as `activity.record`.
  - `run_worker` now owns a persistent `HumanInputLine` recognizer, fed each
    tick's raw input, and OVERRIDES the host-sent
    `human_compact_submitted`/`human_model_command`/`human_effort_command`/
    `input_line_empty` before calling `decide_once` — this is what makes
    recognition hot-reloadable.
  - `supervise()` wires a `RawInputTap`, drains it each tick into the
    `TickFacts` sent to the worker.
  - Module docstring gained a "HOST-TIER SURFACE" section naming what
    remains host-side and why.
- `.claude/ccy/CLAUDE.md`: added a note that typed-command recognition now
  hot-reloads with the worker (Plan 00317), pointing at `AUDIT.md`.
- `CLAUDE/Plan/00317-supervisor-host-thin-shim/AUDIT.md` (new): the full
  classification table.
- Tests: `tests/unit/supervise/test_raw_input_tap.py` (new — tap bounds,
  fail-open forwarding), additions to `tests/unit/supervise/test_policy_worker.py`
  (worker-side recognition across split ticks, JSON roundtrip for the new
  field, and the Task 2.3 mid-session-reload proof test).

## Verification

- `tests/unit/supervise/` : 624 passed (618 pre-existing tests pass
  UNCHANGED; 6 new).
- `ruff check` / `mypy` on the edited file: clean.
- Full QA (`python3 scripts/qa/llm_qa.py all`): **25/25 PASSED**, 17256
  tests passed / 0 failed, 95.2% coverage, no suppressions added. (One run
  had to wait for a concurrent teammate's `llm_qa.py tests` run to release
  the lock — handled correctly, no contended verdict trusted.)

## Not done / deferred to the owner

Live dogfood verification against the actually-running `ccy` supervisor for
this session was NOT performed (the currently-running worker predates this
edit). A four-step checklist is journalled at the bottom of
`CLAUDE/Plan/00317-supervisor-host-thin-shim/JOURNAL/00317-Journal-26-09-02.md`
for the next session (or later in this one): verify the worker pid changed,
confirm existing `/model`/`/effort` recognition is unaffected, then make a
throwaway recognition-code edit and prove via a `ps` check that only the
worker restarts and the new behaviour appears — the actual end-to-end proof
of this plan's claim, beyond what the unit tests can show in-process.

## Contentious points to flag

None from the audit — every "must stay" classification had what I judge to
be a hard, defensible reason (see `AUDIT.md`), and the one out-of-scope
finding (`_is_idle`/`_is_work_idle` threshold comparisons) is minor and
explicitly left alone as not in this plan's Goals. Not committing per
instructions — leaving that to the coordinator.
