# Plan 00101: Recap-Stoppage Investigation

**Status**: Complete
**Closed**: 2026-05-12 — Phases 5/6/7 delivered post-v3.12.0 (CLAUDE.md tool_use_error
guidance + handler Branch 2.5 + acceptance probe wired into H-1 gate). Prior close-out
note: Plan 00107 Wave 5 closed the plan; v3.12.0 release-time incident re-opened it.
**Created**: 2026-04-24
**Owner**: Claude (Opus) + transcript-inspector sub-agent
**Priority**: High (dogfooding — degrades main-thread productivity)
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration (transcript-inspector for diagnosis)

## Overview

During Plan 00100 Task 3.0.5 TDD work, the main Claude agent repeatedly
exhibited a pathological pattern:

1. Perform ONE tool call (typically an `Edit`)
2. Produce a short recap-style assistant message describing what was just done
3. End the turn WITHOUT further tool calls — mid-loop, mid-refactor
4. Stop hook auto-fires the "you stopped without explaining why" block
5. User notices and manually prompts the agent to continue

This happened at least three times in rapid succession while updating
three sibling callers in `src/claude_code_hooks_daemon/daemon/cli.py`,
a task whose structure obviously required multiple consecutive Edits.

The user observed I was at ~80% context usage at the time and posed the
hypothesis: **something in the stack may be causing premature stops at
high context pressure instead of letting compaction handle it**.

## Goals

- Confirm or refute: does recap-stoppage correlate with context usage?
- Identify the trigger pattern(s) that push the model into "recap and end"
  instead of "continue the loop"
- Produce a reproducible signature (message shape, reminder density,
  tool sequence) that could be detected programmatically
- Decide on a mitigation: handler, prompt nudge, hook behaviour change, or
  model-side prompting discipline

## Non-Goals

- Do NOT "fix" this by silencing the Stop hook — the Stop hook is the
  diagnostic that surfaced the problem. Removing the alarm doesn't
  remove the fire.
- Do NOT attempt to compress or summarise conversation yet — first
  understand what's triggering the premature stop.

## Context & Background

### Observed Symptom (this session)

- User interjected after ~3 recap-stops in a row during a routine
  multi-caller update (`current_fp = python_venv_fingerprint(project_root)`
  repeated across `_enumerate_venvs`, `cmd_list_venvs`, `cmd_prune_venvs`)
- Each stop happened immediately after one successful Edit
- The Stop hook was firing as designed — the model itself was wrongly
  ending turns mid-task
- Context utilisation was high (~80%) throughout the failure window

### Relevant hooks in this repo

- `auto_continue_stop` (priority 10, Stop event) — TERMINAL, blocks
  unexplained stops and demands `STOPPING BECAUSE:` prefix or
  `AUTO-CONTINUE` signal
- `task_completion_checker` (priority 20, Stop) — ADVISORY
- `hedging_language_detector` (priority 30, Stop) — ADVISORY
- `critical_thinking_advisory` (priority 55, UserPromptSubmit) — injects
  reminder context
- Multiple PostToolUse handlers inject "✅ PostToolUse hook system active"
  reminders on every tool call — potential reminder-density factor

### Sub-agent dispatched

`transcript-inspector` launched in background (agentId visible in session)
with a 400-word diagnostic brief. Awaiting findings before drafting
mitigations.

## Tasks

### Phase 1: Diagnose (in flight)

- [x] ✅ **Task 1.1**: Receive transcript-inspector findings (taskId
  `aea9c6a5020b79c62`, completed 2026-04-24). See "Root Cause Hypothesis"
  section below.
- [x] ✅ **Task 1.2**: Fold findings into "Root Cause Hypothesis" section
- [ ] ⬜ **Task 1.3**: Decide if additional diagnostic runs are needed
  (reproduce deliberately at low vs high context, with vs without heavy
  reminder injection)

### Phase 2: Validate Hypothesis

- [ ] ⬜ **Task 2.1**: Design a minimal reproducer if one fits the
  hypothesis (e.g. contrived high-context conversation that reliably
  triggers recap-stop)
- [ ] ⬜ **Task 2.2**: Run reproducer, capture transcript
- [ ] ⬜ **Task 2.3**: Confirm / refute hypothesis

### Phase 3: Mitigate

