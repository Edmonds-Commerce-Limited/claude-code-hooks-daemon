# Plan 00087: Post-Clear Auto-Execute

**Status**: In Progress
**Created**: 2026-03-11
**Owner**: Claude
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

When using `/clear execute plan 85` in Claude Code, the session clears and the new context contains the text "execute plan 85", but the agent just sits idle waiting for further input. The user has to manually type "go" or similar to kick things off.

This plan explores whether we can use a hook (likely SessionStart or UserPromptSubmit) to detect that `/clear` was followed by instructional text, and automatically inject a "go" signal so the agent acts on it without manual prompting.

## Goals

- Confirm whether post-clear text is visible in hook events (SessionStart, UserPromptSubmit, or other)
- Build a working prototype that auto-triggers agent execution after `/clear <instructions>`
- Once prototype validated, implement as a proper handler with TDD

## Non-Goals

- Changing Claude Code's `/clear` command behaviour itself
- Handling cases where `/clear` is used alone (no text) - those should remain as-is

## Context & Background

The `/clear` command in Claude Code resets the conversation. When followed by text (e.g., `/clear execute plan 85`), the text appears in the new session context but doesn't trigger agent action. The user must manually prompt again.

The hooks daemon already has SessionStart and UserPromptSubmit handlers. The question is whether the post-clear text is visible in either of these events, and if a hook response can trigger the agent to act on it.

## Tasks

### Phase 1: Investigation & Prototype

- [ ] **Task 1.1**: Capture hook events after `/clear some text`
  - [ ] Enable debug hook logging (`./scripts/debug_hooks.sh start`)
  - [ ] Run `/clear test message here` in a Claude Code session
  - [ ] Examine captured events to see where the post-clear text appears
  - [ ] Document which event type carries the text and its structure

- [ ] **Task 1.2**: Determine viable hook response mechanism
  - [ ] Review what SessionStart hook responses can do (inject context? auto-continue?)
  - [ ] Review what UserPromptSubmit hook responses can do
  - [ ] Identify if any hook response type can trigger agent action
  - [ ] Document findings

- [ ] **Task 1.3**: Build throwaway prototype
  - [ ] Create minimal handler that detects post-clear text
  - [ ] Test whether injecting context/instructions via hook response triggers action
  - [ ] Document what works and what doesn't
  - [ ] Clean up prototype

### Phase 2: Proper Implementation (after prototype validates approach)

- [ ] **Task 2.1**: Design handler based on Phase 1 findings
  - [ ] Choose event type and hook response mechanism
  - [ ] Define matching logic (how to detect post-clear vs normal session)
  - [ ] Define response format
  - [ ] Determine priority and terminal behaviour

- [ ] **Task 2.2**: TDD implementation
  - [ ] Write failing tests for matches() - positive cases (post-clear with text)
  - [ ] Write failing tests for matches() - negative cases (normal session, clear without text)
  - [ ] Implement matches() to pass tests
  - [ ] Write failing tests for handle() - expected response
  - [ ] Implement handle() to pass tests
  - [ ] Refactor

- [ ] **Task 2.3**: Integration & QA
  - [ ] Register handler in config
  - [ ] Run full QA suite: `./scripts/qa/run_all.sh`
  - [ ] Daemon restart verification
  - [ ] Live testing with `/clear <instructions>`

## Technical Decisions

### Decision 1: Which hook event to use
**Context**: Need to determine where post-clear text appears
**Options Considered**:
1. SessionStart - fires on new session, may contain initial context
2. UserPromptSubmit - fires when user prompt is submitted, may carry the text

**Decision**: TBD - Phase 1 investigation will determine this

### Decision 2: How to trigger agent action
**Context**: Need the agent to automatically act on the text
**Options Considered**:
1. Inject system-reminder context that says "execute the following instruction: ..."
2. Use a hook response type that auto-continues
3. Other mechanism TBD from investigation

**Decision**: TBD - Phase 1 investigation will determine this

## Success Criteria

- [ ] Post-clear text is detectable in hook events
- [ ] Agent automatically acts on `/clear <instructions>` without manual "go"
- [ ] Normal `/clear` (no text) behaviour unchanged
- [ ] Normal session starts unaffected
- [ ] All QA checks pass
- [ ] Handler has 95%+ test coverage

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Post-clear text not visible in any hook event | High | Medium | May need to explore alternative approaches or accept limitation |
| Hook response can't trigger agent action | High | Medium | Investigate all response types; may need feature request to Claude Code |
| False positives on normal session starts | Medium | Low | Careful matching logic to distinguish post-clear from normal |

## Notes & Updates

### 2026-03-11
- Plan created
- Starting with Phase 1 investigation to validate the approach before committing to full implementation
