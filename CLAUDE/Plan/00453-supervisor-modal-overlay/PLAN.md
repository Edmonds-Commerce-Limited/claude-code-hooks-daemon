# Plan 00453: supervisor modal overlay

**Status**: Not Started
**Created**: 2026-09-22
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Direct (main session, dogfooded live)

## Overview

The supervisor has exactly one glance-able output surface: the transient
status-line banner built as a general, reusable channel by
[Plan 00173](../Completed/00173-supervisor-ctrlz-guard-and-status-message/PLAN.md)
and adopted for the audit trail by
[Plan 00318](../Completed/00318-supervisor-audit-via-status-line-banner/PLAN.md).
That channel works and this plan does not replace it. It is, however, a
**one-line, TTL-expiring notification** — it can say *what just happened*, and
it is deliberately sized so it cannot say anything else. It cannot hold a
history, it cannot be scrolled, and once the TTL lapses the notice is gone
whether or not anyone was looking at the terminal.

Two pressures make that insufficient. First, the status line is **contended
real estate** — the supervisor banner shares it with every other status
segment, and the prompt-cache work in
[Plan 00452](../00452-prompt-cache-observability-and-invalidation-protection/PLAN.md)
adds more. Every new thing worth glancing at makes the line worse for
everything already on it. Second, and more fundamental: *"why did the
supervisor do that?"* is an **inspection** question, not a notification one.
The durable answer already exists in `decision.log`, but reading it means
leaving the session, and the only in-session route to supervisor state is to
ask the agent — which spends a model turn and lands in the transcript forever,
the precise cost Plan 00318 was written to escape.

This plan adds a **second surface with a different job**: an overlay the
operator summons with a hotkey, which paints over the terminal, shows
supervisor state and recent decision history, and disappears on any key —
consuming no status-line space, no context, and no model turn. The banner stays
the notification channel; the overlay becomes the inspection channel.

## Substrate: what the supervisor already does

Established by reading `.claude/ccy/claude-supervise.py` (7,487 lines), not
assumed. These are the facts the design rests on:

- The supervisor is a PTY host that **forwards operator stdin to the child
  byte-for-byte**, and puts the outer terminal in raw mode (`termios`, `tty`).
  So it already sees every keystroke before Claude Code does.
- `RawInputTap` is a bounded, fail-open buffer of forwarded stdin bytes,
  drained once per tick into `TickFacts.human_raw_input`. **This is the
  interception point** — it exists and is already wired.
- `HumanInputLine` is a streaming, state-machine ANSI parser that already has
  an explicit `_ST_SS3` state and `_SS3_INTRODUCER = 0x4F`. **Function keys are
  already parsed today** and deliberately consumed as non-content, because
  counting their bytes once wedged the injection guard for a whole session
  (v3.34.1 field report). An overlay hotkey therefore *intercepts* a sequence
  the parser already recognises rather than teaching it a new one.
- Swallowing a keystroke instead of forwarding it is **existing, proven
  practice**: the Ctrl+C double-press gate returns `(b"", …)` to drop a lone
  `0x03`, and the Ctrl+Z guard strips `0x1a` outright.
- Nothing in the file references `smcup`, `rmcup`, the `1049` alt-screen
  private mode, or `tmux`. The rendering half is genuinely new.

## The open question the owner must settle

**Which hotkey?** The owner has ruled out **F12** explicitly. **F3** was
floated (*"3 is c for claude"*) and then also set aside. The residual candidate
is **F5**, on the grounds that it has a single encoding across terminals — but
that claim is *recalled, not verified*, and Task 1.1 exists to verify it rather
than to act on it.

The risk being managed is specific: F1–F4 are the multi-encoded range (SS3
`ESC O P..S` in some terminals, CSI `ESC [ 1 N ~` in others, and a third form
on the Linux console), and `ESC O R` for F3 sits one introducer byte away from
the CSI cursor-position report `ESC [ … R` that the parser also consumes. A
hotkey that decodes differently per terminal is a hotkey that silently fails
for some operators, which is worse than no hotkey at all.

## Goals

- The operator can summon supervisor state with one keypress, with **zero**
  model turns, zero transcript entries and zero context cost.
- The overlay shows current supervisor state **and** recent decision history —
  the thing the one-line banner structurally cannot do.