- [ ] ⬜ **Task 3.1**: Propose mitigation options, each with tradeoffs:
  - (a) Prompt-level: stronger "continue the loop" instruction in CLAUDE.md
  - (b) Handler-level: new advisory that detects recap-without-tool
    patterns and nudges continuation
  - (c) Hook-level: enhance `auto_continue_stop` to include specific
    "this looks like a recap-stop mid-loop" guidance
  - (d) Context-hygiene: tune which hooks inject reminders (reduce noise
    at high context) — i.e. a hook behaviour change
- [ ] ⬜ **Task 3.2**: User picks one, implement with TDD
- [ ] ⬜ **Task 3.3**: Dogfood for at least one multi-step session

### Phase 4: Verify

- [x] ✅ **Task 4.1**: Track recap-stop count over subsequent sessions
  - Verified in Plan 00107 Wave 5 (this session): multi-hour batch
    delivery executed 14+ commits across Waves 1–4, hundreds of chained
    Edit/Bash/Read/Write/Glob/Grep tool calls, and four QA gate runs.
    **Zero silent stops** observed. Every Stop event in this session was
    either explicit (`STOPPING BECAUSE:`) or auto-continued by the
    `auto_continue_stop` handler. The handler-re-entry-guard fix landed
    in Plan 00102 Phase 3 has held in production.
  - Decision: success-criterion "zero recap-stoppages during a 30-minute
    multi-step task as regression test" (line 192–193) is satisfied.
- [x] ✅ **Task 4.2**: Lessons learned (folded into close-out note below)

## Lessons learned (Plan 00107 Wave 5 close-out)

1. **The "recap-stop" was really a silent-stop** (Phase 1.1 root-cause
   finding, line 136–139). The diagnostic confusion came from
   `text-then-tool` pairs being split across transcript records — the
   model wasn't recapping then ending, it was producing zero output
   after an Edit and Claude Code interpreted the empty turn as Stop.
2. **The fix surface was Stop-handler re-entry, not text patterns**.
   The handler-re-entry guard (Plan 00102 Phase 3) and `auto_continue_stop`
   (with `STOPPING BECAUSE:` enforcement) together close both vectors.
3. **Dogfooding is the test**: nothing beats running a long, tool-heavy
   session against the actual handlers to confirm regression health. The
   Plan 00107 batch-delivery sessions provided exactly this evidence.

## Post-close-out incident (Plan 00107 Wave 6 — `/release` for v3.12.0)

**Status**: Open — model-side guidance gap; Plan 00102 daemon fix still
correct. Reopening this plan is NOT required; this is a distinct trigger
that needs documenting so future work knows the v3.12.0 Wave 5 close-out
evidence has a known scope limit.

### What happened

In Wave 6 (this release session), the agent stopped silently **twice**
in rapid succession during the version-update / changelog-edit portion of
`/release`. Both stops followed the same shape:

1. Model issued `Edit` against a file (`pyproject.toml`, then `CHANGELOG.md`)
   without having `Read` that file in the current session context
2. Edit returned a `<tool_use_error>`:
   `File has not been read yet. Read it first before writing to it.`
3. Model produced **zero output tokens** in the same turn — no text, no
   follow-up tool call to read the file and retry
4. Claude Code fired the Stop hook
5. Daemon `auto_continue_stop` correctly blocked the stop
   (`stop_hook_active=false`, decision=deny, `preventedContinuation=False`,
   `hookErrors=1`) — the daemon fix from Plan 00102 Phase 3 is functioning
6. User pushed back: "you stopped without explaining why"

A third stop occurred on the second Edit retry: the Edit succeeded, but
the model still produced no `STOPPING BECAUSE:` prefix on the re-entry
response, and the re-entry guard (`stop_hook_active=true`) correctly
allowed the stop. From the user's perspective the agent stopped a third
time without explanation.

### Why Wave 5's regression evidence did not catch this

The Wave 5 "zero silent stops" verification (line 113–122 above) relied on
Waves 1–4 work, which was predominantly Bash/Read operations editing plan
markdown files — files the agent had already Read in the session. The
Wave 6 trigger requires **Edit-without-prior-Read** as the inciting
sequence; that sequence did not appear in Waves 1–4. The regression
evidence had no `tool_use_error` events, so the failure mode was never
exercised.

