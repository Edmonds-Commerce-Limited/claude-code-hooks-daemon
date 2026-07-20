# Stop hook falsely reports "daemon not running" on long sessions — a client read-timeout on unbounded whole-file transcript parsing

**Component:** `claude-code-hooks-daemon` (client wrapper `init.sh` + built-in Stop handlers + `core/transcript_reader.py`)
**Reported against:** vendored copy at daemon version **v3.44.0** (`.claude/HOOKS-DAEMON.md` header)
**Author:** downstream maintainer of a private consumer project, passing upstream verbatim
**Related upstream-facing tracking:** a related issue in that downstream project (see *References* — same misleading symptom, different root cause)

---

## Executive summary

On a long-running Claude Code session the **Stop** hook begins returning, after ~30 seconds,
`{"decision":"block","reason":"Hooks daemon not running - protection not active"}` — while the
daemon is demonstrably **alive** the whole time (stable PID, socket present, every other event
still served). The message is a **false negative**: nothing is down. The client socket has a
single hard-coded 30-second timeout covering the entire request/response exchange, and on a large
transcript several built-in Stop handlers parse the **entire** transcript file from byte zero,
repeatedly, within one dispatch. Those parses blow the 30 s budget; the client raises
`socket.timeout` and — because the timeout path is not distinguished from a dead socket — emits
the "daemon not running" block. The pain scales purely with transcript size, so it appears only
late in long sessions and misleads operators into restarting a perfectly healthy daemon.

**TL;DR fix:** distinguish *connected-but-slow* from *down* at the client and stop full-parsing
the transcript — give the handlers a bounded `get_last_assistant_text()` (tail read), memoise one
parse per dispatch, and make the timeout message say "a handler exceeded the Ns budget — the
daemon is alive, do NOT restart it".

---

## Symptom

- The Stop hook (`.claude/hooks/stop`) blocks with
  `{"decision":"block","reason":"Hooks daemon not running - protection not active"}`.
- It takes ~30 s to do so (not instant, as a genuinely absent socket would be).
- The daemon PID is stable across the whole session; the Unix socket exists; PreToolUse /
  PostToolUse / UserPromptSubmit events continue to be served normally throughout.
- The problem appears only once the session's transcript has grown large, and worsens as it
  grows. `/compact` or a fresh session (both of which shrink/rotate the transcript) instantly
  restore fast, correct Stop behaviour — a strong tell that the cost is transcript-size-bound.

---

## Root cause

Three source facts, each confirmed against the vendored tree, compose the failure.

### 1. The client uses one flat 30 s timeout for the whole exchange, and reports a timeout as "down"

`init.sh` builds the request, then opens the socket with a single 30 s timeout that must cover
connect **plus** send **plus** the entire `recv()` drain loop:

```python
# .claude/hooks-daemon/init.sh:997-1024
try:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(30)  # 30 second timeout          # <-- line 999
    sock.connect(socket_path)
    sock.sendall(request.encode('utf-8'))
    sock.shutdown(socket.SHUT_WR)

    response = b''
    while True:                                        # <-- recv loop, lines 1004-1010
        chunk = sock.recv(4096)
        if not chunk:
            break
        response += chunk
    sock.close()
    ...
    sys.exit(0)

except socket.timeout:
    fail('socket_timeout',                             # <-- lines 1021-1024
        f'Socket timeout (30s) connecting to daemon at {socket_path}. '
        'Daemon may be hung or overloaded.')

except FileNotFoundError:                              # genuinely-down cases handled separately
    fail('socket_not_found', ...)                      # (lines 1026-1029)
except ConnectionRefusedError:
    fail('connection_refused', ...)                    # (lines 1031-1034)
```

The timeout is not a *connect* timeout — it is the deadline for the daemon to finish computing and
streaming its reply. A slow **handler** therefore trips exactly the same `socket.timeout` as a
hung transport.

`fail('socket_timeout', ...)` routes (for a Stop event) into `emit_error_json`, where **every**
error type other than `invalid_hook_input` collapses to the same misleading reason:

```python
# .claude/hooks-daemon/init.sh:921-930  (inside emit_error_json)
if event_name in ('Stop', 'SubagentStop'):
    if error_type == 'invalid_hook_input':
        reason = ('Hooks daemon received a malformed hook payload - this '
                  'event was not validated (daemon likely healthy; do not restart)')
    else:
        reason = 'Hooks daemon not running - protection not active'   # <-- socket_timeout lands here
    response = {'decision': 'block', 'reason': reason}
```

So a request that **reached a live daemon** and merely ran long is reported to the operator as
"daemon not running". (Note the asymmetry: `invalid_hook_input` already gets an honest,
"do not restart" message — `socket_timeout` deserves the same treatment and does not get it.)

### 2. Why a Stop dispatch exceeds 30 s: handlers parse the ENTIRE transcript, from byte zero

`TranscriptReader.load()` calls `_parse()`, which streams the whole file and **materialises every
entry** into `self._messages` / `self._tool_uses` — no tail, no cap, no early-exit:

```python
# .claude/hooks-daemon/src/claude_code_hooks_daemon/core/transcript_reader.py:155-201 (elided)
with path.open("r") as f:
    for line_num, line in enumerate(f, 1):     # <-- whole file, every line
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)            # <-- json.loads on every record (line 163)
        except json.JSONDecodeError:
            continue
        ...
        if entry_type == "message":
            self._parse_message_entry(data)    # builds ContentBlock/TranscriptMessage objects
        elif entry_type in ("human", "assistant"):
            ...
```

The accessor the Stop handlers actually want only needs the **last** assistant message, yet it is
served off the fully-materialised list — the whole-file parse is unavoidable to reach it:

```python
# transcript_reader.py:494-514
def get_last_assistant_message(self) -> TranscriptMessage | None:
    for msg in reversed(self._messages):       # tail-oriented READ, but _messages was built by a full parse
        if msg.role == "assistant":
            return msg
    return None

def get_last_assistant_text(self) -> str:
    msg = self.get_last_assistant_message()
    return msg.content if msg else ""
```

Crucially, the shared loader creates a **fresh** `TranscriptReader` on every call, so the
per-instance cache in `load()` never helps across calls — each call is a fresh whole-file parse:

```python
# src/claude_code_hooks_daemon/utils/stop_hook_helpers.py:41-62
def get_transcript_reader(hook_input):
    transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
    if not transcript_path:
        return None
    reader = TranscriptReader()                # <-- new instance EVERY call → no memoisation
    reader.load(str(transcript_path))
    if not reader.is_loaded():
        return None
    return reader
```

### 3. How many full-file parses a single Stop dispatch triggers

This is where the confirmed behaviour **differs from, and is worse than**, the "three handlers ×
one parse each" mental model. The dispatch chain runs handlers in priority order and **breaks at
the first matching terminal handler** (`core/chain.py:183-223`). In this project's Stop
configuration the order is:

| Priority | Handler                          | Terminal? | Reads transcript how?                                      |
| -------- | -------------------------------- | --------- | ---------------------------------------------------------- |
| 9        | `backlog_stop_blocker` (project) | yes       | **bounded tail read** (1 MiB), full parse only as fallback |
| 10       | `auto_continue_stop` (built-in)  | **yes**   | **full `get_transcript_reader()` parse — multiple times**  |
| 20       | `task_completion_checker`        | no        | never runs on a normal stop (chain already broke at 10)    |
| 30       | `hedging_language_detector`      | no        | never runs on a normal stop (chain already broke at 10)    |
| 58       | `dismissive_language_detector`   | no        | never runs on a normal stop (chain already broke at 10)    |

Because `auto_continue_stop` is **terminal at priority 10** and its `matches()` returns `True` for
essentially every stop, the chain short-circuits there: `hedging_language_detector` and
`dismissive_language_detector` **do not execute on a normal Stop**. The full cost is concentrated
inside `auto_continue_stop`, which parses the whole transcript **2–3 times, and up to ~9 times**,
in a single dispatch:

```
auto_continue_stop.matches()            → get_transcript_reader()   # full parse #1  (line 328)
auto_continue_stop.handle() entry       → get_transcript_reader()   # full parse #2  (line 359)
   Branch 2 → _resolve_current_turn_message() → _await_fresh_assistant_message()
        → up to 6 × TranscriptReader().load()                       # full parses #3..#8 (line 659)
   Branch 3 reload                       → get_transcript_reader()   # full parse #9  (line 411)
```

The poll loop is the sting in the tail. `_resolve_current_turn_message()` decides the last message
is "suspect stale" when its entry timestamp is older than **4.0 s**
(`_STALE_TAIL_THRESHOLD_SECONDS`, line 126) and then re-reads the transcript up to **6 times**
(`_HAS_EXPLANATION_RETRY_ATTEMPTS`, line 129) waiting for "fresher" content:

```python
# auto_continue_stop.py:654-670 (elided)
for _ in range(_HAS_EXPLANATION_RETRY_ATTEMPTS):          # up to 6 iterations
    time.sleep(_HAS_EXPLANATION_RETRY_DELAY_SECONDS)
    retry_reader = TranscriptReader()                     # fresh whole-file parse each iteration
    retry_reader.load(transcript_path)
    candidate = retry_reader.get_last_assistant_message()
    ...
```

On a large transcript this is **self-amplifying**: parse #1 (in `matches()`) and parse #2 (in
`handle()`) *each take several seconds*, so by the time the age check runs the last message's
timestamp is already far older than 4 s — which is read as "stale" and triggers the 6-iteration
poll, each iteration another multi-second whole-file parse. The slower the file is to parse, the
more parses the freshness guard demands. That interaction alone is sufficient to exceed the flat
30 s budget.

### The correct pattern already exists in-tree (proof-of-concept fix)

The project handler `backlog_stop_blocker` needs the *same* datum — the last assistant message —
and reads it in milliseconds by seeking to end-of-file and scanning a bounded tail chunk, only
falling back to the full reader in the pathological >1 MiB-final-record case:

```python
# .claude/project-handlers/stop/backlog_stop_blocker.py:52, 145-178 (elided)
_TAIL_BYTES = 1_048_576  # 1 MiB — far larger than any assistant text message.

@staticmethod
def _tail_last_assistant_text(transcript_path):
    ...
    size = path.stat().st_size
    with path.open("rb") as handle:
        start = max(0, size - _TAIL_BYTES)
        handle.seek(start)                 # <-- seek to tail, do NOT read the whole file
        chunk = handle.read()
    lines = chunk.split(b"\n")
    if start > 0 and lines:
        lines = lines[1:]                  # drop the partial first line
    for raw in reversed(lines):            # scan backwards; stop at first assistant record
        ...
```

Its own docstring names the exact bug this report documents:

> "Parsing the whole file on every Stop (as the shared reader does) makes the Stop hook exceed the
> client's socket timeout on long sessions (a multi-hundred-MB transcript), which the daemon then
> misreports as 'not running'."

This is the reference implementation the built-in handlers and `TranscriptReader` should adopt.

---

## Evidence & measurements

All figures below are from the failing session on the live transcript.

| Measurement                                                                                      | Value                                                                                                                                          |
| ------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Transcript size at time of failure                                                               | **475 MB / 233,236 lines** (one session)                                                                                                       |
| A single **bare** `json.loads`-per-line pass over the file                                       | **2.29 s** (floor; no object materialising)                                                                                                    |
| A full **`TranscriptReader`** pass (materialises every entry)                                    | **~5–7 s** per pass (slower than the floor)                                                                                                    |
| Direct Stop probe through the production wrapper (`.claude/hooks/stop`) with the live transcript | **DURATION = 30096 ms, STOP_EXIT = 2**, `HOOKS DAEMON ERROR [socket_timeout]`, block reason "Hooks daemon not running - protection not active" |

