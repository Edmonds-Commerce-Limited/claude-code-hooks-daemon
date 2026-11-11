# Plan 00600: user prompt quality scan

**Status**: Not Started
**Created**: 2026-11-11
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The daemon guards what agents do, but nothing looks at what a human types. This plan asks whether a UserPromptSubmit
handler should notice a prompt that is clearly not optimal, and warn or block. The research is in
[RESEARCH.md](RESEARCH.md); this plan carries only its conclusions and the work that follows from them.

**Recommendation: a narrow GO.** Most prompt defects that matter (an unclear target, contradictory or unscoped
instructions, an XY problem) need a model's judgement, and the agent that reads the prompt is already that model. So
there is no general "prompt quality" judge. Instead, one handler supplies three FACTS the agent does not have: the
human's bare approval answered a turn that offered several options or a risky step (the Fable 5.2 "Approvals" case);
the prompt holds a credential; a command in the prompt is one a daemon guard will refuse. Only the credential case
speaks to the human, because only the human can rotate a leaked key.

UserPromptSubmit cannot rewrite a prompt, and a block's reason never reaches the model. A credential block is
therefore opt-in, and it must set `suppressOriginalPrompt`, or the block message writes the secret into the
transcript a second time.

## Goals

- A `prompt_facts` UserPromptSubmit handler with three detectors, each with its own enable flag:
  - **D1 gated bare approval**: agent-only advisory, fired only when the previous assistant turn offered two or more
    options or named a destructive step.
  - **D2 pasted credential**: a visible `systemMessage` to the human plus an agent advisory; an opt-in block that sets
    `suppressOriginalPrompt`.
  - **D3 command a guard will refuse**: agent-only advisory, found by dry-running backticked commands through the
    real PreToolUse Bash handlers.
- Each detector ships only after it clears a precision bar on recorded transcripts and shows an outcome difference.
- The ccy supervisor's post-compaction resume line names the action instead of sending a bare `continue`.

## Non-Goals

- No model call from the daemon, and no default `type: "prompt"` hook (RESEARCH.md Q3).
- No prompt rewriting: the event has no field for it.
- No style feedback to the human: no prompt scores, no advice on paste layout or "can you suggest" phrasing.
- No detector for contradictory, unscoped or target-less prompts; those stay with the agent and the existing
  `critical_thinking_advisory` nudge.
- No logging of prompt text or of any matched span.

## Tasks

### Phase 1: measure before building

- [ ] ⬜ **Task 1.1**: Build an offline replay over recorded transcripts on the Plan 00274 extractor
  (`skill_scan/extraction.py`), pairing each genuine human prompt with the assistant turn before and after it. Counts
  only in any written output; samples shown locally for labelling, never committed.
- [ ] ⬜ **Task 1.2**: Stage A precision replay for D1, D2 and D3 against the proposed bars (D2 at 90 %, D1 and D3
  at 80 %). Record the results in a supporting document.
- [ ] ⬜ **Task 1.3**: Stage B outcome proxies (corrections, interrupts, predicted denies, credentials reaching tool
  inputs) for flagged against unflagged prompts. Drop any detector with no outcome difference.
- [ ] ⬜ **Task 1.4**: Confirm live, in a throwaway session, what a plain UserPromptSubmit block leaves in the input
  box and the transcript, with and without `suppressOriginalPrompt`.
- [ ] ⬜ **Task 1.5**: Owner go/no-go per detector on the Phase 1 numbers.

### Phase 2: wire-format carriers

- [ ] ⬜ **Task 2.1**: TDD a `HookResult` carrier for `systemMessage` on UserPromptSubmit and declare it in the
  response schema; drop the matching `ALLOWLIST.yaml` entry.
- [ ] ⬜ **Task 2.2**: TDD a carrier for `hookSpecificOutput.suppressOriginalPrompt`; drop its `ALLOWLIST.yaml` entry.

### Phase 3: the handler

- [ ] ⬜ **Task 3.1**: TDD `prompt_facts` gated on `is_genuine_human_prompt`; skip slash commands and the
  `hooks-daemon focus` trigger; fail open on a missing or non-string prompt and on an unreadable transcript tail.
- [ ] ⬜ **Task 3.2**: D2 on the existing credential patterns (`secret_strategy.py`, `sensitive_content` public
  patterns, the secret word list through `utils/secret_redaction.py`). Messages name the class, never the value.
- [ ] ⬜ **Task 3.3**: D1 with a bounded transcript-tail read of the last assistant message.
- [ ] ⬜ **Task 3.4**: D3 dry-running inline code spans and fenced blocks through the PreToolUse Bash handlers.
- [ ] ⬜ **Task 3.5**: Test that a D2 block leaves the session's Plan 00501 modes unchanged (a blocked prompt does not
  clear BLOCKED or renew focus).
- [ ] ⬜ **Task 3.6**: Acceptance tests, `get_claude_md` guidance, and the release-notes and config-changes entries
  in `CLAUDE/UPGRADES/UNRELEASED/`.

### Phase 4: supervisor resume line and live evaluation

- [ ] ⬜ **Task 4.1**: Replace the supervisor's bare `continue` (`_CONTINUE_BODY`) with a line that names the action,
  and verify the worker reload per the supervisor hot-reload contract.
- [ ] ⬜ **Task 4.2**: Stage C session-parity A/B (advisory emitted against "would fire" logged only), compared on
  human corrections, not on agent questions alone.

## Success Criteria

- [ ] RESEARCH.md answers the five research questions with cited evidence, and the owner records a go/no-go per
  detector.
- [ ] Every shipped detector met its Stage A precision bar and showed a Stage B outcome difference.
- [ ] No daemon log, verdict record or advisory contains prompt text or a matched credential value.
- [ ] Only human-typed prompts are judged: cron ticks, supervisor lines, task notifications and teammate messages
  never trigger a detector.
- [ ] A D2 block sets `suppressOriginalPrompt` and changes no session mode.
- [ ] This project's QA gate for the change passes.
- [ ] Every release-bound consequence (the new handler's release note, its config-changes entry for the opt-in block)
  is in the pending-release holding area `CLAUDE/UPGRADES/UNRELEASED/`.

## Delivery & Milestones

- Research: RESEARCH.md, on branch `plan-00600-research`.
