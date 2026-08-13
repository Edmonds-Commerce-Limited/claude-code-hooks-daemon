# Plan 00236 — Technical Decisions

## Decision 1: The nitpick `stop:1/1` trigger stays. The finding was wrong.

**Context**: Plan 00234 gave `dismissive_language` and `hedging_language`
(nitpick pseudo-event) a FIX verdict, severity high, with the reasoning
"Confirmed structural double-fire with its Stop twin on every Stop
(`triggers: stop:1/1`, merge does not dedupe); drop the stop leg, keep the
justified `pre_tool_use:1/5` coverage."

**What was checked**: one Stop event was fired at the live daemon through the
production `.claude/hooks/stop` forwarder, with a transcript containing both a
hedging phrase ("probably") and two dismissive ones ("pre-existing", "out of
scope"). The daemon's own chain trace:

```
Handler auto-continue-stop matched event
Handler auto-continue-stop returned decision=allow, terminal=True
Handler nitpick-dismissive-language matched event
Handler nitpick-hedging-language matched event
```

`task-completion-checker`, `hedging-language-detector`,
`dismissive-language-detector`, `remind-prompt-library` and
`subagent-completion-logger` do not appear. The response carried only the
nitpick handlers' sentence-case wording, never the Stop detectors' capitalised
`DISMISSIVE LANGUAGE DETECTED:` text.

**Why**: `HandlerChain` breaks the moment a terminal handler matches
(`core/chain.py`, `if handler.terminal: ... break`) regardless of the decision
returned. `auto_continue_stop` is `terminal=True` at priority 10 and its
`matches()` returns True for every Stop except a confirmed re-entry or an
AskUserQuestion turn. So every Stop handler above priority 10 is shadowed on
the ordinary stop.

**Decision**: keep `stop:1/1`. There is no double-fire; the nitpick leg is the
only one delivering this advisory. Dropping it would have removed the working
copy and left the shadowed one.

**What this says about the audit**: the verdict was reached by reading two
config blocks that each register a handler for the same event, which is exactly
how it looks on paper. Nothing short of running the chain would have shown
otherwise — which is why the fix here is a GUARD
(`tests/integration/test_stop_chain_terminal_shadowing.py`) rather than a
correction to one line of a table.

**Consequence, deferred**: the shadowed Stop handlers are a genuine defect of
the same family the audit exists to find — registered, enabled, and unable to
fire in the ordinary case. Resolving it means either removing them or moving
them below priority 10, which is a REMOVE/restructure decision and belongs in
that pass, not this one.

## Decision 2: The harvester correlates by command text, not by pgid.

**Context**: `background_process_tracker` writes
`{command, session_id, run_in_background}`; `read_tracked_pgids` looked for a
`pgid` key. Nothing ever wrote one, so the wall-TTL branch of
`harvest-background` could never fire. Plan 00234 offered "emit pgid or drop
the dead path".

**Options considered**:

1. **Emit a pgid at write time** — snapshot `ps` in the PostToolUse handler and
   correlate the just-launched process by args. Keeps the existing reader
   contract, but puts a `ps` spawn on the hook path and races the process
   start.
2. **Drop the wall-TTL branch** — honest, but deletes the one thing the tracker
   is for: noticing a process YOU backgrounded and forgot. The CPU ceiling
   catches runaways; nothing else catches an idle-but-forgotten build.
3. **Correlate by command text at read time** — the harvester already samples
   `ps`; the tracker already records the command.

**Evidence**: a live probe of a backgrounded command shows Claude Code runs it
as a wrapper shell that `eval`s the command verbatim, so the recorded text is
present in `ps args`:

```
667222  667222  /bin/bash -c source …snapshot.sh && … && eval 'sleep 90; echo done' …
667224  667224  sleep 90
```

Note also that the child sits in its OWN process group (667224 ≠ 667222), so
even a captured parent pgid would not have covered it.

**Decision**: option 3. Zero hot-path cost, no race, and the correlation
happens where both halves of the data already are.

**Stated limit**: this resolves for `run_in_background` calls, whose full
command survives into `args`. A shell-`&` command whose parent has exited
leaves a child whose `args` are a fragment — it matches nothing and gets no
wall TTL, which is exactly the coverage it had before, with the CPU ceiling
still behind it. The docstring says so rather than implying full coverage.

## Decision 3: The guard goes at the seam, not on either side of it.

**Context**: the pgid mismatch survived because BOTH sides were well
unit-tested and both tests fabricated their own fixtures — the harvester's test
invented `{"pgid": 100}` records, the tracker's asserted the fields it wrote.
Neither ran the other's code.

**Decision**: every fix in this plan that spans a module boundary gets an
integration test that runs the real producer against the real consumer. Two
were added; both would have failed before the fix. The unit tests that
fabricated the wrong schema were rewritten to mirror the production record
shape and now carry a docstring saying why.

**Corollary applied to the absence assertions**: an assertion that something
does NOT appear passes just as happily when the fixture is broken. The
shadowing guard therefore contains a paired test that removes the terminal
handler and requires the same transcript to produce the advisories — so a
future fixture rot fails loudly instead of quietly asserting nothing.