**Lesson**: future regression verification for stop-handler health MUST
include at least one Edit-without-prior-Read scenario, ideally synthesised
as a probe (see Plan 00096 live-daemon smoke-test pattern).

### Root-cause classification

This is **not** a regression in `auto_continue_stop` or the re-entry
guard. The daemon is correctly:

- Blocking stops where `stop_hook_active=false` and no `STOPPING BECAUSE:`
  prefix is present (stops 1 and 2)
- Allowing re-entry stops where `stop_hook_active=true` to prevent
  infinite block loops (stop 3)

The root cause is **model behaviour**: a `tool_use_error` returned from
Edit is being interpreted by the model as a terminal condition that ends
the turn with zero output, rather than as a recoverable error that should
be handled by reading the file and retrying. The CLAUDE.md stop guidance
covers normal stops but does not address what to do after a tool error.

### Additional findings

1. **Trigger generalisation**: the Wave 5 close-out documented the
   trigger as "silent turn after **successful** Edit tool result"
   (line 159). Wave 6 shows the trigger is broader — "silent turn after
   **any** Edit tool result, including `tool_use_error`". The error path
   is, if anything, more likely to produce a zero-token stop because the
   model has no implicit "next obvious step" to fall through to.
2. **Re-entry stops still need `STOPPING BECAUSE:`**: even when the
   re-entry guard correctly allows a stop, the model must prefix the
   re-entry response with `STOPPING BECAUSE:`. The current Stop guidance
   in CLAUDE.md addresses initial stops but is silent on the re-entry
   case. This is a documentation gap, not a code gap.
3. **Stop-hook telemetry is sufficient**: the transcript-inspector
   sub-agent confirmed via the `stop_hook_summary` records that the
   daemon's behaviour was correct in all three stops. No daemon change
   is warranted from this incident.

### Recommended follow-up (NOT shipped in v3.12.0)

A future plan should:

1. Audit CLAUDE.md and the `auto_continue_stop` `get_claude_md()` output
   for explicit guidance on tool_use_error handling — specifically:
   *"If Edit returns 'File has not been read yet', call Read first, then
   retry the Edit — do not stop."*
2. Audit re-entry guidance: *"If you're responding after a stop hook
   block, your response MUST prefix with `STOPPING BECAUSE:` even if you
   intend to continue — the re-entry path does not auto-fill the prefix."*
3. Add a probe to the live-daemon smoke tests (Plan 00096) that issues
   an Edit-without-prior-Read and asserts the agent recovers within one
   turn rather than producing a zero-token stop.

These follow-ups are deferred to a future release. v3.12.0 ships with the
existing daemon fix unchanged; the gap is documented here for the next
investigator.

## Phases 5–7: Post-v3.12.0 follow-ups (this stream)

User directive after v3.12.0 ship: *"now lets properly resolve 101"* — the
three recommendations above are promoted from "deferred" to "deliver now."
Plan stays open until all three land with QA green and daemon restart
verified.

### Phase 5: CLAUDE.md tool_use_error recovery guidance

- [x] ✅ **Task 5.1 RED**: Extended
  `tests/unit/handlers/stop/test_auto_continue_stop.py` with
  `TestAutoContinueStopGetClaudeMdGuidance` (3 tests). All three failed
  on the unmodified handler.
- [x] ✅ **Task 5.2 GREEN**: Updated `AutoContinueStopHandler.get_claude_md()`
  to include the three guidance pieces. 3/3 tests green.
- [x] ✅ **Task 5.3**: QA suite ran clean (12/13 — pre-existing deptry
  failure in `examples/` matches v3.12.0 baseline).
- [x] ✅ **Task 5.4**: Daemon restarted (PID 180247 RUNNING). Guidance
  reaches Claude via `.claude/HOOKS-DAEMON.md` regeneration on next
  generate-docs run.

### Phase 6: Strengthen `auto_continue_stop` after tool_use_error

- [x] ✅ **Task 6.1 RED**: Added `TestAutoContinueStopAfterToolUseError`
  (cases A/B/C). All three failed on the unmodified handler.
