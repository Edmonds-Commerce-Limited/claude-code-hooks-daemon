# Plan 00399: supervisor does not see tab completed slash commands

**Status**: Not Started
**Created**: 2026-09-13
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Direct

## Overview

The supervisor recognises a human's typed `/compact` by matching the raw bytes
it forwarded to the child. **Tab autocomplete produces none of those bytes**, so
a `/compact` reached by typing `/comp` and pressing Tab is never recognised.

Graduated from [Plan 00397](../Completed/00397-niggles-ledger-eight/PLAN.md) N1, which
holds the full evidence. Graduated because the obvious fix trades a false
negative for a strictly worse false positive, which is a ruling rather than an
edit.

## The mechanism, established rather than assumed

`.claude/ccy/claude-supervise.py:751`:

```python
def _buffer_is_compact(self) -> bool:
    text = bytes(self._buffer).decode("utf-8", errors="ignore")
    return text.strip().startswith(_COMPACT_COMMAND_PREFIX)   # "/compact"
```

The expansion from `/comp` to `/compact` happens INSIDE Claude Code's own input
box and emits no keystrokes, so the tap's buffer holds `/comp` and the match
never fires. Observed live in the worker diagnostic log, including a captured
literal Tab:

```text
[2026-09-08 13:10:56] '/comp\tok lets continue pruning these plans…' (recognised compact=False)
[2026-09-13 13:07:49] command='/comp' len=14                          (recognised compact=False)
[2026-09-13 15:54:42] command='/comp' len=31                          (recognised compact=False)
```

## The cost runs the OPPOSITE way to intuition

Recognition exists so the supervisor **defers** — it enters AWAIT_COMPACTING
without injecting, so it never stacks a second `/compact` on the human's, which
Claude Code aborts as a duplicate (line 3892). Failing to recognise therefore
risks a DUPLICATE injection. **It cannot cause a missed compaction**, and a
write-up saying otherwise would be a tidy story pointing the wrong way.

## Tasks

### Phase 1: Owner decision

- [ ] ⬜ **Task 1.1**: RULING NEEDED between:

  1. **Match typed prefixes against known completions.** `/comp` resolves to
     `/compact` while it is the unique match. Fixes Tab. The list is a fact
     about Claude Code's current command set, not an invariant this repository
     controls, so it needs maintaining.
  2. **Stop inferring from keystrokes; read the fact from the daemon's own
     `PreCompact` record.** Authoritative, no ambiguity, no command list. Same
     shape as the Plan 00328 ruling that made `/model` restore arm on the
     daemon's `.model-downgrade` signal rather than on typed text — a precedent
     this project already set for exactly this class of inference.
  3. **Accept it.** The cost is a visible, self-limiting duplicate `/compact`,
     and option 2 may subsume it anyway.

  **The asymmetry that makes this a ruling and not an edit**: a missed
  recognition risks one duplicate `/compact`. A FALSE recognition makes the
  supervisor defer to a compaction that is never coming, suppressing real
  auto-compaction until the state clears. Widening the match trades a cheap
  failure for an expensive one.

### Phase 2: Establish whether tmux changes the byte stream

- [ ] ⬜ **Task 2.1**: The ccy session is now wrapped in tmux on the host —
  confirmed by `TERM` inside the container changing from `xterm-256color` to
  `tmux-256color`. tmux is NOT in the injection path, but it IS in the input
  path, which is the path this plan is about. The pre-tmux captures are on
  record above, so the next Tab-completed `/compact` typed under tmux yields a
  directly comparable diagnostic line. Identical means tmux changes nothing
  here; different means any fix must account for its key re-encoding.

## Success Criteria

- [ ] A Tab-completed `/compact` either defers the supervisor correctly, or the
  project has recorded a decision not to support it and why.
- [ ] Whatever is chosen is covered by a test that fails against today's code.
- [ ] No fix widens the match in a way that can produce a FALSE recognition,
  which costs more than the bug it repairs.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Graduated from Plan 00397 N1, found while investigating an unrelated report
  that supervisor compaction had stopped working.
