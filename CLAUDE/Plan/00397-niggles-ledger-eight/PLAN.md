# Plan 00397: niggles ledger eight

**Status**: In Progress
**Created**: 2026-09-13
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The open ledger for small defects. Ledger seven (00393) closed when both its
entries were resolved, and SOP is that the next niggle found opens a NEW ledger
rather than reopening an archived one — so this exists because a niggle was
found, not in anticipation of one.

A niggle is recorded **in the turn it is found**, before the work that surfaced
it continues. The rule exists because the alternative is reporting it in context
output, where it is read once and then lost when the window compacts. Every
entry names what was OBSERVED, not what was guessed.

Entries may be fixed here, or GRADUATED to their own plan when they turn out to
be larger than a niggle. Graduating is a success: the ledger's job is to make
sure nothing is dropped, not to force every fix into one plan.

## Goals

- Every small defect found while doing other work is recorded, with enough
  evidence that someone else could reproduce it.
- Each entry is either fixed here or graduated to a named plan — never dropped.

## Non-Goals

- Batching. An entry is appended the turn it is found; the ledger is never
  "caught up" later from memory.
- Large work. Anything needing its own design graduates to its own plan.

## Tasks

### Phase 1: Entries

- [ ] ⬜ **N1** — A Tab-completed `/compact` is never recognised as a human
  compact, because the raw-input tap only ever sees the bytes the human
  actually typed.

  **Observed**, in the live worker diagnostic log
  (`untracked/claude-supervise-worker.err.log`), twice today and repeatedly
  over the preceding days:

  ```text
  [2026-09-08 13:10:56] '/comp\tok lets continue pruning these plans…' (recognised compact=False)
  [2026-09-13 13:07:49] command='/comp' len=14                          (recognised compact=False)
  [2026-09-13 15:54:42] command='/comp' len=31                          (recognised compact=False)
  ```

  The literal `\t` in the first line is the giveaway: the human types `/comp`,
  presses **Tab**, and Claude Code's own autocomplete expands it to `/compact`
  in its input box. The expansion happens INSIDE Claude Code and produces no
  keystrokes, so the tap — which records bytes forwarded to the child — holds
  `/comp`, never `/compact`.

  **Cause**, `.claude/ccy/claude-supervise.py:751`:

  ```python
  def _buffer_is_compact(self) -> bool:
      text = bytes(self._buffer).decode("utf-8", errors="ignore")
      return text.strip().startswith(_COMPACT_COMMAND_PREFIX)   # "/compact"
  ```

  An exact-prefix match against text the human never typed.

  **What it actually costs, stated precisely, because the obvious reading is
  backwards.** Recognising a human `/compact` makes the supervisor DEFER —
  `handlers` log line "human /compact detected -> awaiting compaction (no
  inject)" — so that it never stacks its own compaction on top. Failing to
  recognise it therefore risks the supervisor injecting a SECOND `/compact`,
  not suppressing one. This niggle does NOT cause missed compactions, and must
  not be written up as though it does.

  **How it was found.** The owner reported that supervisor compacts had stopped
  working and asked whether wrapping ccy in tmux had broken it. Neither turned
  out to be the case (see N2), but reading the worker's diagnostic log to check
  surfaced this.

  **Fix is not obvious enough to apply unilaterally** — matching a `/comp`
  prefix would fire on any future `/comp…` command, and the tap cannot see
  which entry autocomplete actually selected. Needs a ruling; see the journal.

- [x] ✅ **N2** — RESOLVED as NOT A DEFECT, recorded so it is not re-investigated
  from scratch: supervisor auto-compaction is healthy, and tmux is not in the
  path.

  **Observed.** The supervisor host runs `--arm` (real injection, not dry-run),
  its worker is alive, and the sidecar it polls is being written continuously:

  ```json
  {"red": false, "critical": false, "compact_urgent": false, "tier": "yellow",
   "pct": 24.0, "window_size": 1000000, "seq": 16387}
  ```

  Auto-compaction fires at the RED threshold, which for a 1,000,000-token
  window is **40%** (`context_tiers.py:51`). The session is at 24%. There is
  nothing to fire on.

  **Why it reads as "stopped working".** The window is 1M, where red is 400k
  tokens of context; on a 200k window red is 76%, i.e. 152k tokens. A session
  therefore runs roughly 2.6x longer between automatic compactions than it did
  on the smaller window, with no configuration having changed.

  **tmux is outside the container and not in the supervisor's path.** Process
  ancestry inside the container is `tini(1) -> claude-supervise.py(2) -> claude(83)`, with `TMUX`/`TMUX_PANE` unset and no tmux server socket. Any
  tmux wraps the container's stdio from the outside; it does not sit between
  the PTY host and its child. The `/comp` truncation in N1 is also visible
  from 2026-09-08, so it predates any recent change of terminal wrapper.

## Success Criteria

- [ ] Every entry above is fixed with a regression test, graduated to a named
  plan linked from the entry, or — the third outcome, added because N2 is one —
  investigated to a conclusion of NOT A DEFECT with the evidence recorded, so
  the question is answered once rather than re-opened by the next reader.
- [ ] No entry is closed on reasoning alone. N2 was closed on the decision log
  (176 historical compact injections, the most recent firing at 50% the day
  before), a live sidecar reading of 24% against a 40% red threshold, and the
  in-container process ancestry — not on an argument that it ought to be fine.

## Delivery & Milestones

- Opened because ledger 00393 closed and a new niggle was found, per the SOP in
  `CLAUDE/core/PlanWorkflow.core.md`: "The next niggle found opens a NEW ledger.
  Never reopen a closed one."
- **Close this ledger when its entries are resolved.** Do not hold it open as a
  standing fixture.