The 30096 ms end-to-end figure is the empirical anchor: it lands one tick past the hard-coded
30 s client deadline, exactly as a `recv`-side budget exhaustion (not a connect failure) would.
Several `TranscriptReader` passes at ~5–7 s each — the 2–3 baseline parses plus the freshness poll
described above — comfortably exceed 30 s on this file.

**Explicitly ruled out:**

- **Not OOM.** No mutation-testing run was in flight during the failure; memory was not the
  constraint. (This is what distinguishes the failure from the related downstream issue as
  titled — see *References*.)
- **Not a crash.** The daemon PID was stable across the entire session and the socket remained
  present; other events were served throughout.

It is purely a **client read-timeout on slow whole-file transcript parsing** — a live daemon that
did not finish in time, mislabelled as a dead one.

---

## 1. Timeout error handling / messaging

A processing/handler timeout must surface **as a timeout**, never as "daemon not running". The two
failure modes are already distinguishable at the client and must be reported differently:

- **(a) Genuinely DOWN** — `FileNotFoundError` (no socket) or `ConnectionRefusedError` (nothing
  listening). These already have their own `except` arms (`init.sh:1026-1034`). *This* is when
  "daemon not running — protection not active" is the truthful message and a restart is the right
  operator action.
- **(b) ALIVE but slow/overloaded** — `socket.timeout` after a successful `connect()`+`sendall()`.
  The daemon was reached; a handler simply ran past the deadline. This must **not** advise a
  restart.

Recommendations:

1. **Give `socket_timeout` its own honest Stop reason**, mirroring the existing `invalid_hook_input`
   special-case in `emit_error_json` (`init.sh:921-930`). Something like:
   *"A hook handler exceeded the Ns budget — the daemon is ALIVE and was reached; do NOT restart
   it. This usually means the transcript is very large; `/compact` or a new session will restore
   fast Stops."*
2. **Attribute the culprit where possible.** If the daemon times the chain per handler (see §4),
   the timeout message can name which handler blew the budget, turning a mystery block into an
   actionable one.
3. **Reconsider fail-closed vs fail-open on a read timeout.** Today a slow handler yields a
   `decision:block` that *hard-blocks the user's Stop*. Hard-blocking a human because an advisory
   handler was slow is a poor trade — at minimum the reason string must not mislead the operator
   into restarting a healthy daemon; ideally a *read-side* timeout on Stop degrades to fail-open
   (allow the stop, emit a diagnostic) rather than fail-closed, since the safety value of a Stop
   advisory does not justify wedging the session for 30 s and then lying about the cause. (Connect
   / send failures — genuine "down" — can remain fail-closed.)

---

## 2. Transcript-reading efficiency

There is enormous headroom; the handlers request "the last assistant message" but pay for a full
materialisation of a multi-hundred-MB file.

Recommendations:

1. **Promote a bounded `get_last_assistant_text()` to a first-class API** that tail-reads (seek to
   end, read the last N KiB/lines, scan backwards, stop at the first assistant record) — precisely
   what `backlog_stop_blocker._tail_last_assistant_text` already does. Handlers that only need the
   last assistant text should call *this*, never build a whole-file reader.
2. **Stream/reverse and early-exit.** For "find the most recent record matching X", read backwards
   and stop as soon as the record is found instead of parsing to EOF and reversing an in-memory
   list.
3. **Do not materialise all entries when only the last text is needed.** `get_last_assistant_text`
   forcing a full `self._messages` build (`transcript_reader.py:494-514`) is the core waste.
4. **Add a hard size fast-path.** Beyond some threshold (e.g. > 10 MB) *only ever* tail-read —
   never attempt a whole-file parse from a hook that runs under a 30 s client deadline.
5. **Offset/mtime-keyed caching.** `TranscriptReader` already has `read_incremental(path, offset)`
   (`transcript_reader.py:279-365`); a cache keyed by `(path, size, mtime)` that reuses prior work
   and only reads the appended tail would make even the full-history accessors cheap on an
   append-only transcript.

---

## 3. Per-event memoisation