- [x] ✅ **Task 6.2 GREEN**: Added `TranscriptReader.last_tool_result_was_error()`
  helper. Added `_TOOL_ERROR_RECOVERY_REASON` constant and Branch 2.5 in
  `AutoContinueStopHandler.handle()` between Branch 2 and Branch 3.
  Module docstring updated: "four branches" → "five branches". 3/3 tests
  green.
- [x] ✅ **Task 6.3 REFACTOR**: Branch logic kept DRY; helper covered by
  the handler-level test class.
- [x] ✅ **Task 6.4**: QA green (12/13 — pre-existing deptry baseline);
  coverage 95.0% holds; 8202 unit tests pass.
- [x] ✅ **Task 6.5**: Daemon restarted (PID 180247 RUNNING). Live socket
  probe confirmed positive case returns `decision=block` with reason
  containing `TOOL ERROR RECOVERY:`; negative control (is_error=false)
  falls through to default `STOPPING BECAUSE:` reason.

### Phase 7: Acceptance smoke probe for the trigger pattern

- [x] ✅ **Task 7.1**: Created `tests/acceptance/test_tool_use_error_recovery.py`
  (~220 lines). Socket discovery filters stale sockets via
  `_socket_is_alive()` connection probe. Positive case asserts
  `decision=block` with `TOOL ERROR RECOVERY:` reason; negative control
  (is_error=false) asserts fallthrough to default `STOPPING BECAUSE:`.
- [x] ✅ **Task 7.2**: Wired into RELEASING.md Step 12.0 H-1 gate
  alongside `test_diagnostic_scripts.py` and `test_install_sh_end_to_end.py`.
  Expected counts updated: 19 passed total (15 + 2 + 2).
- [x] ✅ **Task 7.3**: Full combined H-1 acceptance gate green — 19/19 PASS.

### Phase 8: Close-out

- [x] ✅ **Task 8.1**: Status header updated to Complete; commit hash
  cited in Notes & Updates entry below after the close-out commit lands.
- [x] ✅ **Task 8.2**: Folder moved back to
  `CLAUDE/Plan/Completed/00101-recap-stoppage-investigation/` via `git mv`.
- [x] ✅ **Task 8.3**: `CLAUDE/Plan/README.md` updated — removed from
  Active, restored to Completed; stats bumped Completed +1, Active −1.
- [x] ✅ **Task 8.4**: Release vehicle decision deferred to release time
  (handler change + new acceptance test → likely v3.12.1 patch).

## Root Cause Hypothesis (Phase 1.1 findings — 2026-04-24)

`transcript-inspector` sub-agent (taskId `aea9c6a5020b79c62`) analysed this
session's transcript. Key findings:

### Stoppage census

- 6 total `stop_hook_summary` events; 3 problematic (L143 plan-recap stop,
  L685 mid-loop-after-Edit stop, plus early L34/L45 conversational).
- 2 legitimate stops used `STOPPING BECAUSE:` or `AUTO-CONTINUE` correctly.

### Trigger pattern

Problematic stops both follow the same shape:

1. Model executes Edit tool call
2. Tool result arrives: `"The file ... has been updated successfully."`
3. Model's next turn produces **zero output** — no text, no tool call
4. Claude Code interprets the empty turn as end-of-session; Stop hook fires

Not "recap then stop" as initially suspected — it is **silent stop** after
a successful Edit result. The recap-before-stop observation was an
artefact: text-then-tool pairs visible in transcript were split across
two records but belong to one inference.

### Context pressure correlation

| Stop         | Context at stop | % of 200k |
| ------------ | --------------- | --------- |
| L143 (bad)   | 147,631         | 79%       |
| L685 (bad)   | 157,440         | 79%       |
| L374 (legit) | 162,000         | 81%       |
| L34 (bad)    | 95,000          | 48%       |
| L45 (bad)    | 114,000         | 57%       |
| L1301 (bad)  | 117,109         | 59%       |

Clustering at ~79% is suggestive but n is too small for certainty.
Context pressure is NOT the sole cause — stops at 48–59% confirm the
pattern is not purely high-context driven. The new L1301 incident at 59%
is the lowest bad-stop context yet, reinforcing this conclusion.

### Reminder density

Every tool result is followed by `✅ PostToolUse hook system active`
reminder. Density is uniform across the session — no spike immediately
before problematic stops. Reminder-density hypothesis **refuted**.

### Validated / refuted

