# Plan 00298 — Brainstorm: failsafe cron cadence under stable human-blockage

## The incident, restated precisely

Plan 00297 finished and the session became blocked **only** on two owner
decisions — a stable state, not a transient stall. The hourly failsafe
recovery cron (`recovery_cron_advisor`, canonical prompt in
`src/claude_code_hooks_daemon/handlers/post_tool_use/recovery_cron_advisor.py`)
then fired roughly 14 consecutive times overnight. Each tick delivered the
canonical prompt to the model, which correctly produced:

```
STOPPING BECAUSE: failsafe cron tick, nothing to resume ... blocked only on
human input. Waiting.
```

`auto_continue_stop.py` Branch 2 (`_STOP_EXPLANATION_PREFIX` match, see
`handle()` lines ~489-513) allows this stop cleanly — there is no deny-loop,
no repeated turns per tick. The waste is not in the stop hook at all: it is
that **every tick costs one full model turn** (prompt in, generation out,
transcript write, stop-hook round trip) to produce a guaranteed no-op. The
cron's own canonical prompt text explicitly forbids deleting the cron for
this reason ("Do NOT delete this cron merely because a tick finds nothing to
resume ... a still-live session stays exposed to the next rate limit without
it") — so the current design has no lever between "keep paying full hourly
cost forever" and "delete and lose all recovery coverage."

## Why this matters (and why it's stable, not incidental)

The cron exists to recover from **external** interruptions: API errors, rate
limits, 5-hour usage limits, network failures. A session blocked only on
human input is not any of those — it is waiting for something the cron
cannot supply (a message from the owner). Once in that state, every future
tick is *provably* a no-op until either (a) the owner responds — which
independently wakes the session via a normal user turn, cron or no cron — or
(b) an external interruption occurs, which is a different, real state the
cron should still catch. So the two states genuinely warrant different
cadence, and detecting the transition between them is well-defined: it's
exactly the "STOPPING BECAUSE: blocked only on human input" moment the model
already narrates every time.

## Ideas evaluated

### 1. No-op streak backoff (session/agent-side, convention only)

After N consecutive cron ticks with nothing to resume, the agent
CronDelete+CronCreate at a longer interval (e.g. 1h → 4h → 12h), resetting to
1h on any real recovery. Cheap to describe, zero daemon changes.

**Trade-off**: entirely convention-enforced. Nothing stops a future agent
turn from skipping the backoff logic (it competes with every other
instruction in context), and it still costs one full model turn *per tick*
to decide "still nothing, widen the interval" — better cadence, but not
zero-token. Also the canonical prompt text currently says NOT to delete the
cron on a no-op, so this would need a companion edit to that prompt to avoid
contradicting itself.

### 2. Daemon-side suppression at the prompt-submission boundary (zero-token)

Claude Code's `UserPromptSubmit` hook event fires *before* the prompt reaches
the model; a `deny`/block decision there can short-circuit delivery entirely
— no model turn is spent. If the daemon recognises (a) the incoming prompt
text as the canonical cron prompt (verbatim match, already defined as
`_CANONICAL_CRON_PROMPT` in `recovery_cron_advisor.py` — reusable constant)
**and** (b) a recorded "blocked only on human input" marker is still valid
for this session, it can short-circuit the tick at the hook layer and never
hand it to the model at all. This is the only idea on this list that is
**actually zero-token**, not just cheaper.

**Trade-off**: needs a marker (idea 3) to condition on, and needs to get the
suppression-vs-miss trade-off right (see "failure mode" below). Also needs a
decision on what the hook *returns* in place of the prompt — Claude Code
needs some acknowledgement path so the cron mechanism itself doesn't look
broken; likely a hook-supplied synthetic response, not silence.

### 3. Blocked-state marker recorded by the Stop handler (the enabling primitive)

When `auto_continue_stop.py` Branch 2 allows a stop whose `STOPPING BECAUSE:`
text matches a "blocked on human input" shape (needs a defined pattern set —
"blocked only on human input", "waiting for human", "need user input", etc.,
analogous to the existing `CONFIRMATION_PATTERNS` group), the handler writes
a small persisted marker (session-scoped, similar to the existing
`stop-events.jsonl` / disclosure-tracker persistence already in this file) —
e.g. `{"blocked_on_human_since": <ts>}`. Any **genuine user prompt** (not a
cron tick) clears the marker unconditionally — that's the existing
`UserPromptSubmit` event, trivially distinguishable from a cron-delivered
prompt by matching against the canonical cron text.

This is the cheap, deterministic, daemon-enforceable primitive the other
ideas build on. It is a natural extension of infrastructure already present
in this file (transcript reading, `_log_stop_event`, the disclosure tracker
pattern) — not a new subsystem.

**Trade-off**: false-positive risk on the pattern match (a stop reason that
*mentions* human input but isn't actually a stable blockage, e.g. "STOPPING
BECAUSE: waiting for human review of this PR before merging, but background
polling continues") would incorrectly arm suppression. Needs a conservative,
narrow pattern set, not a broad "input" substring match.

### 4. Cadence baked into the cron prompt itself (convention only)

Same idea as #1 but pushed into `_CANONICAL_CRON_PROMPT` text rather than
left to agent judgement each session. Marginal improvement over #1 (more
consistent phrasing) but the same fundamental limit: still costs a full
model turn per tick to *read* the instruction and decide to act on it, and
still cannot reach zero token cost.

### 5. Distinguish blockage types explicitly (frames the other ideas correctly)

The key insight underlying 2/3: "blocked on human input" and "blocked on an
external interruption" are not the same state and do not deserve the same
cadence. Human-input blockage already self-resolves the instant the owner
sends a message — a real user turn wakes the session with no cron
involvement at all, so the cron adds strictly nothing while that state
holds. External-interruption blockage is exactly what still wants full
hourly (or shorter) coverage, because nothing else will wake the session.
This framing is why suppression can be aggressive for state (a) without
weakening coverage for state (b) — they are different states, not different
confidence levels on the same state.

## Daemon-enforceable vs convention-only, and the over-suppression risk

| Idea                            | Enforcement                    | Token cost per no-op tick      |
| ------------------------------- | ------------------------------ | ------------------------------ |
| 1. Session-side backoff         | Convention (agent must comply) | Still ~1 full turn, less often |
| 2. UserPromptSubmit suppression | Daemon-enforced, deterministic | **Zero**                       |
| 3. Blocked-state marker         | Daemon-enforced, deterministic | N/A (enabling primitive)       |
| 4. Cadence in cron prompt       | Convention                     | Still ~1 full turn, less often |

**The failure mode that matters**: a stale marker suppressing a cron tick
that would have caught a *real* rate-limit recovery. Concretely — marker set
while blocked on human input, owner is slow to respond, and *independently*
an API error also occurs during the wait. If suppression is unconditional
while the marker is set, that tick is silently swallowed and the session
never recovers from the API error until the owner's message arrives anyway
(which does wake it) — so the practical exposure window is bounded by
"however long the owner takes to respond," not unbounded. This is a real but
narrow gap, and it's boundable further: cap how long a marker stays valid
without re-confirmation (e.g. one calendar day), so long silences degrade
back to full coverage automatically rather than staying suppressed
indefinitely.

## Recommendation

Primary: **idea 3 (blocked-state marker on Stop) + idea 2 (UserPromptSubmit
suppression keyed on the canonical cron text)** — the only combination that
is deterministic, daemon-enforced, and genuinely zero-token for the no-op
case, while leaving external-interruption recovery fully intact (a marker
only suppresses ticks that carry the canonical cron prompt verbatim; a real
user message always clears it). Add a conservative expiry on the marker
(e.g. 24h) as the safety valve against the over-suppression failure mode
above, so an extended silence degrades back to full hourly coverage rather
than staying suppressed forever.

Treat idea 1/4 (session-side backoff, prompt-text cadence) as **not worth
building** given 2+3 exist: they cost strictly more (still a full turn per
tick) for strictly less reliability (convention, not enforcement), and would
require rewriting the canonical prompt's current "do not delete" guidance to
avoid self-contradiction. If 2+3 prove harder to land than expected, 1 is
the fallback, not a parallel track.

This plan is design-only (see PLAN.md scope). No daemon source is changed
here.