Within a **single** Stop dispatch the transcript is parsed repeatedly when it should be parsed **at
most once** and shared. As shown in §Root-cause-3, `auto_continue_stop` alone re-reads it 2–3
times on the baseline path (`matches()` at line 328, `handle()` entry at line 359, Branch 3 reload
at line 411) and up to 6 more times in the freshness poll (`_await_fresh_assistant_message`, line
659\) — every one a fresh `TranscriptReader()` because `get_transcript_reader` never reuses an
instance (`stop_hook_helpers.py:55`).

Recommendations:

1. **A per-dispatch transcript cache**, keyed by `(transcript_path, size, mtime)`, threaded through
   the chain (e.g. on a request-scoped context object) so all handlers in one Stop event — and all
   internal re-reads within one handler — share a single parse.
2. **Collapse `auto_continue_stop`'s own re-reads.** Parse once at the top of the dispatch and pass
   the reader (or the derived "last assistant message") down every branch instead of reloading in
   `matches()`, at `handle()` entry, and again at Branch 3.
3. **Rethink the freshness poll for large files.** The 4 s staleness threshold + 6-iteration poll
   was designed for a cheap parse; on a slow parse it is actively harmful (each retry is another
   multi-second whole-file read, and the parse latency is itself what makes the tail look "stale").
   With a bounded tail read this poll becomes cheap; alternatively gate the poll out entirely above
   a file-size threshold.

---

## 4. Additional recommendations (our own analysis)

- **Per-handler wall-clock budget + timing telemetry.** `ChainExecutionResult` already carries
  `execution_time_ms` for the whole chain (`chain.py:46`); extend it to per-handler timings and log
  any handler exceeding a soft budget. This makes "which handler was slow" answerable from logs and
  feeds the attributed timeout message in §1.
- **Event-aware timeouts.** A flat 30 s for all events is crude: a Stop legitimately does more work
  (transcript inspection) than a trivial PreToolUse. Consider a larger, explicit Stop/ SubagentStop
  budget, or — better — make Stop cheap enough (tail reads) that the budget is irrelevant.
- **A global byte-cap on parsing** regardless of handler, so no hook can ever attempt to parse an
  arbitrarily large file synchronously under a client deadline.
- **A slow-handler watchdog** in the daemon that logs (handler, elapsed, transcript size) whenever
  a handler exceeds a threshold — turning silent 30 s stalls into a visible, greppable signal.
- **Operator-relief note worth surfacing in the timeout message:** `/compact` or a fresh session
  rotates/shrinks the transcript and instantly restores fast Stops. The pain scales purely with
  transcript size, so this is a reliable immediate workaround while the root fix ships.

---

## Reproduction

1. Run a single Claude Code session long enough to grow its JSONL transcript to hundreds of MB
   (here: 475 MB / 233,236 lines). No mutation-testing load is required.
2. Fire a real Stop event through the production wrapper against that transcript, e.g.:
   ```bash
   echo '{"hook_event_name":"Stop","stop_hook_active":false,"transcript_path":"<LIVE_TRANSCRIPT>.jsonl"}' \
     | .claude/hooks/stop
   ```
3. Observe: the call takes ~30 s and returns
   `{"decision":"block","reason":"Hooks daemon not running - protection not active"}`, with
   `HOOKS DAEMON ERROR [socket_timeout]` on stderr and exit code 2 — **while the daemon PID is
   unchanged and its socket is present** (`daemon-cli status` shows RUNNING throughout).
4. Confirm size-dependence: `/compact` (or a new session) shrinks the transcript and the identical
   probe returns instantly and correctly.

---

## Impact

As any session gets long, **every Stop hard-blocks for ~30 s and then misreports the daemon as
down**. Two compounding harms:

1. **Workflow stall + false alarm.** The user's turn is blocked for 30 s, then told "protection not
   active", which reads as a safety-critical outage.
2. **Wrong remediation.** The message steers operators to **restart a perfectly healthy daemon** —
   which does nothing for the actual cause (transcript size), so the next Stop stalls again. In an
   autonomous/long-running setting this manifests as a repeating 30 s Stop stall and needless
   restart churn, precisely when a session is most productive (i.e. longest-lived).