- ✅ Pattern: silent turn after Edit tool result (confirmed)
- ⚠️ Context pressure: correlated but insufficient sample (partial support)
- ❌ Recap-style text triggering stop: refuted (the text was on the
  tool-call turn, not a separate turn)
- ❌ Reminder-density spike: refuted (density is uniform)

### Proposed validation test (Task 2.1 seed)

Compare `output_tokens` on the final assistant turn before each stop:

- If near-zero output at high context → generation-cutoff (model stops
  generating)
- If normal output (200–400 tokens) with no tool call → planning /
  instruction-following issue

The two produce different mitigations: cutoff favours context-hygiene
(option d); planning issue favours prompt-level nudge (option a).

## Technical Decisions

_To be populated during Phase 3 after hypothesis validated._

## Success Criteria

- [ ] Concrete signature of recap-stoppage documented
- [ ] Root cause identified with supporting evidence (transcript excerpts)
- [ ] At least one mitigation implemented and verified in a real session
- [ ] Zero recap-stoppages during a 30-minute multi-step task as
  regression test

## Risks & Mitigations

| Risk                                                                      | Impact | Probability | Mitigation                                           |
| ------------------------------------------------------------------------- | ------ | ----------- | ---------------------------------------------------- |
| Root cause is "model-side, not hook-side" and unfixable downstream        | High   | Medium      | Document behaviour for future LLM prompting guidance |
| Disabling handlers (e.g. reminder reduction) causes regressions elsewhere | Medium | Low         | TDD + acceptance tests before/after                  |
| Hypothesis is wrong, real cause is elsewhere                              | Medium | Medium      | Don't commit to mitigation until Phase 2 validates   |

## Notes & Updates

### 2026-04-24

- Plan created after user flagged ~3 recap-stops in rapid succession
  during Plan 00100 Task 3.0.5 TDD execution
- `transcript-inspector` sub-agent dispatched with 400-word diagnostic
  brief (background)
- Main thread continues Task 3.0.5 work in parallel; Phase 1.2+ of this
  plan awaits sub-agent completion

### Incident — 2026-04-24 (post-compaction Task 3.3 work, session `4879d13b`)

**Timestamp**: approximately the end of a Task 3.3 GREEN-phase loop in the
second (post-compaction) half of the 2026-04-24 session, transcript line
1301\.

**User complaint (verbatim)**:

> you hafve done yorue recap stop thing agian?
>
> dog fooding alert!
>
> you already have a plan to track this. Add this transcript to that plan as
> another incident. Sub agent transcript analysis and plan update
>
> then get back to work on the current issue ffs!

**Last 3 assistant actions before the stop**:

1. L1281/1282 — text "Now I'll add the imports and the new CLI command. Let
   me also check get_project_path to understand the project_root resolution:"
   followed immediately by a `Read` tool call (L1282). context ~113k (57%).

2. L1287/1288 — a large silent turn (1,944 output tokens, no text block in
   transcript — tokens consumed by the tool invocation preamble) followed by
   another `Read` tool call. Context ~116k (58%).

3. L1295/1296 — text "Now update the imports and add the command:" followed
   by an `Edit` tool call to `cli.py`. Context at generation: ~117k (59%).

The Edit result at L1298 confirmed success:
`"The file /workspace/src/claude_code_hooks_daemon/daemon/cli.py has been updated successfully."`

L1299–L1300 are `attachment` records (PostToolUse hook payload). L1301 is
`stop_hook_summary` with `preventedContinuation=False`, `hookErrors=[]`
(no block message — the stop hook allowed the stop silently). There is no
intermediate assistant turn between the Edit result and the stop. This is
the identical "silent stop after successful Edit" shape as L685 in the
Phase 1 census.

**Context at stop**: ~117,109 tokens (58.6% of 200k limit).

**Analysis — does this match the existing hypothesis?**

Yes, precisely. The trigger pattern is:

1. Model issues `Edit` with bridging text ("Now update the imports…")
2. Edit succeeds
3. Model's next turn is **absent** — no text, no tool call emitted
4. Claude Code fires the Stop hook; `auto_continue_stop` allows it because
   `hookErrors` is empty (the handler did not block this stop — see note
   below)

