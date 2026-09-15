# Callout: the must-do list can arrive as a turn, not as session-start context

**Plan**: 00416
**Audience**: everyone

Tagging session-start messages with a computed tier (callout 04) makes the
must-do set short and nameable. It does not make it get read — injected
context is scenery, and an agent weighs it as background because that is what
it is. What changes the outcome is the CHANNEL: a single line typed into the
chat as a real turn gets the whole start-up block worked through, where the
block itself did not.

`session_actions_directive` closes that gap. When a session starts with one or
more `ACTION_REQUIRED` items, the daemon drops a `<session>.session-actions`
signal and the ccy supervisor types one short directive naming the count and
pointing at `hooks-daemon session-actions`.

**The signal carries a number and nothing else.** Not a message, not a
rendered line — a positive integer count, which the supervisor interpolates
into a fixed template it owns. This is the `operator-signal` shape rather than
the `goal-intent` one: a channel with no text to forge cannot be talked into
typing prose, now or after a future widening. A signal file carrying extra
fields renders exactly the same sentence.

Three conditions gate it, and all three must hold: a SessionStart verifier is
currently failing, an armed ccy supervisor is live to read the signal, and the
handler is enabled. It is **opt-in** — it types into your terminal, so you
choose it:

```yaml
handlers:
  session_start:
    session_actions_directive:
      enabled: true
      priority: 72
```

It adds nothing to the session-start block itself. The whole value is the
second channel, so saying it in both would dilute both.
