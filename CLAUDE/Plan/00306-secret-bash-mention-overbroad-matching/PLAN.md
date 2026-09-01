# Plan 00306: secret bash mention overbroad matching

**Status**: Not Started
**Created**: 2026-09-01
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

While fixing Plan 00305 Task 2.5 (secret_file_guard Edit-path false positive
on the Python list literal `[pass_result, fail_result]`), the implementing
agent repeatedly tripped `R-SECRET-BASH-MENTION` on Bash commands containing
plain words with "secret" in them — no `.secret` path literal, no protected
file named. That is the same over-broad-matching defect class as Task 2.5,
but in the Bash-mention detection path rather than the Edit/new_string path,
so it was out of that task's scope and is ledgered here instead (Plan 00157
"never drop a finding").

A guard that false-fires on ordinary words invites being disabled, which
costs more than the false positive itself — the fix must tighten matching
without weakening genuine protected-path detection.

## Goals

- Reproduce the false positive with a pinned failing test (a Bash command
  mentioning a plain word containing "secret" that names no protected path).
- Tighten the Bash-mention matching so plain-word substrings do not match
  protected-path globs, while all existing genuine-mention tests stay green.

## Non-Goals

- Revisiting the Edit-path matching (fixed in Plan 00305 Task 2.5).
- Weakening any deny that fires on a genuine protected-path mention.

## Tasks

### Phase 1: Reproduce and fix

- [ ] ⬜ **Task 1.1**: Reproduce the false positive from the Plan 00305
  journal context (grep/utility commands whose text contained plain words
  with "secret") and pin it with a failing unit test against the
  Bash-mention matching path.
- [ ] ⬜ **Task 1.2**: Tighten the matching (likely the same
  complete-bracket/glob-shape discipline applied in
  `utils/secret_file_matching.py` for Task 2.5) so the pinned test passes
  with the full existing secret_file_guard suite green.

## Success Criteria

- [ ] False positive pinned and fixed with TDD; full QA green; daemon
  restarted and verified.

## Delivery & Milestones

- <!-- milestone or delivery commit hash -->