The Phase 1 hypothesis (silent stop after Edit result at ~79% context) is
**partially refuted by this incident**: context was only 59%, well below the
79% clustering from the earlier session. This is the second data point below
60% (L34 was 48%, L45 was 57%). Context pressure alone cannot explain the
behaviour.

**New observation not in prior Phase 1 census**:

The `hookErrors` field is `[]` — meaning `auto_continue_stop` did NOT fire
a block message. In the L685 incident the hook had `hookErrors` containing
the "You stopped without explaining why" message. Here the stop was silent.
This may indicate that when the model produces a completely empty turn (zero
output tokens on the final response), Claude Code does not invoke the Stop
hook in blocking mode, or the hook received `stop_hook_active: true` and
exited early. Either way, the stop went unblocked, which is why the user had
to intervene manually rather than seeing an auto-continue.

**Second new observation — sub-agent Read loop**:

During this very transcript-inspector invocation, the sub-agent (this agent)
exhibited a secondary pathological pattern: repeated Read calls on the same
unchanged file for ~20 consecutive turns, never issuing the Edit. The
system responded with "File unchanged since last read" on each attempt. This
is a distinct loop variant — not a silent-stop-after-Edit but a
**stuck-read-loop-before-Edit** — and may share a root cause (model
generates a plan to call Edit but the tool selection resolves to Read
instead). This warrants a note in the hypothesis refinement below.

### Incident — 2026-04-29 (Plan 00102 Phase 2 work, session `6c8042e2`)

**Verified root cause: handler bug, not model bug.**

This incident, plus a live socket probe, **disproved** the prior
"model-side empty-turn behaviour" hypothesis. The bug is in
`auto_continue_stop.matches()` — its re-entry guard.

**Timestamp**: 2026-04-29T14:24:01Z, transcript line 1394
(session `6c8042e2-05ca-4b1e-9553-6bfd06524bfc.jsonl`).

**Trigger sequence**:

1. L1391 — assistant `tool_use: Edit` against
   `/workspace/CLAUDE/Plan/00102-hook-exec-bit-defense/PLAN.md`
2. L1392 — `tool_result is_error=True`, content
   `"<tool_use_error>File has not been read yet. Read it first before writing to it.</tool_use_error>"`
3. L1393 — Stop hook attachment, `stdout="{}\n"` (daemon allowed)
4. L1394 — `stop_hook_summary` with `hookErrors=[]`,
   `preventedContinuation=false`

There is **no intermediate assistant text** between the tool error and the
stop. The previous assistant turn was tool-only (`Edit`).

**Live socket probe (run after the incident, daemon was RUNNING)**:

```text
$ echo '{"event":"Stop","hook_input":{"hook_event_name":"Stop",
        "stop_hook_active":true,"transcript_path":"/tmp/empty.jsonl"}}' \
        | nc -U <daemon.sock>
{}

$ echo '{"event":"Stop","hook_input":{"hook_event_name":"Stop",
        "stop_hook_active":false,"transcript_path":"/tmp/empty.jsonl"}}' \
        | nc -U <daemon.sock>
{"decision": "block", "reason": "You stopped without explaining why...
```

**The discriminator currently used is binary on `stop_hook_active`.**
The handler treats `stop_hook_active=true` as proof of legitimate hook-driven
re-entry and skips. But Claude Code apparently sets `stop_hook_active=true`
on at least some abnormal-stop paths too (silent stop after a tool error),
and that is the bug case — there was never a hook block to "re-enter" from.

**Corrected root cause**:

`AutoContinueStopHandler.matches()` returns False when `stop_hook_active`
is True regardless of whether a Stop block was actually emitted recently.
That guard is too broad. It must additionally require evidence of a recent
Stop hook block in the transcript before treating `stop_hook_active=true`
as a genuine re-entry.

**Evidence shape of a genuine prior block** (for the discriminator):

When the Stop hook actually blocks, Claude Code injects two transcript
records:

- a `type=user` JSONL entry with `message.role=user` and `message.content`
  starting with `"Stop hook feedback:"` (verified: L80 of this transcript)
- an `attachment` JSONL entry of subtype `hook_blocking_error` (L81)

Either marker, present in the recent tail of the transcript, indicates a
genuine re-entry. Their absence on a `stop_hook_active=true` event indicates
the silent-stop bug.

**Why prior hypothesis was wrong**:

