# Decision: a Tab-completed `/compact` (Task 1.1)

Supporting document for [PLAN.md](PLAN.md) Phase 1. It records the ruling
between the three options at PLAN.md:54-73, the evidence, the cost, the best
case against, and whether any owner-only question remains.

> **Superseded as the ruling.** Task 1.1 was decided as option 2, not the
> option 3 recommended below; PLAN.md Task 1.1 records the ruling and what it
> built. The evidence here stands, including the queued-window limit, which
> the built option 2 carries as its stated limit.

## The decision, in one sentence

**Option 3 — accept the blind spot: keep the exact-prefix recogniser as it is,
do not widen it, and do not build option 2, because the part of option 2 that
is buildable is already built and the part that would replace the recogniser
cannot be.**

## First, what the recogniser is actually for

The keystroke path (`.claude/ccy/claude-supervise.py:762-768`,
`:838-841`, `:858-867`) exists so that a human `/compact` moves the machine to
`AWAIT_COMPACTING` **without injecting** (`:4399-4407`), so the supervisor never
stacks a second `/compact` on the human's. That is the only thing it does.

The daemon's `PreCompact` record already covers everything from compaction
START onwards: `compaction_signal.py` writes `<session>.compacting` on every
compaction "whether triggered by the PTY supervisor's `/compact` OR typed
manually by the human" (`compaction_signal.py:3-7`), the supervisor reads it as
an independent input (`claude-supervise.py:2479-2515`, `:5096-5119`), and the
`compacting` branch runs BEFORE any state-machine logic (`:4359-4394`), so once
the signal lands no `WOULD_COMPACT` can be decided. A second, host-side guard
suppresses a stale `WOULD_COMPACT` when the host is already awaiting
(`:6074-6080`).

So the recogniser's whole marginal value is the window **between the human's
Enter and `PreCompact` firing**. That window has two shapes:

- **Idle session, `/compact` runs at once.** `PreCompact` fires within hook
  dispatch latency. The supervisor polls every 2 s (`:4874`) and `idle`
  requires no stdin byte for 2 s (`:4875`, `:4992-5000`) — the human's own
  Enter holds `idle` False across that whole window. The recogniser adds
  nothing here.
- **Streaming turn, `/compact` is QUEUED.** Claude Code runs it when the turn
  ends, so `PreCompact` fires minutes later. If the context is in the
  elevated or critical band (which ignores `work_idle`, `:4475-4477`), the
  cooldown has elapsed (300 s, `:1139`; bypassed at critical) and 2 s have
  passed since the Enter, the supervisor injects its own `/compact`. This is
  the only window where the recogniser earns its keep, and it is the window a
  Tab-completed `/compact` falls through.

## Why option 2 is not available as a replacement

Option 2 is phrased as "read the fact from the daemon's own `PreCompact`
record". `PreCompact` fires when compaction **starts**
(`untracked/hooks-raw.md:3023-3046` — it carries `trigger: manual|auto` and
`custom_instructions`). It is structurally silent during the queued window,
and no other hook fires for a queued built-in slash command either. There is
therefore no daemon-side event that could deliver "a human has submitted a
`/compact` that has not yet begun". The consumer of the fact the daemon CAN
supply already exists (`reading.compacting`). An option that cannot be built
is not an option; option 2 collapses into "delete the recogniser and accept
the queued-window duplicate", which is option 3 with less code — and the
recogniser is correct and cheap when the human types the whole word, so
deleting it buys nothing.

One thing option 2's shape COULD add is attribution of a compaction to the
human via `trigger=manual` plus a `custom_instructions` that lacks the
supervisor's bot prefix (`:4918-4920`). It is not needed: `_await_is_human`
only governs the ESC-flush inside `AWAIT` (`:4502-4505`), and once a
compaction is observed the machine resets to `MONITOR` (`:4390`), so the flag
is moot by the time the daemon could inform it.

## Why option 1 is rejected, and the asymmetry that decides it

Option 1 resolves `/comp` to `/compact` "while it is the unique match". Four
problems, the last of which is disqualifying:

1. The list is Claude Code's, not ours, and it includes project skills: this
   repository alone contributes `configure` and `code-review`, so `/co` is
   already ambiguous and the uniqueness boundary moves whenever a skill is
   added anywhere in the stack.
2. Tab-completion picks Claude Code's FIRST match in ITS ordering, then the
   human may arrow to another. The supervisor cannot observe either.
3. A human who types `/comp` and presses Enter WITHOUT Tab has submitted an
   unknown command, not a compaction. Prefix matching reads it as one.
