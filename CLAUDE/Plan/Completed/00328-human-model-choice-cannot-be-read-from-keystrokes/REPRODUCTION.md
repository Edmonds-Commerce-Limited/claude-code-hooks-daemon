# Live reproduction — 2026-09-04, exhausted-fable account

Captured during a deliberate dogfood. The owner switched this session onto a
Claude account whose **Fable allowance was exhausted**, so the conditions were
real rather than simulated.

The human performed **one** action: `/model` → picked Opus. Everything else
below was typed into the PTY **by the supervisor**.

## Raw Claude Code output, as the human saw it

Supervisor injections are indistinguishable from typed input on screen — they
go to the same PTY — which is why the transcript reads as though the human ran
all of these.

```
❯ ok this session is now on an exhausted fable and shjould bounce down automatically
  ⎿  You've reached your Fable limit. /model to switch models.
     /upgrade to increase your usage limit.

✻ Cooked for 1s · done 7:58 AM

❯ acutaly no it requires manual model switch apparently?
  ⎿  You've reached your Fable limit. /model to switch models.
     /upgrade to increase your usage limit.

✻ Brewed for 1s · done 7:58 AM

❯ /model
  ⎿  Set model to Opus 5 and saved as your default for new sessions

❯ /effort xhigh
  ⎿  Set effort level to xhigh (saved as your default for new sessions): Deeper reasoning than high, just below maximum (Fable 5, Opus 4.7+, Sonnet 5)

❯ /model fable
  ⎿  API error: 429 {"type":"error","error":{"type":"rate_limit_error","message":"This request would exceed your account's rate limit. Please try again later."},"request_id":"req_011Cei3ZVfbxsY5Q9vaZDVin"}

❯ /effort low
  ⎿  Set effort level to low (saved as your default for new sessions): Quick, straightforward implementation with minimal overhead

❯ OK so bug reproduced
```

Only the `/model` line was the human. `/effort xhigh`, `/model fable` and
`/effort low` were all injected.

## What the supervisor recorded

`untracked/claude-supervise-worker.err.log`:

```
[2026-09-04 07:58:46] diagnostic typed-slash observed: '/moBBA' (recognised model=None picker=False effort=None)
```

`untracked/supervise/decision.log`:

```
2026-09-04T07:57:29 supervisor exiting (ARMED); 451359 input bytes observed
2026-09-04T07:57:56 supervisor active (ARMED); wrapping: ['claude', '--dangerously-skip-permissions', '--continue']
2026-09-04T07:58:48 noop: model restore pending but session busy
2026-09-04T07:58:51 would-effort: effort below floor (…:opus:xhigh) -> injected '/effort xhigh'
2026-09-04T07:58:54 would-model: downgrade quiet delay elapsed -> injected '/model fable'
2026-09-04T07:58:56 would-effort: model switch requires coupled effort (…:fable:low) -> injected '/effort low'
2026-09-04T07:58:58 would-compact: repeated downgrade (flip-flop) -> injected flag-cleaning '/compact …'
```

## The failure chain

1. **The human's choice was invisible.** The observed keystrokes were
   `'/moBBA'` — `/mo`, then Down, Down, Up (CSI arrows appended as literal
   `B`,`B`,`A`), then Enter. No family, no recognisable command:
   `model=None picker=False`. Recognition had nothing to work with.
2. **The drop was in scope, correctly.** fable → opus is exactly the shape the
   auto-restore exists for, so the Plan 00327-era scope narrowing does not and
   should not save this case. Only human-choice recognition could have.
3. **The restore was injected and failed** — `/model fable` returned HTTP 429.
   The account cannot serve fable at all.
4. **The coupled effort fired for a switch that never happened**, dropping
   effort to fable's floor while the session was still on opus.
5. **A `/compact` was injected.** `flag_compact_due` reads "a restore fired and
   the episode is still open" as a downgrade flip-flop. Here the episode was
   still open because the restore had *failed*, not because a classifier
   re-fired. The owner escaped it manually; unattended it would have destroyed
   the session context.

## Why the existing recognition could not have worked

Four input shapes were observed across one morning of dogfooding. Two are
unparseable by any rule over the typed text:

| What the human did           | Bytes the PTY carried | Recognised?         |
| ---------------------------- | --------------------- | ------------------- |
| typed `/model fable`         | `/model fable`        | yes                 |
| bare `/model`, then picked   | `/model `             | yes (`picker=True`) |
| `/mo` + Down + TAB + `fable` | `/moB\tfable`         | no                  |
| `/mo` + Down + Down + Up     | `/moBBA`              | no                  |

Claude Code renders autocomplete and the model picker in its **own UI, above
the PTY**. The completed word never crosses it. Arrow-key navigation carries
no text at all. Plan 00316 built recognition on this channel; this
reproduction shows the channel cannot carry the signal.

## Signals that DO exist

- **`~/.claude/settings.json`.** Every human `/model` writes the family
  there ("saved as your default for new sessions"). Verified after this
  reproduction: `{"model":"opus"}`, mtime 07:58:56 — the **failed** `/model fable` did NOT write `fable`, so the file tracks what actually took effect.
  Caveat: it is a user-level file shared by concurrent sessions, and the
  supervisor writes it too via its own injections (it knows when it does).
- **Claude Code's own message**: `You've reached your Fable limit.` The PTY
  host sees all child output — but `OutputActivity.record` only counts bytes
  and timestamps, never content, and Plan 00317's audit deliberately keeps the
  host tier thin. Adding content inspection there is a real architectural
  cost.
- **The outcome of the restore itself.** After injecting `/model fable`, the
  next reading either shows fable or it does not. Here it did not. This needs
  no new input channel at all.