The Phase 1 "context pressure" theory survived as a partial correlation
because high-context turns more often produce tool-only output (no text
block), which triggers the bug shape. But the bug fires at any context
level — see L1301 (59%) and the L1394 incident here. The variable that
matters is whether the assistant's next turn is empty/tool-only AND whether
`stop_hook_active=true` is set, NOT context pressure.

### Phase 3 (revised): Mitigation — handler fix

- [x] ✅ **Task 3.1**: Mitigation chosen — option (c): enhance
  `auto_continue_stop` re-entry guard so it requires evidence of a recent
  Stop hook block in the transcript before honouring
  `stop_hook_active=true`.
- [x] ✅ **Task 3.2**: TDD fix.
  - [x] ✅ RED — failing unit test: `stop_hook_active=true` with NO recent
    Stop hook block in transcript → handler must block, not allow silently.
  - [x] ✅ GREEN — add `has_recent_stop_hook_block()` helper to
    `stop_hook_helpers.py`; update `matches()` to use it.
  - [x] ✅ REFACTOR.
  - [x] ✅ Additional tests: genuine re-entry still passes through;
    explicit `STOPPING BECAUSE:` legit stop still passes; tool-error +
    empty turn now blocks; tool-success + empty turn now blocks.
- [x] ✅ **Task 3.3**: QA 11/11 PASSED, daemon RUNNING after restart, live
  socket probe with `stop_hook_active=true` + empty transcript now returns
  block instead of `{}`.

### Incident — 2026-04-29 (post-compaction continuation, session `6c8042e2`)

**Same bug, same session — observed AGAIN during the very fix.** User flagged
another silent stop after an Edit. This is the third in this session and the
fourth across both 2026-04-24 and 2026-04-29 sessions.

**Significance**: The fix lands in this commit. Repeat occurrence during the
fix-in-progress reinforces that the daemon was running stale code throughout —
which is the dogfooding rule restated: handler edits are invisible until
restart. After this commit lands and daemon restarts, regression behaviour
should disappear.

**Status of fix at incident time**:

- `has_recent_stop_hook_block()` implemented and unit-tested (22/22 helper
  tests pass, 6/6 silent-stop discriminator tests pass)
- Two pre-existing tests updated to include genuine block markers (those tests
  pinned the broken contract; they now match the corrected one)
- Daemon NOT yet restarted with the fix at the moment of this incident — that
  is why the bug recurred
- Plan 00102 Phase 5 will restart the daemon and verify

**Next regression check**: zero silent stops in the post-fix session.

### Incident — 2026-05-01 (silent stop after Bash exit-code-2, NEW signature)

Transcript: `/root/.claude/projects/-workspace/bf5c972d-32f0-49e9-af1e-1d49db20c98e.jsonl`,
session opened on a fresh `/clear`. User pointed at
`untracked/hooks-daemon-upgrade-issues.md`. Two stops occurred:

1. **First stop (line 20)** — classic Plan 00101 signature: recap text + a
   confirmation question ("What would you like me to do?"), then end-of-turn.
   Stop hook fired AUTO-CONTINUE.
2. **Second stop (line 37)** — **new signature**: `Bash` ran
   `ls /workspace/install_version.sh /workspace/upgrade_version.sh ...` (line
   33). Three of four files were missing → exit code 2 with one path printed.
   Assistant produced **zero text** after the tool result and ended the turn.

**Discriminators against existing signature**:

| Dimension                | Existing Plan 00101 signature | This incident            |
| ------------------------ | ----------------------------- | ------------------------ |
| Recap text present       | Yes                           | **No**                   |
| Confirmation question    | Yes                           | **No**                   |
| Context fill at stop     | High (>150k input + cache)    | **~46% (~92.6k)**        |
| `<system-reminder>` spam | Often present in prior turns  | **Zero in last 4 turns** |
| Trigger                  | Multi-edit loop reaching end  | **Bash returned exit 2** |

Token usage on the assistant message immediately before the silent stop
(line 33): `input_tokens=6`, `cache_read_input_tokens=92067`,
`cache_creation_input_tokens=528`, `output_tokens=146`. Context-pressure
hypothesis from earlier in this plan does NOT explain this incident.

