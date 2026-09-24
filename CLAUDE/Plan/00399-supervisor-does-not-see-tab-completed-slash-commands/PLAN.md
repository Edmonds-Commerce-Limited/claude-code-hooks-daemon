# Plan 00399: supervisor does not see tab completed slash commands

**Status**: Blocked
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

- [x] ✅ **Task 1.1**: RULING NEEDED between:

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

  **Decided (unattended, 2026-09-24)**: option 2. The daemon's `PreCompact`
  record is authoritative, needs no command list, and cannot give a false
  positive, following the Plan 00328 precedent. Assumption: the owner's 'no
  known defects' instruction; the owner can reverse this with one message.

  What that builds, checked against today's code (the supporting
  [decision document](fable-compact-detection-decision.md) had recommended
  option 3):

  - The record already existed and the supervisor already read it:
    `compaction_signal` wrote `<session>.compacting` on every `PreCompact`, and
    `load_compaction_signal` fed `reading.compacting`, whose branch runs before
    any state-machine logic. A Tab-completed `/compact` at an idle prompt was
    therefore already deferred to correctly: the human's own Enter holds `idle`
    False for 2 s, and `PreCompact` lands inside that window.
  - What was missing was the half of option 2 that REPLACES keystroke
    inference: the record said "a compaction", never whose. It now carries
    `trigger` and an `origin` (`human`, `supervisor`, `auto`) that the daemon
    attributes from `trigger` plus whether `custom_instructions` starts with
    the supervisor's `🤖 [ccy-supervisor` prefix. The human's own instruction
    text is never written. The supervisor reads `origin` and names it on the
    resume, so a Tab-completed `/compact` shows in `decision.log` as
    `compaction detected (human /compact)`, recognised from the record while
    the keystroke match saw nothing.
  - The keystroke match stays exact (option 1 stays rejected). It still
    defers a fully typed `/compact` that is QUEUED behind a streaming turn,
    which is the one window `PreCompact` cannot cover.
  - **Limit, stated rather than hidden**: `PreCompact` fires at compaction
    START, and no hook fires when a built-in `/compact` is submitted.
    Evidence: at 15:52:20.90 the supervisor typed `/compact` and `PreCompact`
    followed at 15:52:20.97 with no `UserPromptSubmit` between them
    (`untracked/logs/hooks/verdicts.jsonl`); `UserPromptExpansion` covers
    only skill and custom commands. So a Tab-completed `/compact` queued
    behind a streaming turn is still unseen until it runs, and in the
    elevated or critical band the supervisor may type its own `/compact` in
    that window. The cost is the one PLAN.md already accepts: a duplicate,
    never a missed compaction.

### Phase 2: Establish whether tmux changes the byte stream

- [ ] ⬜ **Task 2.1**: The ccy session is now wrapped in tmux on the host —
  confirmed by `TERM` inside the container changing from `xterm-256color` to
  `tmux-256color`. tmux is NOT in the injection path, but it IS in the input
  path, which is the path this plan is about. The pre-tmux captures are on
  record above, so the next Tab-completed `/compact` typed under tmux yields a
  directly comparable diagnostic line. Identical means tmux changes nothing
  here; different means any fix must account for its key re-encoding.

  **Needs a human, and only this task does**: the capture is a person typing
  `/comp`, pressing Tab and Enter in the real tmux-wrapped ccy session. No agent
  can press keys on the host terminal, and a synthetic byte stream would test
  the recogniser rather than tmux. Where to read the result: the
  `diagnostic typed-slash observed` line in
  `untracked/claude-supervise-worker.err.log`, and the matching
  `compaction detected (human /compact)` line in
  `untracked/supervise/decision.log`, which should now appear however tmux
  encodes the keys. Since the ruling this task gates nothing: the record does
  not come from the input path at all.

  **Blocked on this task alone.** Everything an agent can do shipped with B1
  (2e6483a3). The plan waits for the owner to make the capture above, then
  closes.

## Success Criteria

- [x] A Tab-completed `/compact` either defers the supervisor correctly, or the
  project has recorded a decision not to support it and why. Recognised from
  the daemon's record once it starts; the queued window is recorded as the
  accepted limit (Task 1.1).
- [x] Whatever is chosen is covered by a test that fails against today's code:
  `tests/unit/supervise/test_compaction_origin.py` and the origin tests in
  `tests/unit/handlers/pre_compact/test_compaction_signal.py`.
- [x] No fix widens the match in a way that can produce a FALSE recognition,
  which costs more than the bug it repairs. Guarded by
  `test_keystrokes_without_the_whole_word_are_not_a_compact`.
- [x] Full QA passes and CI is green. Landed with integration batch B1
  (2e6483a3); CI green on d23b56f0.
- [x] Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/18-a-tab-completed-compact-is-recognised-from-the-daemon-record.md`.

## Delivery & Milestones

- Graduated from Plan 00397 N1, found while investigating an unrelated report
  that supervisor compaction had stopped working.