4. **The false-positive cost is the expensive direction** (PLAN.md:68-72). A
   false recognition enters `AWAIT_COMPACTING` with `is_human=True`; the
   machine then returns `NOOP "awaiting human compaction start"` on every tick
   (`:4504-4505`) and never fires the ESC-flush, until `await_timeout_seconds`
   (120 s, `:1140`, `:4592`) returns it to `MONITOR`. For those two minutes no
   supervisor compaction can fire at any band, including CRITICAL — which is
   the same shape as the Plan 00398 incident the project just repaired. A
   missed recognition, by contrast, costs one duplicate `/compact` that Claude
   Code aborts.

The precedent settles what the arithmetic already says. Plan 00328 faced the
same shape for `/model`: a stem match on keystrokes (`'/moBBA'`) misread the
picker and drove a futile restore, a coupled `/effort`, and an unrequested
`/compact`. The ruling was not to widen the match but to delete the
keystroke-derived recognition entirely and arm on a positively attributed
machine signal (`Completed/00328-…/PLAN.md:100-111`,
`DETECTION-CHANNELS.md:7-26`). Widening a stem match is precisely the move
00328 rejected. Reading Claude Code's rendered input box from child OUTPUT
would work, and is also excluded by that plan's non-goals
(`00328/PLAN.md:50-53`, Plan 00317's thin-host audit).

## What it costs, and who bears it

- **The cost is borne by the human at the keyboard, and it is bounded.** Under
  the queued-window conditions above, the supervisor types a second `/compact`
  which Claude Code aborts as a duplicate; if no compaction has started after
  60 s (`:1147`) the supervisor's ESC-flush interrupts the in-flight turn,
  which is the behaviour the supervisor would have shown had the human typed
  nothing. The net visible effect is one aborted command line in the
  transcript. It cannot cause a missed compaction (PLAN.md:44-48).
- **Frequency.** The diagnostic log shows three Tab-completed `/compact`
  submissions across five days (PLAN.md:36-40); the duplicate requires the
  band and cooldown conditions to coincide, so three is the upper bound on
  incidents in that period.
- **Nothing to maintain.** No completion list, no daemon change, no new
  supervisor state.

## The strongest argument against, stated fairly

"The recogniser now has a known hole, and a supervisor whose contract says
'never stacks a duplicate' is quietly not honouring it." That is true, and it
is why this document exists rather than the hole being left implicit. The
reply is that the contract can be honoured only by one of two channels — a
keystroke stream that does not carry the completed word, or a hook that does
not fire in the relevant window — and neither can be made to. Recording the
limit is the honest form of the contract. If Claude Code ever exposes the
resolved command at submit time (a `UserPromptSubmit`-shaped event for
built-ins, or a queued-command hook), that record becomes the fix and this
ruling should be revisited; nothing here forecloses it.

## Consequences for the rest of the plan

- **Success criterion 2** ("covered by a test that fails against today's
  code", PLAN.md:88) cannot be met by a decision that changes no code. It
  should be re-read as a characterisation test: feed `/comp`, a Tab byte and
  Enter through `HumanInputLine` and assert `take_compact_submitted()` is
  False and the machine stays in `MONITOR`. It passes today and guards against
  a future well-meant widening — the test that would fail is the one someone
  writes when they widen the match. (This document does not edit PLAN.md; the
  executor should adjust that criterion when picking the plan up.)
- **Phase 2 (tmux)** is unchanged as a diagnostic — the worker's
  `typed-slash observed` line is free — but it gates nothing: whether tmux
  re-encodes input changes what the tap sees, not the fact that Tab emits no
  keystrokes.
- **A note on a citation.** PLAN.md:47 cites "line 3892" for Claude Code
  aborting a duplicate. `claude-supervise.py:3892` is unrelated
  (`_coupled_effort_pending`); the reference is to Claude Code's own source,
  not this repository, and should be read that way.

## Does a genuine human gate remain?

**No.** The choice turns on three facts that are all in the repository or the
vendored contract: `PreCompact` fires at compaction start, so no daemon record
exists in the queued window (`hooks-raw.md:3023-3046`); a false recognition
silences supervisor compaction for 120 s at every band (`:4504-4505`,
`:1140`); and Plan 00328 already ruled against widening keystroke inference
for this exact class. Nothing here depends on the owner's risk appetite — the
accepted cost is an aborted duplicate line, which is not a risk — or on any
commitment to users. Task 1.1 can be marked decided on the strength of this
document.