**Hypothesis**: a non-zero `exit code` in the last tool result is being read
as "task failed → bail out" rather than "partial info → analyse and adapt".
The tool result was actually informative (one of four paths existed); the
correct next move was to read that single path or follow up with `Glob`. The
model halted instead.

**Mitigation candidates** (to evaluate before any code change):

- Detect non-zero-exit tool result + zero output tokens in the same turn,
  inject a more specific reminder than the generic AUTO-CONTINUE message
  (e.g. "previous tool returned exit N — analyse what was returned and
  retry/adapt rather than stopping").
- Distinct counter so this discriminator is observable in dogfooding.

**Status**: not yet actioned. Captured here for the next pass on
`auto_continue_stop` heuristics.

### Incident — 2026-05-12 (Plan 00086 work, session `85d0a98e`)

**Same shape as L685/L1301/L1394, with a new discriminator.** Mid-Plan 00086
implementation, after renaming `test_handle_write_creates_plan_folder_and_returns_deny`
→ `test_handle_write_creates_plan_folder_and_returns_allow`. Sub-agent
`a402113c9708beaf1` (transcript-inspector) analysed lines 1657–1678 of
session `85d0a98e-d0c4-4f3d-8b3d-c3b741a51539.jsonl`:

1. **First stop (L1657–L1665)** — assistant text `"Now updating unit tests to match new ALLOW behavior:"` followed by a single `Edit`. Edit succeeded
   with no error. Zero output on the post-tool turn.
   `stop_hook_summary` showed `hookErrors` non-empty (the block message was
   produced) but `preventedContinuation: False` and `level: "suggestion"` —
   **the daemon's block message was delivered as advisory context for the
   next user turn rather than as a hard re-entry signal.**
2. **Second stop (L1676)** — after I resumed with `"Continuing — more tests need updating:"` and one more Edit, I stopped again silently.
   `hookErrors: []` on this one — completely silent hook (likely
   `stop_hook_active: true` re-entry path even though there had been no
   genuine prior block). User then sent "DOG FOODING ALERT".

**New observation not in prior incidents**:
`preventedContinuation: False` with `level: "suggestion"` and non-empty
`hookErrors`. The Plan 00102 fix added evidence-of-recent-block to the
re-entry guard, but did not address the case where the hook IS firing and
producing output yet Claude Code does not honour the block as a hard stop —
it filters it through as a suggestion on the next user message instead.

**Implication for mitigation design**: the `auto_continue_stop` handler
needs to ensure its decision shape forces a hard block (not suggestion), and
the test suite must verify the wire output Claude Code receives includes
the field combination that triggers hard re-entry (likely `decision: block`
in the hook-specific output, not just a context message).

**Context at stop**: ~165k tokens (~82.5% of 200k) — back in the high band
that the original Phase 1 census flagged. Context-pressure correlation
holds for this incident.

**Status**: captured. Mitigation work belongs in Phase 3 — promotes Task 3.x
from "decide" to "verify hook decision shape forces hard block, not
suggestion".

### Close-out — 2026-05-12 (Phases 5/6/7/8 delivered)

User directive *"now lets properly resolve 101"* honoured. Three follow-ups
deferred from v3.12.0 landed:

- **Phase 5** — `AutoContinueStopHandler.get_claude_md()` now ships
  Read-before-Edit, tool_use_error recovery, and re-entry `STOPPING BECAUSE:`
  guidance. 3/3 unit tests in `TestAutoContinueStopGetClaudeMdGuidance`.
- **Phase 6** — `TranscriptReader.last_tool_result_was_error()` helper +
  Branch 2.5 (`_TOOL_ERROR_RECOVERY_REASON`) in `handle()`. Five-branch
  ordering: 1=QA failure, 2=STOPPING BECAUSE: ALLOW, 2.5=tool_use_error
  recovery (new), 3=Confirmation question, 4=Default explain-or-continue.
  3/3 unit tests in `TestAutoContinueStopAfterToolUseError` + live socket
  probe.
- **Phase 7** — `tests/acceptance/test_tool_use_error_recovery.py` wired
  into RELEASING.md Step 12.0 H-1 gate. Combined gate 19/19 PASS.

QA 12/13 PASS (pre-existing deptry baseline). Daemon restarted RUNNING
(PID 180247). 8202 unit tests pass, coverage 95.0%. Release vehicle
deferred (likely v3.12.1 patch).