- Dismissal restores the terminal exactly, including the cursor position and
  any partially-typed input box content.
- The chosen hotkey is verified against the terminals actually in use, not
  assumed from a table.
- The status line gains no new permanent segment.

## Non-Goals

- **Not replacing the status-line banner.** Plan 00318's channel remains the
  notification surface; this is inspection. Both ship.
- **Not a second input channel into the agent.** The overlay reads supervisor
  state and never injects into the conversation — the closed-by-default shape
  Plan 00417 established for host→agent signals is not being widened here.
- **Not a TUI.** No editing, no scrollback search, no mouse. Paint, read,
  dismiss.
- **Not a `tmux` dependency.** If `tmux display-popup` is used at all it is an
  enhancement on top of a renderer that works without it.

## Tasks

### Phase 1: Settle the hotkey empirically

- [ ] ⬜ **Task 1.1**: Capture the actual byte sequence each candidate key emits
  in every terminal the owner uses (`showkey -a`, or `cat -v`), including
  inside and outside `tmux`. Record the raw bytes per key per terminal in a
  supporting document — this is the evidence the choice rests on.
- [ ] ⬜ **Task 1.2**: Confirm the candidate is not already consumed by Claude
  Code itself, by the terminal emulator, or by a `tmux` binding. A key the
  child wants is not available however cleanly it decodes.
- [ ] ⬜ **Task 1.3**: Record the ruling — chosen key, rejected keys, and the
  measured reason for each rejection. F12 and F3 are already rejected;
  capture *why* so the question is not reopened from memory.

### Phase 2: Interception

- [ ] ⬜ **Task 2.1**: Recognise the chosen sequence in the forwarded-stdin
  path and swallow it, following the Ctrl+C gate's established
  swallow-and-report shape rather than inventing a new one.
- [ ] ⬜ **Task 2.2**: Prove the sequence is swallowed when **split across
  `read()` chunks**. The parser is streaming and a function key is 3–5
  bytes; a chunk boundary mid-sequence is the realistic failure, so it is
  the test that matters.
- [ ] ⬜ **Task 2.3**: Prove a swallowed hotkey never marks the input box
  non-empty. This is the v3.34.1 wedge, and it is the regression with the
  worst blast radius — every injection tick deferred forever.

### Phase 3: Rendering and restoration

- [ ] ⬜ **Task 3.1**: Render via the alt-screen private mode (`ESC [ ? 1049 h`
  / `l`), which saves and restores the primary screen as one operation.
- [ ] ⬜ **Task 3.2**: Handle a window resize while the overlay is up, and a
  terminal too small to hold the content.
- [ ] ⬜ **Task 3.3**: Guarantee restoration on **abnormal** exit — supervisor
  crash, worker crash, `SIGTERM`. A terminal left on the alt screen with
  raw mode set is an unusable terminal, so the teardown must not depend on
  the happy path.
- [ ] ⬜ **Task 3.4**: Decide whether `tmux display-popup` is worth supporting
  as a detected enhancement, or whether one renderer is the better trade.

### Phase 4: Content

- [ ] ⬜ **Task 4.1**: Define what the overlay shows: armed/disarmed state,
  current goal, last N `decision.log` entries, worker health, tick cadence.
- [ ] ⬜ **Task 4.2**: Source every field from state the supervisor already
  holds. If a field needs new plumbing, that is a signal to drop the field.
- [ ] ⬜ **Task 4.3**: Bound the read — `decision.log` is append-only, so the
  overlay tails it rather than reading it whole.

## Success Criteria

- [ ] The hotkey is chosen from measured bytes, and the measurements are in the
  repository.
- [ ] Pressing it paints the overlay; any key dismisses it; the underlying
  screen and a partially-typed input box are byte-identical afterwards.
- [ ] Killing the supervisor with the overlay up leaves a usable terminal.
- [ ] A hotkey split across read chunks is still swallowed, and never marks the
  input box non-empty.
- [ ] Summoning and dismissing the overlay produces no transcript entry, no
  model turn, and no new status-line segment.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00453-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Not started. Phase 1 gates everything else: the hotkey is an owner decision
  backed by measurement, and Phases 2–4 are unbuildable until it is settled.