The fix is high-leverage and low-risk: the bounded-tail pattern already exists in-tree, and the
timeout/messaging split is a small, self-contained change to `init.sh`.

---

## References (file:line)

Client wrapper (`.claude/hooks-daemon/init.sh`):

- `999` — `sock.settimeout(30)` (single flat budget for the whole exchange)
- `1004-1010` — `recv()` drain loop covered by that one budget
- `1021-1024` — `except socket.timeout: fail('socket_timeout', ...)`
- `1026-1034` — `FileNotFoundError` / `ConnectionRefusedError` arms (the genuine "down" cases)
- `916-930` — `emit_error_json`: Stop branch; every non-`invalid_hook_input` error → "Hooks daemon
  not running - protection not active" (line `926`)
- `941-954` — `fail()`

Transcript reader (`src/claude_code_hooks_daemon/core/transcript_reader.py`):

- `104-141` — `load()` (per-instance cache only)
- `143-205` — `_parse()`; whole-file loop at `156-157`, `json.loads` per line at `163`
- `494-514` — `get_last_assistant_message()` / `get_last_assistant_text()` (served off the fully
  materialised list)
- `279-365` — `read_incremental()` (existing offset-based reader, unused by the Stop path)

Shared Stop helper (`src/claude_code_hooks_daemon/utils/stop_hook_helpers.py`):

- `41-62` — `get_transcript_reader()` creates a fresh `TranscriptReader` on every call (no
  cross-call memoisation)

Built-in Stop handler (`src/claude_code_hooks_daemon/handlers/stop/auto_continue_stop.py`):

- `126` — `_STALE_TAIL_THRESHOLD_SECONDS = 4.0`; `129` — `_HAS_EXPLANATION_RETRY_ATTEMPTS = 6`
- `328` — full parse in `matches()`; `359` — full parse at `handle()` entry; `411` — full parse
  (Branch 3 reload)
- `633-670` — `_await_fresh_assistant_message()`; fresh `TranscriptReader().load()` per poll
  iteration at `659`

Dispatch (`src/claude_code_hooks_daemon/core/chain.py`):

- `183-223` — priority-ordered loop; terminal handler breaks the chain (why the priority-10
  terminal `auto_continue_stop` short-circuits the lower-priority advisory Stop handlers)

Reference implementation of the fix, already in-tree
(`.claude/project-handlers/stop/backlog_stop_blocker.py`):

- `52` — `_TAIL_BYTES = 1_048_576`; `145-178` — `_tail_last_assistant_text()` bounded tail read

Related tracking:

- a related downstream issue — "Hooks daemon OOM-killed under heavy mutation-testing load →
  protection gaps + Stop-hook loop". Same *user-visible symptom* (Stop mis-reports the daemon as
  down / Stop-hook loop) but a **different root cause** (memory pressure under mutation-test load).
  The failure documented here is **not** OOM and occurs with no mutation-testing run in flight; it is a
  client read-timeout on slow whole-file transcript parsing. Worth cross-linking so the shared
  "not running" symptom is understood to have (at least) two distinct causes.

---

## Appendix A — the ccy PTY supervisor's auto-`/compact` is defeated by the same failure

The daemon ships a **ccy PTY supervisor** (`.claude/ccy/claude-supervise.py`, Plan 00147/00148)
whose job is to keep a long session healthy: it watches a **daemon-written context sidecar** and,
when the context reading goes **RED** and the session is **idle**, injects a real `/compact`; on
any detected compaction it injects `continue` to resume. It is the intended automatic defence
against exactly the long-transcript regime that triggers the Stop-timeout bug above — so its
behaviour under that regime matters, and it was sense-checked live this session.

**Finding: the supervisor is healthy and armed, but stopped auto-compacting for the rest of the
session after exhausting a lifetime injection cap — and the Stop-timeout bug actively works against
it.**

Evidence from the live session:

