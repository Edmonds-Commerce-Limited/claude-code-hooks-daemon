# Callout: the chain deadline now bounds a handler's own execution, not just the gap before it

**Plan**: 00466
**Audience**: operators

`daemon.chain.deadline_seconds` (Plan 00466 N25) was checked once per
handler, BEFORE it ran — it bounded the gap between handlers, never a
handler's own `matches()`/`handle()` call. A handler slow enough within its
own call reproduced the exact bypass N25 was built to close: measuring
`secret_file_guard`'s wall-clock while verifying N25 found 48.958s on 4 MB
of Write content, past both the 20s chain deadline and the client's own 30s
socket timeout — with `secret_file_guard` as the FIRST and only matching
handler, nothing ran before it to trip the between-handlers check at all.

Two changes close this, plus one correction to how this note first
described the deny wording and the deadline's actual guarantee:

- Since Plan 00466 N40 M1, the whole per-handler loop for one event is
  dispatched as ONE bounded call on its own daemon thread
  (`core.bounded_dispatch.BoundedDispatcher`) — NOT each handler bounded
  individually as an earlier version of this note said. The chain waits on
  that one call for at most the REMAINING deadline budget, not however long
  the handlers inside it take collectively. On expiry the same fail-closed
  rule applies as before — a `SAFETY`+`BLOCKING` handler not judged in time
  is denied — but the reason now reads `chain: not judged in time`, not a
  per-handler name: the whole chain is one dispatched call, so there is no
  longer a single handler to name at the point of expiry. Anything else not
  yet run is skipped with an advisory note. The overrunning call is not
  interrupted (Python cannot forcibly stop a running thread) — it keeps
  running on its own daemon thread, logged again at WARNING whenever it does
  eventually finish, and never blocks the daemon process's own shutdown.
  Concurrency is bounded (16 calls at once, by default): a call beyond that
  is refused outright and treated the same way as a timeout, rather than
  queued.
- `daemon.chain.max_safety_input_bytes` (default 2 MiB) is new: defence in
  depth alongside the deadline. A `SAFETY` handler whose combined,
  serialised `tool_input` exceeds it is denied (or skipped) BEFORE dispatch
  is even attempted, so a truly pathological payload fails fast rather than
  paying dispatch overhead only to be cut off by the deadline anyway.

**Correction, not a new change: the deadline does NOT cap worst-case wall
clock regardless of size.** A handler that holds the GIL for its whole run —
a single C-level `re` call on a hostile input, measured at up to 73.5s on
two shipped handlers — blocks the deadline's own timed wait along with
everything else on the process, so the deadline cannot fire until the
handler itself returns. The deadline bounds the case where a handler is
merely slow (blocked on I/O, or doing real work across many small steps);
it is not a bound on a single pathological call. Making every SAFETY-
reachable regex genuinely linear, and sweeping for the GIL-starvation shape
specifically (see the harness change in note 41), is the actual defence
against that case; true process-level isolation remains the structural fix
and is out of scope here.

If your own security review or documentation ever assumed the chain
deadline could only be exhausted by handlers running BEFORE the slow one,
re-check that claim: before this fix, a single slow handler with nothing
ahead of it in priority order was not bounded at all. If it assumed the
deadline caps wall clock for ANY handler regardless of what the handler's
own code does, re-check that too — a GIL-holding call is the counter-
example.
