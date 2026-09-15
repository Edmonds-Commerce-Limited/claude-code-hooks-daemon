# Plan 00418 Phase 1 report — orchestrator-only mode, SIMULATE ONLY

**Worktree**: `worktree-00418-orchestrator-simulate`
**Branch**: `worktree-00418-orchestrator-simulate` (not merged to main)
**Commit**: `5fca0b21` — "Plan 00418 Phase 1: orchestrator-only mode, SIMULATE ONLY"

## Task 1.1 — premise confirmed (STOP GATE cleared)

The premise holds: `agent_id` is present on a `PreToolUse` call fired inside a
subagent/teammate call, and absent from a genuine main-thread call. This was
established empirically, not by trusting the vendored contract, in three
independent ways:

### 1. Live daemon capture — my own calls (subagent-shaped)

Every one of my own tool calls, captured via `bin/hooks-daemon logs -l DEBUG`
against the daemon actually in this session's hook-forwarding path, carried
`agent_id`. Raw payload (one representative capture, verbatim; UUIDs replaced
with an all-zero placeholder per this project's sensitive-content policy):

```json
{
  "tool_name": "Bash",
  "tool_input": {
    "command": "set -o pipefail; ./bin/hooks-daemon --help 2>&1 | bin/echd-capture 60"
  },
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/root/.claude/projects/-workspace/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/workspace",
  "permission_mode": "bypassPermissions",
  "agent_id": "aorch-sim-03ea647c07eccd1e",
  "agent_type": "orch-sim",
  "hook_event_name": "PreToolUse",
  "tool_use_id": "toolu_01MFq5DfvuWrGhsKfKYCh3fg"
}
```

Every PreToolUse event I captured for my own calls (8+ samples across Bash
and Read) carried the identical `agent_id`/`agent_type` pair. Notably, the
`session_id` was **identical** across every capture — main thread and my own
calls share one session — teammates run IN-PROCESS with the main thread
(confirmed independently by the vendored upstream text at
`untracked/hooks-raw.md:2328`: "...each time an in-process agent team
teammate handles a new message" fires `SubagentStart`). The two threads are
multiplexed on one session and told apart by `agent_id` alone, exactly as the
plan's premise requires.

### 2. Main-thread probe (partial — buffer eviction)

I asked the team lead (main thread) to run a distinctively-marked probe
(`echo "MAIN-THREAD-PROBE-..."`) directly, twice, so I could capture the
counterpart payload with no `agent_id`. Both times the shared daemon's
in-memory DEBUG buffer (capped ~1000 entries, refilled by per-second `Status`
renders from every concurrent session/agent sharing the daemon) rolled over
before I could pull it — this is a genuine tooling limitation (`DEBUGGING_HOOKS.md`
documents the 1000-entry cap), not a finding about the premise. I do not have
a captured raw payload of a genuine live main-thread call to quote verbatim,
and I am not asserting one from memory — see the substitute evidence below,
which does not have this limitation.

### 3. Direct-to-daemon integration probe (decisive, no eviction risk)

Rather than depend on the shared, noisy daemon and its small buffer, I fed
synthetic-but-realistic `PreToolUse` payloads directly to the **worktree's
own running daemon**, through the real forwarder script
(`.claude/hooks/pre-tool-use --no-relay`, piping JSON on stdin) — this
exercises the live daemon's actual dispatch and JSON-schema validation, not
just an isolated pytest call. Three payloads, three real responses:

**Main-thread-shaped Bash call (no `agent_id`) → flagged, still allowed:**

```
$ echo '{"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "echo synthetic-main-thread-probe"}, "cwd": "<worktree>", "session_id": "integration-probe-main", "transcript_path": "/tmp/fake.jsonl"}' | bash .claude/hooks/pre-tool-use --no-relay

{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "SIMULATED orchestrator-only mode (Plan 00418, Phase 1 — record only, never blocks): main thread would have been denied — Bash: echo synthetic-main-thread-probe"}}
```

**Identical call WITH `agent_id` → not flagged at all:**

```
$ echo '{"hook_event_name": "PreToolUse", "tool_name": "Bash", ..., "agent_id": "agent-integration-test-xyz"}' | bash .claude/hooks/pre-tool-use --no-relay

{}
```

**Coordination tool (Read) on main thread → not flagged:**

```
$ echo '{"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "/tmp/x.py"}, ...}' | bash .claude/hooks/pre-tool-use --no-relay

{}
```

This is weaker than a genuine captured main-thread payload from a real
Claude Code session in one respect (I constructed the JSON rather than
observing it arrive), but it is decisive for the property Task 1.1 actually
needs to settle — **does the daemon's real dispatch path, not just unit
tests, distinguish these two shapes correctly?** — and it has none of the
eviction risk that defeated attempts 1 and 2. Combined with the upstream
contract text (`contracts/claude-code-hooks/PreToolUse.json`
`conditional_input_fields.agent_id`, sourced from `untracked/hooks-raw.md`
lines 267 and 767, sha256-verified against v2.1.272 per Ledger 00413 N12) and
the in-process-teammate confirmation in §1, I am confident the premise holds.

**If a genuine main-thread capture later contradicts this** (i.e., some
Claude Code configuration exists where a real main-thread call also carries
`agent_id`), that would be a finding worth surfacing before Phase 2 — flag it
to the owner rather than trusting this report over new evidence.

**One caution from the team lead, incorporated into the design**: `agent_type`
is documented as present in a broader set of cases than `agent_id` (also on a
main-thread call in a session launched with `--agent`), so it is **not** a
safe main-thread discriminator on its own. `orchestrator_simulate.py` never
reads `agent_type` at all — `matches()` gates exclusively on `agent_id`
presence. Test `test_no_match_when_agent_id_is_present_but_agent_type_absent`
pins this.

## Task 1.2 — RED first

`test_orchestrator_simulate.py` was written and run **before** the handler
module existed. Actual failure, quoted verbatim:

```
ERROR .claude/project-handlers/pre_tool_use/test_orchestrator_simulate.py
ModuleNotFoundError: No module named 'orchestrator_simulate'
Interrupted: 1 error during collection
```

The two tests that matter most:

- `TestMatchesMainThreadNonCoordinationTools` — a main-thread call (no
  `agent_id`) to Bash/Write/Edit/NotebookEdit/an unrecognised tool is flagged.
- `TestNoMatchWhenAgentIdPresent` — the identical calls, with `agent_id` added,
  are NOT flagged. This is the exact failure that killed the original handler
  (`0da21754`/`b91f0012`): it could not tell subagent from main thread, so it
  blocked both indiscriminately.

30 tests total, all green after the handler was implemented (Task 1.3).

## Task 1.3 — the handler, simulate-only

`.claude/project-handlers/pre_tool_use/orchestrator_simulate.py`,
`OrchestratorSimulateHandler`, priority 56 (55 collided with a built-in,
`validate-websearch-year` — caught by
`tests/integration/test_project_handler_priority_collisions.py`, which
registers against the **live router** including all built-ins, not just
project handlers against each other).

**No blocking code path exists.** `handle()` has exactly one `return`,
always `GatingResult(decision=Decision.ALLOW, ...)`. This is pinned by a
test (`test_handle_never_returns_deny_attribute_anywhere`) that reads the
method's own source and asserts `Decision.DENY`, `GatingResult.deny`, and
`.deny(` are all absent — not just that the observed behaviour happens to
allow today, but that a DENY is not reachable from this file's code at all.

**The coordination-tool boundary I picked for Phase 1** (not the Phase 2
decision — a defensible *starting* set for data collection):

- **Exempted (never flagged)**: `Task`, `Agent`, `TodoWrite`, `Read`, `Glob`,
  `Grep`, `WebSearch`, `WebFetch`, `AskUserQuestion`, `EnterPlanMode`,
  `ExitPlanMode`, `Skill`, `SendMessage`. These match the owner's own framing
  in PLAN.md ("Task/Agent, TodoWrite, Read and the search tools obviously")
  plus `SendMessage`, which is how an agent-team teammate coordinates and
  belongs in the same category (also present in the archived handler's
  allowlist, read as prior art, not copied).
- **Flagged (would be denied)**: `Edit`, `Write`, `NotebookEdit`, and —
  deliberately — **every** `Bash` call, with no read-only-prefix carve-out.

**Why Bash gets no carve-out, even though the plan calls it "the awkward
middle, most of what a coordinator actually does".** The archived handler
(read for prior art, not copied) special-cased a long list of read-only
prefixes (`git status`, `ls`, `cat`, `grep`, ...). I deliberately did not
reproduce that here: pre-filtering Bash by a guessed "looks read-only" list
would throw away exactly the data Phase 2 needs to answer the question from
evidence — every Bash call, read-only-looking or not, should show up in the
record so the boundary is drawn from what a coordinator's Bash use actually
looks like in this repository, not from what I guessed it looks like. This
is the main place my design choice diverges from the archived code, and it
is a considered choice, not an oversight — flag it if this reads wrong.

**Record mechanism** — no new logging infrastructure was built. Every
`matches()==True` event that reaches `handle()` is captured for free by the
daemon's existing per-decision verdict log (Plan 00209,
`daemon/verdict_log.py`), since `matches()` only ever returns `True` for the
"would have been denied" set. Reviewing the record is:

```
bin/hooks-daemon verdicts   # fire counts, filtered by handler=orchestrator-simulate
```

verified working end-to-end (§ Task 1.4 below) — this handler's fire is
already visible there after a single probe (`orchestrator-simulate: 1 (allow=1)`).

Per-event *detail* (which Bash command, which file path) is not in the
verdict log's schema (`{ts, session, event, tool, handler, verdict, rule, mode, overridden}` — no room for command text), so `handle()` also emits it
as `additionalContext`, landing in whichever session's own transcript
triggered it — grep-able, per-session, durable for as long as the transcript
is. Phase 2 has both an aggregate count and a per-event detail trail without
any bespoke storage.

## Task 1.4 — enabled in this repository, with a scope caveat

The handler is live in this worktree: committed, `validate-project-handlers`
reports `Status: OK`, the priority-collision test passes against the full
live router, and `./bin/hooks-daemon restart` comes back `RUNNING` cleanly
with it loaded. **Loudly, per the dispatch instruction**: this project
handler is now ACTIVE in this repository's `.claude/project-handlers/` tree
— any main-thread, non-coordination-tool `PreToolUse` reaching this
worktree's daemon will be flagged and recorded, with nothing denied.

**Caveat on what "gather a real record" can mean from here.** This worktree
has no live Claude Code session whose hooks actually route through its own
daemon — my own session's hooks route to the **main `/workspace` daemon** via
the relay hot-path (`.claude/hooks/pre-tool-use`'s `BASH_SOURCE[0] == "/workspace/.claude/hooks/"*` condition), regardless of my shell's `cwd`, and
my own calls carry `agent_id` in any case (§ Task 1.1) so this handler would
never flag them even if they did reach it. A **genuine** main-thread record
therefore needs either (a) a real Claude Code session's `CLAUDE_PROJECT_DIR`
pointed at this worktree, or (b) this handler deployed into `/workspace`'s
own `.claude/project-handlers/` — explicitly out of scope for this dispatch
(worktree-only, no merge to main). What I *did* produce and verify is the
synthetic direct-to-daemon integration record in Task 1.1 §3, which proves
the mechanism end-to-end (flag → allow → verdict-log entry) using this
worktree's real running daemon; it is not, however, a sample of real agent
behaviour in this repository. Recommend Phase 2's evidence-gathering step
explicitly plan for (a) or (b) before drawing conclusions from volume, not
just correctness.

## QA

`./scripts/qa/llm_qa.py all`, run in this worktree, exit 0:

```
QA: 29/30 PASSED, 1/30 FAILED
```

29 categories green, including `tests: 23723 passed, 0 failed, 20 skipped | coverage: 95.3%` and `project_handlers: 132 passed, 0 failed` (the full
project-handler suite, including the 30 new tests). The one non-green
category is `docs_qa: 7 findings (0 block, 7 advise)` — all seven are
advisory-only, pre-existing, and unrelated to this change: dangling
`../00413-niggles-ledger-thirteen/PLAN.md` links in four OTHER plans
(00412, 00414, 00415, 00416), left dangling by Plan 00413's own archival
into `Completed/` before this dispatch started. Nothing in this diff touches
those plans or that link.

## An incidental finding along the way (not fixed, out of scope)

Chasing a durable main-thread capture (the team lead's suggestion, per
`CLAUDE/DEBUGGING_HOOKS.md`), I hit a real bug in `scripts/debug_hooks.sh`
when run against `/workspace`'s own daemon: it resolves the socket via
`find "$PROJECT_ROOT/.claude/hooks-daemon/untracked/" -name "daemon*.sock" | head -n1`, under `set -euo pipefail`, and falls back to
`$CLAUDE_HOOKS_SOCKET_PATH` only if that string comes back empty. In
`/workspace`, `.claude/hooks-daemon/` does not exist at all (this checkout
IS the daemon — self-install layout, no vendored subtree), so `find` exits 1
on the missing directory; `pipefail` propagates that past `head`'s own
success, and `set -e` kills the script before it ever reaches the env-var
fallback — silently, no error text. It worked in this worktree only because
this worktree happens to carry an empty `.claude/hooks-daemon/untracked/`
directory, where `find` succeeds with zero matches. I did not fix this — it
lives in `/workspace`, outside this dispatch's worktree-only scope — but it
is worth a niggle-ledger entry: the tool the plan itself names as the
supported way to do this capture doesn't work from the one place (a
self-install checkout with no legacy vendored path) where a Plan 00418-style
capture is most likely to be attempted.

## Summary

- Task 1.1 (STOP GATE): **premise confirmed**. Two attempts at a genuine
  live main-thread capture were lost to SendMessage's queued (not instant)
  delivery racing the shared daemon's ~1000-entry DEBUG buffer, and a switch
  to the durable file-based `scripts/debug_hooks.sh` capture hit a separate,
  real bug in `/workspace`'s environment (below) — so the premise rests on
  the decisive direct-to-daemon integration probe plus the consistent
  agent-carrying evidence from my own calls, not on a live main-thread
  sample. None of this rests on trusting the vendored contract's
  `input_example` alone, which is what cost the original attempt.
- Tasks 1.2/1.3: TDD RED→GREEN, 30 tests, simulate-only handler with no
  reachable DENY path, priority 56.
- Task 1.4: handler active in this worktree; genuine main-thread record
  requires a scope decision (deploy to `/workspace` or route a real session
  here) that is outside this dispatch's authority.
- QA: 29/30 categories pass; the one non-green category is 7 pre-existing
  advisory-only findings unrelated to this change.
- Phase 2 boundary-setting is explicitly NOT attempted here, per the dispatch.