- Both supervisor processes alive and armed the whole session (`--arm`): the PTY wrapper and its
  `--worker`, up ~1d 22h. The mechanism demonstrably works end-to-end — after a **manual**
  `/compact` the supervisor correctly detected the compaction and injected
  `🤖 [ccy-supervisor …] continue`.
- Its decision log (`untracked/supervise/decision.log`) shows, across the whole RED window, only
  two `noop` reasons, in escalating order of blame:
  1. **`session busy (composing)`** — the injection is idle-gated; the child was producing output
     almost continuously so the tick deferred (idle floor is 2.0 s).
  2. **`injection cap reached [urgent]`** — the *dominant, terminal* reason. From early in the RED
     window onward the log is a solid wall of this while context sat RED/urgent and never
     compacted.

Root cause of the cap-out (confirmed in source):

- The supervisor enforces a **lifetime** cap `_DEFAULT_MAX_INJECTIONS = 20`
  (`claude-supervise.py:601`, checked at `:1661`). The counter `self._injections` is incremented
  on every injection (`:1668`) and is **reset only in the constructor** (`:1505`) — there is **no
  reset after a successful compaction**. So once 20 auto-`/compact` injections have been made over
  a session's lifetime, every subsequent RED tick returns `noop: injection cap reached` and the
  supervisor **never auto-compacts again for that session**.
- A lifetime cap conflates two very different situations: a *tight runaway loop* (20 injections in
  quick succession — should stop) and a *legitimately long-lived session* (20 healthy compactions
  spread over ~2 days — should keep going). A marathon autonomous session is exactly the case the
  supervisor exists to serve, and it is the one the lifetime cap silently abandons.

**Compounding interaction with the Stop-timeout bug (the two failures reinforce each other):**

- A `/compact` only *lands* when injected into an idle, settled session. The Stop-timeout bug keeps
  the session **non-idle**: every long/errored Stop (30 s block, then re-fired) reads as
  "composing", so the idle-gated injection keeps deferring (`session busy`) and, when it does fire,
  competes with a session that will not settle — so injections are spent without reliably landing a
  compaction, driving toward the lifetime cap without the desired effect.
- Net effect: the daemon-overload bug both *creates* the need to compact (huge transcript) and
  *prevents* the automatic remedy from working (non-idle session + burned injection cap), which is
  why the operator ultimately had to `/compact` by hand.

Recommendations (supervisor, same upstream repo):

1. **Reset or credit-back `self._injections` on each *successful* compaction** (or replace the
   lifetime cap with a per-window rate cap, e.g. N injections/hour). A successful compaction is the
   *desired* outcome, not evidence of a runaway, and should not consume the session's lifetime
   budget. This is the single highest-value change — it keeps auto-compact alive across a long
   session.
2. **When the cap is reached while context is RED/urgent, emit a LOUD, visible operator warning**
   (e.g. `🤖 auto-compact DISABLED: injection cap (20) reached — please /compact manually`) instead
   of silently `noop`-ing. Today the operator gets no signal that the automatic safety net has
   switched off; the context simply fills until they notice.
3. **Fixing the Stop-timeout bug (main body) directly improves this**: with bounded tail reads the
   Stop hook stops wedging the session for 30 s, so the session settles to idle far more often and
   the supervisor's idle-gated `/compact` can actually land.

Supervisor file:line references (`.claude/ccy/claude-supervise.py`):

- `601` — `_DEFAULT_MAX_INJECTIONS = 20` (lifetime cap)
- `1505` — `self._injections = 0` (reset **only** here, in the constructor)
- `1652` — idle gate (`not idle` → `noop: session busy (composing)`)
- `1659` — patient-band gate (`not urgent and not work_idle` → defer)
- `1661-1662` — cap check (`self._injections >= max_injections` → `noop: injection cap reached`)
- `1668` — `self._injections += 1` (only on a WOULD_COMPACT decision; never decremented/reset)
- `1814` — `_DEFAULT_IDLE_FLOOR_SECONDS = 2.0`
