# Plan 00115: Parallel-Batch Cancellation Footgun Mitigation

**Status**: Complete
**Created**: 2026-05-29
**Owner**: Claude (Opus) + user (joseph)
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Single-threaded, strict one-mutation-per-turn (dogfooding the fix)

**Outcome (maintainer-finalised)**: G1 + G3 shipped in `core/hook_result.py` (commit
e7b02c2) and live-proven (a blocked `sed`/pipe now returns the cancellation warning). G4
delivered as a brief permanent warning in hand-authored `CLAUDE.md` (commit 11d5eeb) — the
generated-`<hooksdaemon>`-clause variant is deferred to Plan 00116's single meta-rule to
avoid re-bloating the injected block. **G2 SKIPPED** by maintainer decision: the static
suffix is accurate without a transcript-derived sibling count, and counting adds hot-path
I/O; revisit only if a precise count proves necessary.

## Overview

While working on Plan 00114, the agent repeatedly lost Edits, Writes, and commits and
misdiagnosed the cause as a "degraded harness" for ~6 rounds. The real cause is a
**silent, self-misdiagnosing footgun**:

> Claude Code executes parallel tool calls in a single assistant turn. When ANY one call
> in that batch is denied by a daemon PreToolUse hook (e.g. `sed_blocker`, `pipe_blocker`),
> Claude Code CANCELS every sibling tool call in the batch with
> "Cancelled: parallel tool call … errored". Any `Edit`/`Write`/`git commit` batched
> alongside the blocked command is silently discarded — and the cancellations arrive
> lagged/out-of-order, so they read like terminal flakiness rather than data loss.

The daemon cannot stop Claude Code's client-side cancellation (the block MUST happen to
protect against dangerous commands). But the daemon can — and currently does NOT — make
the consequence **loud and actionable** at the exact moment it fires, and can warn agents
away from the pattern up front.

Worse, the current guidance actively reinforces the trap: `_DENY_CONTINUATION_SUFFIX`
(`core/hook_result.py:25`) appends to every DENY *"Do not stop working. Modify your
approach using the guidance above and continue."* — which frames a block as locally
recoverable and never mentions that batched siblings were just destroyed.

## Goals

- **G1** — Every PreToolUse DENY surfaces a clear warning that batched sibling tool calls
  (Edit/Write/commit) were cancelled by Claude Code and must be re-issued in a separate
  turn. (Static baseline — zero detection, zero risk, always correct advice.)
- **G2** — When the daemon can confirm the block was part of a real multi-tool-use turn
  (via the transcript), emit a louder, specific warning naming the cancelled siblings.
- **G3** — Correct `_DENY_CONTINUATION_SUFFIX` so "modify and continue" also says
  "re-issue anything that was batched with this call".
- **G4** — Add a guidance clause to the generated `<hooksdaemon>` block: never batch
  Edit/Write/commit in the same turn as a Bash command that may be blocked.
- **G5** — Regression tests pinning G1-G4; full QA; daemon restart RUNNING.

## Non-Goals

- Preventing Claude Code's parallel-cancellation behaviour (client-side; out of our control).
- Changing what the blocking handlers block (sed, pipes, etc. stay blocked).
- Reordering / holding tool execution.

## Context & Background

### Confirmed mechanism

- The block is a daemon PreToolUse DENY → Claude Code treats the call as errored → cancels
  siblings in the same parallel batch. Observed repeatedly this session:
  `Cancelled: parallel tool call Bash(...) errored`.
- Each PreToolUse hook fires as a SEPARATE socket request; the payload contains only that
  call's `tool_input` — siblings are NOT visible within a single invocation.
- Batch detection IS possible:
  1. **Transcript (reliable)**: `transcript_path` is in hook_input; `core/transcript_reader.py`
     already parses `tool_use` blocks. Count `tool_use` blocks in the latest assistant
     message → `>1` = batch; sibling tool names reveal cancelled Edit/Write/commit.
  2. **Timing (heuristic)**: persistent daemon can cluster near-simultaneous PreToolUse
     invocations per session. Less robust — not the chosen path.

### Relevant code (verified against HEAD)

- `core/hook_result.py:22-27` — `_DENY_CONTINUATION_SUFFIX` (appended to all PreToolUse
  DENY reasons). The natural home for the static warning (G1) and the correction (G3).
- `core/router.py:19-21` — `_CONFIG_KEY_FOOTER` + `_inject_config_key_footer` (line 128):
  central place DENY/ASK reasons are augmented (Plan 00050). Candidate site for the
  transcript-aware warning (G2) since it has the event/handler context.
