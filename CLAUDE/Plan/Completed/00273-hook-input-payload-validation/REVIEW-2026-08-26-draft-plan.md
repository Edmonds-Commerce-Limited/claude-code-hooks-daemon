# Plan 00273 Draft Review — 2026-08-26

Pre-execution plan-quality review by a dispatched code-reviewer sub-agent.
Verbatim report follows; each finding must be either folded into PLAN.md or
explicitly rebutted there.

**Verdict: FIX FIRST** — 10 findings.

Direction is right and the fail-open stance is correctly stated (Non-Goals + Goals). Two things block execution: the plan assumes a per-event `input_example` can serve as a schema without confronting the gap, and Task 1.5 specifies an outcome with no method or evidence standard.

## CRITICAL

**1. `input_example` is an example, not a schema (PLAN.md:19-25, Task 1.2).** Each contract carries one flat example, no required/optional marking, no types, no conditionality. `Stop.json` has `stop_hook_active`/`background_tasks`/`session_crons`; `PostToolUseFailure.json` has `error`/`is_interrupt` — several are present only in some dispatches. Diffing "fields handlers read" against "keys in the example" therefore produces false findings in the direction that matters: a legitimately conditional field looks like drift.
*Remediation:* add a Technical Decision before Task 1.1 choosing (a) promote examples to a declared per-event input schema with explicit `required`/`optional` sets (new key in each contract JSON, maintained by the refresh procedure), or (b) treat the example strictly as a SUPERSET check — flag only fields the daemon reads that appear in NO example for that event, never flag absence. (b) is far cheaper and matches the stated fail-open principle.

**2. The read-surface inventory is scoped to the wrong population and lands red on false findings (Task 1.1).** Running the scan the task describes: top-level reads across `src/` include `assistant_messages`, `workspace`, `context_window`, `cost`, `effort`, `terminal_columns`, `level`, `count`, `custom_message` — none exist in any vendored contract, because they belong to StatusLine (declared out-of-contract by 00271 Task 3.2) and the `nitpick` pseudo-event. Also: reads are not confined to `handlers/` — `utils/session_helpers.py`, `utils/stop_hook_helpers.py`, `utils/permission_mode.py` read `hook_input` on handlers' behalf, so a handler-only AST scan under-reports. And the single most common read is `hook_input.get("tool_input")` (13 sites), whose NESTED keys (`command`, `file_path`, `new_string`) are exactly where rename risk lives — yet no contract describes them, since `tool_input` in the examples is one tool's shape.
*Remediation:* exclude out-of-contract/pseudo events by construction; widen the scan to `utils/`; state explicitly in Non-Goals whether nested `tool_input` keys are in scope.

**3. Task 1.5 has no experiment and its allowlist claim is half-wrong (PLAN.md:55-62).** `scripts/debug_hooks.sh` — what 00271 Task 2.7 used — captures INBOUND events and cannot answer an OUTBOUND rendering question. Workable design: emit a distinct sentinel on each channel in a real dogfood session, check which appears in the transcript jsonl vs the user-visible surface, and state the retirement rule in advance. Absence of rendering has innocent explanations, so write the rule as "retire only on positive evidence that the surviving channel delivers" — never on the other's failure to appear.
Also: only PermissionRequest has an allowlist entry (`contracts/claude-code-hooks/ALLOWLIST.yaml:25-27`). SessionStart's dual emission generates NO finding — `systemMessage` is documented on that event — so there is no SessionStart dual-channel allowlist entry to hunt for. Fix the task text.
Finally, 1.5 is 00271 close-out, not input validation: it shares no substrate with 1.1-1.4, blocks nothing here, and needs the dogfood daemon on main (a worktree agent cannot do it). Give it its own phase.

## IMPORTANT

**4. Goals bullet 2 contradicts Task 1.3.** The goal asserts the runtime advisory as a deliverable; Task 1.3 makes it conditional. Downgrade the goal to "a runtime advisory IF static coverage proves insufficient, with the decision recorded".

**5. The runtime advisory has no delivery surface (Task 1.3).** Most events cannot carry `additionalContext`, and drift would typically be detected on one that cannot advise. Realistic shape: record to the daemon/verdict log at detection, surface a per-session summary via SessionStart. Name it or the task is unimplementable.

**6. No performance budget for per-dispatch validation (Task 1.3).** Dispatch is ~1.8 ms; a per-dispatch layer is a measurable fraction. State a budget + measurement step, or sample first-dispatch-per-event-per-session.

**7. Contract refresh workflow interaction missing.** `docs/guides/HOOK-CONTRACT-REFRESH.md` has no step for re-triaging input fields. Without one the input half rots exactly as the output half did. Add a task.

**8. Project-handler implications unaddressed.** Client handlers read `hook_input` too and are the one population a QA sweep cannot reach; `bin/hooks-daemon validate-project-handlers` is the established mechanism (precedent: `core/decision_capability.py`). Extend it or record the gap in Non-Goals.

**9. Success criteria not mechanically measurable (PLAN.md:66-68).** "An input-field rename in a future release is surfaced" cannot be checked at completion. Restate as: a unit test that mutates a vendored `input_example` (renaming a read field) and asserts the checker reports it, plus checker wired into `llm_qa.py` and green.

**10. Structure incomplete vs CLAUDE/PlanWorkflow.md.** No Dependencies (should cite 00271 Complete + its artifacts by path), no Technical Decisions (findings 1 and 3 each need one), no Risks & Mitigations table, no Context & Background pointing at `AUDIT-schema-drift.md`. Phasing is one "Phase 1: Design and guard" holding five heterogeneous tasks including the unrelated 1.5.

## MINOR

- Task 1.4's field list sits in Goals rather than the task; move it so the task is self-contained. `effort` is already read (StatusLine), so its triage is "already consumed, different surface".
- If Task 1.3 lands it adds a config option → needs a `CLAUDE/UPGRADES/UNRELEASED/config-changes/` manifest entry plus `get_claude_md()`/acceptance-test consideration.
- Daemon-restart verification is named nowhere despite touching the dispatch path (mandatory per CLAUDE/CodeLifecycle/General.md).
- Task grammar, status line, header fields and absence of time estimates are all correct — no plan-QA issues.
