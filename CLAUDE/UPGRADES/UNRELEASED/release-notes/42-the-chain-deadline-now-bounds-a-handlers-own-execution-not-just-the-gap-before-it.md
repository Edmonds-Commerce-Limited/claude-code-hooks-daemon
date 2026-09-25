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

Two changes close this:

- Every handler's own call is now individually bounded too (`core.bounded_ dispatch.BoundedDispatcher`): it runs on its own daemon thread and the
  chain waits on it for at most the REMAINING deadline budget, not however
  long the handler's own code takes. On expiry the same fail-closed rule
  applies as before — a `SAFETY`+`BLOCKING` handler not judged in time is
  denied, naming the handler; anything else is skipped with an advisory
  note. The overrunning call is not interrupted (Python cannot forcibly stop
  a running thread) — it keeps running on its own daemon thread, logged
  again at WARNING whenever it does eventually finish, and never blocks the
  daemon process's own shutdown. Concurrency is bounded (16 calls at once,
  by default): a call beyond that is refused outright and treated the same
  way as a timeout, rather than queued.
- `daemon.chain.max_safety_input_bytes` (default 2 MiB) is new: defence in
  depth alongside the deadline. A `SAFETY` handler whose Bash `command` or
  Write/Edit content exceeds it is denied (or skipped) BEFORE dispatch is
  even attempted, so a truly pathological payload fails fast rather than
  paying dispatch overhead only to be cut off by the deadline anyway. This
  is not the only guarantee — the per-handler deadline bound above already
  caps worst-case wall clock regardless of size — so raising or disabling
  it (`null`) is safe as long as `deadline_seconds` stays enforced.

If your own security review or documentation ever assumed the chain
deadline could only be exhausted by handlers running BEFORE the slow one,
re-check that claim: before this fix, a single slow handler with nothing
ahead of it in priority order was not bounded at all.