- `core/front_controller.py:132` — sibling `_inject_config_key_footer` (DRY check: confirm
  which path is live for PreToolUse so the warning isn't duplicated or missed).
- `core/claude_md_injector.py` — generates the `<hooksdaemon>` guidance block (G4).
- `core/transcript_reader.py` — `tool_use` parsing for batch detection (G2).

### Dogfooding root-cause (the irony)

The fix author (this session) is the proof case: with the warning absent, an Opus agent
lost work 6× and blamed the harness. The static warning (G1) alone would have flipped that
on the first occurrence.

## Tasks

### Phase 0: Confirm the mechanism & wiring (NO code changes)

- [ ] ⬜ **Task 0.1**: Confirm which `_inject_config_key_footer` (router.py vs
  front_controller.py) is live for PreToolUse DENY in the running daemon (dispatch path).
- [ ] ⬜ **Task 0.2**: Confirm `_DENY_CONTINUATION_SUFFIX` is applied to all PreToolUse
  DENY reasons and where (so G1/G3 land once, not twice).
- [ ] ⬜ **Task 0.3**: Confirm `TranscriptReader` exposes per-message `tool_use` blocks
  usable from the deny path, and that `transcript_path` is reliably in PreToolUse input.

### Phase 1: G1 — Static cancellation warning on every PreToolUse DENY (TDD)

- [ ] ⬜ **Task 1.1**: RED — test that a PreToolUse DENY reason contains the
  batch-cancellation warning (sibling Edit/Write/commit cancelled → re-issue separately).
- [ ] ⬜ **Task 1.2**: GREEN — add the warning to the universal DENY suffix path in
  `hook_result.py`. Keep it concise; PreToolUse-only (not Stop/other events).
- [ ] ⬜ **Task 1.3**: Ensure ASK decisions also covered if they cancel siblings (verify;
  include if so).

### Phase 2: G3 — Correct the misleading continuation suffix (TDD)

- [ ] ⬜ **Task 2.1**: RED — test the continuation suffix now references re-issuing batched
  calls, not just "modify and continue".
- [ ] ⬜ **Task 2.2**: GREEN — update `_DENY_CONTINUATION_SUFFIX` wording. Update any
  existing tests that pin the old exact string (legitimate contract change).

### Phase 3: G2 — Transcript-aware precise warning (TDD)

- [ ] ⬜ **Task 3.1**: RED — test that when the current assistant message has >1 `tool_use`
  block, the DENY reason includes a specific warning naming the count and any cancelled
  Edit/Write/commit siblings; and that a solo block does NOT get the loud version.
- [ ] ⬜ **Task 3.2**: GREEN — in the central deny-augmentation path, read the transcript
  (best-effort; never fail the deny if transcript is unreadable — FAIL SAFE to G1's static
  warning), count `tool_use` blocks, classify siblings, append the precise warning.
- [ ] ⬜ **Task 3.3**: Performance/robustness — transcript read must be cheap and
  exception-safe (a slow/missing transcript must never break or delay a block).

### Phase 4: G4 — Guidance clause in generated docs (TDD)

- [ ] ⬜ **Task 4.1**: RED — test the generated `<hooksdaemon>` block contains a
  "never batch mutating tool calls with blockable Bash" clause.
- [ ] ⬜ **Task 4.2**: GREEN — add the clause in `claude_md_injector.py` (or its template).
- [ ] ⬜ **Task 4.3**: Regenerate `.claude/HOOKS-DAEMON.md` / CLAUDE.md injected block.

### Phase 5: Integration, QA, dogfood

- [ ] ⬜ **Task 5.1**: Full QA: `./scripts/qa/llm_qa.py all`.
- [ ] ⬜ **Task 5.2**: Daemon restart RUNNING; live-probe a block via `nc`/hook wrapper to
  confirm the warning appears in a real DENY payload.
- [ ] ⬜ **Task 5.3**: Update CLAUDE.md "Blocking Handler" section if needed; note the
  footgun in the dogfooding section.

## Technical Decisions

### Decision 1: Static baseline first, transcript-aware enhancement second

**Context**: the warning must never itself fail (a broken warning path that swallows a DENY
would be catastrophic). **Decision**: ship G1 (static, unconditional, no I/O) as the
load-bearing fix; layer G2 (transcript-aware) on top as best-effort that FAILS SAFE to the
static text if the transcript is missing/unreadable. Never let transcript I/O break a block.

### Decision 2: PreToolUse scope

**Context**: parallel cancellation matters where mutating siblings exist — PreToolUse. Stop/
SessionStart/etc. denies don't share the footgun the same way. **Decision**: scope the
warning to PreToolUse (and PermissionRequest if it cancels siblings — verify in Phase 0).

## Success Criteria

- [ ] Every PreToolUse DENY tells the agent that batched siblings were cancelled (G1).
- [ ] The continuation suffix no longer implies a block is consequence-free (G3).
- [ ] Real multi-tool-use blocks get a specific, named warning; solo blocks don't (G2).
- [ ] Generated guidance warns against the batch pattern (G4).
- [ ] Transcript read is exception-safe and cheap; a missing transcript never breaks a block.
- [ ] Full QA passes; daemon restarts RUNNING; live-probe shows the warning.

## Risks & Mitigations

| Risk                                                            | Impact | Probability | Mitigation                                                             |
| --------------------------------------------------------------- | ------ | ----------- | ---------------------------------------------------------------------- |
| Transcript read throws / is slow on the hot deny path           | High   | Med         | G2 wrapped in try/except → fall back to G1 static text; cheap read     |
| Warning becomes noise on every solo block                       | Low    | Med         | Keep G1 text one line; reserve the loud/named version for real batches |
| Updating `_DENY_CONTINUATION_SUFFIX` breaks string-pinned tests | Low    | High        | Find & update those tests (legitimate contract change)                 |
| Duplicate warning (router.py AND front_controller.py paths)     | Med    | Med         | Phase 0.1 pins the single live path before editing                     |

## Notes & Updates

### 2026-05-29

- Plan created directly from this session's dogfooding incident (lost work 6× to the
  cascade; misdiagnosed as harness flakiness).
- Verified `_DENY_CONTINUATION_SUFFIX` (`hook_result.py:25`) and the central
  `_inject_config_key_footer` augmentation points (`router.py`, `front_controller.py`).
- Plan 00114 (upgrade fixes) delegated to a background Opus agent in an isolated worktree
  to avoid git races while this footgun work proceeds in the main tree.
  </content>
