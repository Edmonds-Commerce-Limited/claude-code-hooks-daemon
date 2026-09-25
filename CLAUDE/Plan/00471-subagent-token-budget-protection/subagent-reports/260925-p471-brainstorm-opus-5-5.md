# Plan 00471 Task 1.1: brainstorm and ranked design for subagent spend levers

Author: p471-brainstorm (Opus 5.5). Read-only: no code changed and nothing committed.
The analysis script is `untracked/scratch/p471_spend.py` and its output is
`untracked/scratch/p471_spend.json`. It streams every transcript once, in 18 s.

## 0. Units and caveats

- **Raw tokens** = input + cache_read + cache_creation + output, summed per API
  request. Requests are deduplicated on `requestId`, because Claude Code writes
  one record per content block and each record carries the whole request's
  usage. `subagent_cache_aggregator.py:156-161` documents the same trap.
  `<synthetic>` records carry zero usage and are skipped.
- **ite** (input-token-equivalents) weights the API price ratios: input 1,
  5-minute cache write 1.25, cache read 0.1, output 5. The 5-hour
  subscription limit's internal weighting is not published, so ite is a proxy
  and the percentages are what matter.
- The savings figures are **simulations, and they are upper bounds**. The
  model is a sawtooth: at budget B the agent restarts at a 30k-token base (the
  measured median first-request context is 36,467), grows by the same
  per-request deltas as the real agent, and pays 5k output tokens plus a 30k
  cache write per handoff. It does not model rework, meaning a fresh agent
  re-reading files the old one had in context. Discount by roughly a quarter
  to a third for a realistic figure.

## 1. Ground truth: what the daemon can see

### 1.1 Hook inputs (vendored docs, `remote-docs/code.claude.com/docs/en/`)

| Fact                                                                                                                                                                  | Citation                                                 |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| Every event carries `session_id` and `transcript_path`. PreToolUse also carries `tool_name`, `tool_input` and `tool_use_id`.                                          | hooks.md:786-808, 1613                                   |
| Inside a subagent, tool events also carry `agent_id` and `agent_type`.                                                                                                | hooks.md:277, 777-778                                    |
| SubagentStop carries `agent_transcript_path` and `last_assistant_message`. There, `transcript_path` is the **main** session's transcript.                             | hooks.md:2413                                            |
| SubagentStart **cannot block** a spawn. It can only inject context.                                                                                                   | hooks.md:2390                                            |
| Agent tool input has `prompt`, `description`, `subagent_type` and `model`. PostToolUse `tool_response` has `totalTokens` and `usage`, but only for the final request. | hooks.md:1764-1790                                       |
| Stop input has a `background_tasks[]` array (type `subagent` or `teammate`, plus status). It is **only on Stop and SubagentStop**, not on PreToolUse.                 | hooks.md:2564-2580, 2421                                 |
| TeammateIdle fires when a teammate goes idle, with `teammate_name` and `team_name`. The daemon already has the enum (`constants/events.py:62`).                       | hooks.md:2682-2690                                       |
| SendMessage input: `to` (a name or agentId), `message`, `summary`. TaskStop input: `task_id`.                                                                         | tool schemas, loaded in this session                     |
| A SendMessage to a finished agent **resumes its full history**, including runs stopped with TaskStop.                                                                 | sub-agents.md:1088, 1106                                 |
| A native concurrency cap exists: `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`, default 20. It does **not** cover agent-team teammates or resumes.                           | sub-agents.md:1048-1055                                  |
| `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` applies to subagents. Transcripts log `compact_boundary` with `preTokens`/`postTokens`.                                             | sub-agents.md:1128-1145                                  |
| Subagent requests default to a **5-minute** cache TTL (`subagentPromptCacheTtl`).                                                                                     | prompt-caching.md:265-297                                |
| The Status (status-line) payload carries `rate_limits.five_hour.used_percentage`, `cost.total_cost_usd` and `context_window`.                                         | `untracked/payload-capture/Status.jsonl` (keys verified) |

**Every agent in this session is a teammate.** Each agent's `meta.json` says
`"taskKind":"in_process_teammate"`, so the native concurrent-subagent cap
never applied here.

**Not verified: whether a subagent's PreToolUse `transcript_path` points at
its own transcript or at main's.** The docs state it only for SubagentStop,
where it is main's. The layout makes the agent's file derivable either way:
`<dirname(transcript_path)>/<session_id>/subagents/agent-<agent_id>.jsonl`.
The file names match the `agentId` field, for example
`agent-aplan464-impl-aeaeef9c8c61cd48.jsonl`. A named agent's file is
`agent-a<name>-<16 hex>.jsonl`, and `meta.json` carries `name`. That covers
the SendMessage `to` → transcript lookup. **The first task of Phase 2 is to
capture a real subagent PreToolUse payload** (payload-capture currently
records only Status) and confirm this.

### 1.2 The environment

The session runs with `CLAUDE_CODE_AUTO_COMPACT_WINDOW=600000`. That is why
every compaction fires at `preTokens` 566,930 to 581,612 (all 9 of Plan 464's
implementer's). The ~570k figure in N62 is this setting, not a model limit.
The main context window is 1,000,000 (Status payload).

### 1.3 Measured spend: session e5e72775, 297 subagent transcripts, 978 MB

| Measure                                            | Value                                                                                                       |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Subagent API requests                              | 47,391                                                                                                      |
| Subagent raw tokens / ite                          | 12.70 B / 1,664 M                                                                                           |
| Main thread raw tokens / ite                       | 2.16 B / 260 M (8,314 requests, max ctx 566,580, 28 compactions)                                            |
| Subagent share of all ite                          | **86.5 %**                                                                                                  |
| Top 10 agents' share of subagent ite               | 33.4 %                                                                                                      |
| Top 30 agents' share of subagent ite               | **62 %**                                                                                                    |
| 116 agents with under 50 requests                  | 2.8 %                                                                                                       |
| Model split of subagent ite                        | Sonnet 5: 53.6 %, Opus 5.5: 45.2 %                                                                          |
| Agents whose description says "review"             | 23.2 % of subagent ite. Plan 463 had 12 review agents, 421 had 7, 376 had 6.                                |
| Peak concurrently active agents (per minute)       | 22. The share of subagent ite spent while more than 3 were active is **86.5 %**; while more than 5, 79.2 %. |
| Busiest 5-hour window                              | 538 M ite of 1,925 M session total. The peak hour was 172 M.                                                |
| Cold large cache writes (over 100k in one request) | 284 requests, 104 M ite (6.2 %)                                                                             |

Share of subagent ite by the request's context size:

| Context  | Requests | ite share |
| -------- | -------- | --------- |
| 0-100k   | 4,928    | 5.0 %     |
| 100-150k | 6,881    | 8.1 %     |
| 150-200k | 6,701    | 9.9 %     |
| 200-300k | 11,042   | 21.7 %    |
| 300-450k | 11,062   | 30.9 %    |
| 450k+    | 6,777    | 24.4 %    |

**76.5 % of subagent spend happened at a context above 200k.** The largest
agents (such as `n466-guard-defects`, `plan464-impl` and `plan463-impl`)
average 315k to 340k context per request over 1,450 to 2,100 requests, and
each received 14 to 19 inbound teammate messages. They were reused for "NEW
TASK" after "NEW TASK" rather than replaced.

### 1.4 Cost of measuring in a hook

Measured on the 48.9 MB `plan464-impl` transcript:

| Method                                                                                                                                                  | Cost                                                                                                                                                                                    |
| ------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Full scan per call                                                                                                                                      | 58 ms. Not acceptable per tool call, fine once per stop.                                                                                                                                |
| **Tail read**: seek to EOF minus 64 KiB and scan lines backwards for the last non-`<synthetic>` assistant `usage`, doubling the window if none is found | **59 µs per call**, 1 read. The largest single line in the file is 264 KB, so the worst case is about 3 doublings (512 KiB).                                                            |
| Offset cache: daemon-side `{path: (inode, offset, totals)}`, parsing only the bytes appended since the last call                                        | O(new bytes), which also gives **cumulative** spend cheaply. It must be reset when the inode changes or the size shrinks. It persists to a sidecar so a daemon restart does not rescan. |

Current context = `input + cache_read + cache_creation` of the last real
request. The first non-`<synthetic>` record matters: the file's very last
assistant record was `<synthetic>` with zero usage.

### 1.5 What the daemon already has, to reuse

- `handlers/subagent_stop/subagent_cache_aggregator.py`: a per-agent,
  per-session cache-usage sidecar written at SubagentStop, with dedup by
  message id. It is the natural home for a spend ledger. It reads the **whole**
  transcript on every stop (lines 164-171), which for a resumed giant agent is
  47 MB × 19 stops. It should adopt the offset cache.
- `handlers/status_line/context_sidecar.py`: writes a per-session sidecar on
  every render, including `cost_usd`, but not yet `rate_limits`. Adding
  `five_hour_pct` is a small change, and it is the input for a rate-aware
  governor.
- `handlers/status_line/mtime_cache.py`: an mtime-gated reader that
  governors reading sidecars should use.
- `prompt_cache_indicator.py`: already reads `prompt_cache` from Status. A
  spend segment belongs beside it.
- `pre_tool_use/dispatch_declaration.py`: already a PreToolUse gate on Agent,
  so the brief-file and concurrency checks can live beside it or share its
  parsing.
- `core/handler_scope.py`: MAIN/SUB scoping by `agent_id`, so a subagent-only
  handler comes for free.
- `subagent_report_persistence` and `subagent_report_path_verifier`: the
  handoff report path convention already exists (`subagent-reports/`).
- `budget_exhaustion_detector` (PostToolUse): scans tool responses for opaque
  budget errors. It is related but does not measure tokens. It could consume a
  "usage limit" StopFailure signal (hooks.md:2660, `error` on rate limit).
- `background_process_tracker`: tracks shell backgrounding only, so there is no
  reuse for agent liveness.
- The `thread_registry` pattern (an on-disk heartbeat registry) is the model
  for an agent-liveness registry.

## 2. Brainstorm: every lever, including the impossible

M = measure, A = advise, D = deny, R = report.

| #   | Lever                                                                                                                                         | Kind   | Verdict                                                                                                                                                                                                                                                                                      |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| L1  | Owner sets a lower `CLAUDE_CODE_AUTO_COMPACT_WINDOW` (or `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`). The daemon supplies the measured recommendation. | R      | **Survives.** Largest saving, zero enforcement code.                                                                                                                                                                                                                                         |
| L2  | Subagent context budget: soft advise, then hard handoff-only                                                                                  | M/A/D  | **Survives.**                                                                                                                                                                                                                                                                                |
| L3  | Resume guard on SendMessage to a cold, large, stopped agent                                                                                   | D      | **Survives.**                                                                                                                                                                                                                                                                                |
| L4  | Concurrency cap on Agent (spawn) and SendMessage (resume)                                                                                     | D      | **Survives**, as a rate lever rather than a total-spend lever.                                                                                                                                                                                                                               |
| L5  | Rate-aware governor on `five_hour.used_percentage`                                                                                            | A/D    | **Survives.**                                                                                                                                                                                                                                                                                |
| L6  | Spend ledger: per agent, per plan (by `gitBranch`/`cwd` in records), with a CLI report                                                        | M/R    | **Survives.** It is the enabler for tuning everything else.                                                                                                                                                                                                                                  |
| L7  | Status-line spend meter (Σ subagent ite, a live-agent count, the largest live agent's context)                                                | R      | **Survives** (cheap, from the L6 sidecars).                                                                                                                                                                                                                                                  |
| L8  | CLAUDE.md diet for the daemon-generated section                                                                                               | M      | **Survives, conditionally.** The file is 90,760 bytes (about 22k tokens), loaded into every subagent. 47,391 requests × 22k × 0.1 ≈ 104 M ite ≈ **6 %**, plus the first-request write for each agent. The daemon owns the generated block. The risk: less guidance means more blocked calls. |
| L9  | Review-round convergence advisory (count review dispatches per plan or branch)                                                                | M/A    | **Survives, as advisory only.** It is a heuristic: nothing deterministic tells a daemon whether findings are shrinking.                                                                                                                                                                      |
| L10 | Brief-file requirement on Agent (prompt must point at a file)                                                                                 | D      | **Weak.** Prompts are a small share of context; `dispatch_declaration` covers the report half. Fold it into L4's message rather than building it.                                                                                                                                            |
| L11 | Model cap: deny `model: opus` for dedupe scouts and reviewers                                                                                 | D      | **Weak or deferred.** Model is only a price multiplier, and the owner picks models deliberately. It could be a per-`subagent_type` allowlist later.                                                                                                                                          |
| L12 | `maxTurns` in the daemon's shipped agent definitions                                                                                          | D      | **Weak.** It counts turns, not context, only covers custom types, and the teammates here are none of them.                                                                                                                                                                                   |
| L13 | `experimental.cacheTtl: 1h` for long-lived agent types, to make idle resumes warm                                                             | config | **Doubtful.** A 1-hour write costs 2× base and helps only when resumes land between 5 and 60 minutes. L3 fixes the cause instead.                                                                                                                                                            |
| X1  | The daemon changes the autocompact threshold itself                                                                                           | —      | **Impossible.** Env is fixed when Claude Code starts. A hook's `CLAUDE_ENV_FILE` affects Bash subprocesses only. It is owner-only (plan Non-Goals).                                                                                                                                          |
| X2  | The daemon triggers `/compact` inside a subagent                                                                                              | —      | **Impossible.** Hooks cannot issue slash commands. The PTY supervisor (`claude-supervise`, via `context_sidecar`) types into the main terminal only, and subagents have no terminal.                                                                                                         |
| X3  | The daemon kills or stops a runaway agent                                                                                                     | —      | **Impossible and forbidden.** Hooks cannot call TaskStop, agents are in-process, killing loses work, and the N59 signal rules forbid it. The hard budget reaches the same end by starving tool calls.                                                                                        |
| X4  | Block the spawn at SubagentStart                                                                                                              | —      | **Impossible** (hooks.md:2390). Gate PreToolUse Agent instead.                                                                                                                                                                                                                               |
| X5  | Read usage from the hook input                                                                                                                | —      | **Not available.** Usage exists only in the transcript (or Status for main).                                                                                                                                                                                                                 |
| X6  | Exact subscription accounting                                                                                                                 | —      | **Impossible.** The weights are unpublished. `five_hour.used_percentage` from Status is the only ground truth, and it arrives only through the main thread's status line.                                                                                                                    |
| X7  | Shrink a live agent's context in place                                                                                                        | —      | **Impossible.** Only compaction or a fresh agent can shrink it.                                                                                                                                                                                                                              |
| X8  | Use `background_tasks` for a live count at PreToolUse                                                                                         | —      | **Not on that event.** Stop and SubagentStop only. It can feed the liveness registry as a reconciliation point.                                                                                                                                                                              |
| X9  | Native `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS=3` as the whole cap                                                                              | —      | **Insufficient.** It does not apply to teammates (every agent here) or resumes (sub-agents.md:1053-1055).                                                                                                                                                                                    |

## 3. Design of the surviving levers

### L1: autocompact recommendation (owner's setting)

- **Mechanism**: a SessionStart or `hooks-daemon spend` report reads
  `compact_boundary.preTokens` across recent subagent transcripts, together
  with the L6 ledger. It prints the measured distribution and a recommended
  value. It changes nothing itself.
- **Evidence**: an autocompact at B is the same sawtooth as the L2 simulation,
  but it has no coordinator turn and restarts from `postTokens` (7.6k to 33k
  measured, lower than the 30k brief). Gross savings of subagent ite:
  **B=150k: 54.9 %, 200k: 47.7 %, 300k: 32.2 %, 450k: 18.5 %.** N62's "500k
  saves ~12 %" matches the curve.
- **Recommended value**: about 200k, meaning `CLAUDE_CODE_AUTO_COMPACT_WINDOW`
  near 230,000 given the ~33k buffer observed (600k gave ~567k). The same
  setting also compacts the **main coordinator** (260 M ite, 13.5 %, which
  compacted 28 times at 566k). The owner must weigh coordinator recall
  against cost. Past about 8 compactions an agent's summary chain loses
  fidelity, which is why L2 (a clean handoff) complements rather than
  replaces L1.
- **Default**: a report only, everywhere.
- **Failure modes**: none from the daemon. A lossy summary chain is the owner's
  trade-off.
- **Test**: unit tests on the preTokens and recommendation arithmetic, using
  fixture transcripts.

### L2: subagent context budget (soft advise, hard handoff-only)

- **Mechanism**: a PreToolUse handler, scope SUB (`agent_id` present). It
  resolves the agent transcript (section 1.1), then takes the context from a
  tail read, or from the offset cache to get cumulative spend as well.
  - At or above `soft_tokens`, it injects `additionalContext` **once per band
    crossing**, keyed `(agent_id, band)` in daemon state. Advising on every
    call would itself grow the context. The advice: "write your handoff to
    `<plan>/subagent-reports/…-handoff.md`, commit WIP, SendMessage the lead".
  - At or above `hard_tokens`, it **denies every tool except** these:
    - Write or Edit under the handoff directories (`**/subagent-reports/**`,
      `untracked/scratch/**`);
    - Bash matching a read-only or commit allowlist (`git status|diff|add|commit|log`);
    - SendMessage (any recipient);
    - Read of the handoff file it is writing.
  - The deny reason names the exact report path and the three steps.
  - A **SubagentStop companion** (reuse `subagent_report_path_verifier`)
    blocks the stop of an over-budget agent until the handoff file exists. That
    guarantees no lost work.
- **Trigger and cost**: an integer compare after a 59 µs tail read. With the
  offset cache it is usually under 10 µs of I/O.
- **Defaults**:
  - Client projects: soft advisory on at 300k (it only ever advises), hard off.
  - This repo: soft 150k, hard 250k. The hard value sits above soft so the
    agent gets a real window to comply, and 250k leaves space to write the
    handoff.
  - Config keys:
    - `handlers.pre_tool_use.subagent_context_budget.options.{soft_tokens, hard_tokens, handoff_globs, allowed_bash_prefixes, exempt_agent_types}`
- **Savings** (simulated gross; subtract the coordinator overhead of about 2
  main turns per handoff at the mean main context of 259k, mostly cache
  reads):
  - hard at 200k: 47.7 % gross, 488 handoffs, about 1.5 % overhead, about
    46 % net upper bound;
  - soft-compliance at 150k: 54.9 % gross, 736 handoffs, about 2.5 %
    overhead.
  - Realistic after rework: **30-40 % of subagent ite**.
  - If L1 is adopted at 200k, L2's marginal saving falls to the quality gain
    plus the agent-reuse cases.
- **Failure modes and mitigations**:
  - **Lockout.** An agent that cannot write its report is stuck. The allowlist
    always admits the handoff write and SendMessage. After K=3 consecutive
    denials the reason escalates to "stop now; your worktree state is the
    handoff".
  - **Lost work.** The deny never kills. Work lives in the worktree, the
    allowlist permits a commit, and SubagentStop forces the report.
  - **False positive in a legitimately long task.** The coordinator can pass
    a higher `hard_tokens` per dispatch through an explicit brief marker
    (`budget: 400k`) read at SubagentStart and stored per `agent_id`. That is
    deterministic and visible.
  - **An unmeasurable transcript** (path missing, unparseable): **fail open
    with a logged, recorded "unmeasured" event.** This is not a security gate,
    and failing closed would lock out every agent whenever a Claude Code
    format change lands. This contradicts the "fail closed" standing rule only
    if the owner classes budgets as security, so it is flagged for the owner's
    decision in Task 1.2.
  - **A coordinator that cannot recover.** The main thread is out of scope
    (no `agent_id`), so the coordinator is never gated.
- **Tests**:
  - fixture transcripts with usage records, `<synthetic>` tails, a 300 KB
    trailing line and a compaction;
  - a tail-read proof by **read-count scaling** (a 1 MB file vs an 8 MB file
    gives the same number of seek/read calls; no timing asserts);
  - a deny/allow matrix across the tool allowlist;
  - once-per-band injection;
  - a SubagentStop block until the report exists;
  - an acceptance test through a real subagent in the main thread.

### L3: resume guard (SendMessage to a cold, large, stopped agent)

- **Mechanism**: PreToolUse `SendMessage`.
  1. Resolve `tool_input.to` to a transcript: an `agent-a<name>-*.jsonl` glob
     where the newest mtime wins, confirmed against `meta.json` `name`; or the
     raw agentId.
  2. Tail-read its context. Stopped means its last real assistant record has
     `stop_reason == "end_turn"`, or TeammateIdle was seen for it. Cold means
     the transcript mtime is older than `warm_seconds` (300, the subagent
     cache TTL).
  3. If it is stopped **and** cold **and** its context is at or above
     `max_resume_tokens`, deny. The reason names the route: "spawn a fresh
     agent from its last report or handoff file (path shown when found)".
  4. A warm resume is allowed, because it is cache reads only.
  5. Messages to a **running** agent are never gated: they do not resume
     anything.
- **Measured**: at 150k, **46 cold resumes**. Their first requests wrote
  **15.46 M tokens to the cache** (mean 336k per resume, 19.3 M ite, 1.2 %).
  The simulation of continuing from a 30k brief instead saves **5.8 %** of
  subagent ite (4.5 % at 250k).
- **Cost**: one glob of about 300 names plus a tail read, about 1 ms, and only
  on SendMessage calls.
- **Defaults**: client projects advisory (a warn, not a deny) at 250k; this
  repo deny at 150k.
  - Config: `handlers.pre_tool_use.resume_guard.options.{max_resume_tokens, warm_seconds, mode}`
- **Failure modes**:
  - Guarding a legitimate "one more small fix" to a huge agent. The explicit
    override is a message prefix (`RESUME-LARGE: <reason>`), which is recorded.
  - Name ambiguity: `SendMessage` itself refuses retargeted names (v2.1.199,
    sub-agents.md:1116). The guard uses the newest match and fails open on no
    match, because the message may target a cross-session peer.
  - It overlaps with L2: a resumed agent that is over the hard limit would be
    handoff-only anyway. L3 exists to avoid paying the cold cache write first.
- **Tests**: name resolution fixtures (two generations of the same name),
  warm/cold by fixture mtimes (set with `os.utime`, not the wall clock),
  running vs stopped, and the override prefix.

### L4: concurrency cap on Agent and resume

- **Mechanism**: PreToolUse `Agent` (spawn), plus L3's SendMessage path
  (resume of a stopped agent).
  - Live count = subagent transcripts in the session directory whose mtime is
    within `liveness_seconds` (for example 120 s) **and** whose last real
    record is not an `end_turn`.
  - It is reconciled by the `background_tasks[]` array on each Stop or
    SubagentStop, stored in a small registry like `thread_registry`.
  - At `max_concurrent` or above: deny, with the list of live agents, and say
    "wait for a completion notification".
- **Cost**: one `scandir` of about 600 entries plus N tail reads, about 1-3 ms,
  only on Agent and SendMessage.
- **What it saves**: **almost no total tokens.** The same work runs, only
  later. It lowers the **rate**: 86.5 % of subagent ite ran while more than 3
  agents were active, and the peak minute had 22. Under a cap of 3 the
  busiest 5-hour window (538 M ite) would spread across roughly
  (mean active / 3)× the wall time. That is what keeps a run under the 5-hour
  limit, which is the owner's actual pain. Secondary savings: fewer
  simultaneous completions means fewer coordinator turns at a 259k context.
- **Defaults**: client off; this repo `max_concurrent: 4`. The owner picks 3
  to 5 in Task 1.2.
- **Failure modes**:
  - A stale "live" count locks the coordinator out of spawning. Mitigations:
    mtime liveness expires by itself, the count is reconciled at every Stop,
    and the deny message names the agents so the coordinator can TaskStop one.
  - It must never deny the coordinator's own SendMessage to a **running**
    agent.
- **Tests**: fixture session directories with mtimes via `os.utime`; the
  reconcile path from a Stop payload's `background_tasks`; that the cap does
  not count `end_turn` agents.

### L5: rate-aware governor (five-hour percentage)

- **Mechanism**:
  - `context_sidecar` adds `five_hour_pct` and `resets_at` from
    `rate_limits.five_hour`.
  - PreToolUse Agent and SendMessage (resume) read the sidecar through
    `mtime_cache`. At `advise_pct` (for example 70) they advise "serialise
    now". At `deny_pct` (for example 90) they deny new spawns and resumes,
    naming the reset time. Running agents are untouched.
  - A sidecar older than `max_age_seconds` counts as unknown: advise, never
    deny.
- **Cost**: one stat, and a small JSON parse when the mtime moves.
- **Defaults**: client advisory at 80 %; this repo deny at 90 %.
- **Failure modes**:
  - A headless session with no status line has no sidecar, so the lever is
    inert. That is recorded, not silent.
  - Blocking the very handoff a user wants near the limit: spawning a fresh
    agent from a handoff is still a spawn. Allow a spawn whose prompt names a
    handoff file.
- **Tests**: fixture sidecar JSON (fresh, stale, missing) and the threshold
  matrix.

### L6 and L7: spend ledger and meter

- **Mechanism**:
  - Extend `subagent_cache_aggregator` to record `requests`, `max_ctx`,
    `mean_ctx`, ite, `compactions` and `inbound_messages`, plus the plan key.
    The plan key comes from `gitBranch` or `cwd` in the records, which name
    the worktree and plan.
  - Switch it to the offset cache so a resumed giant is not rescanned each
    stop.
  - A new `hooks-daemon spend [--session] [--by plan|agent]` CLI.
  - A status segment `Σ⚙ 1.66G ite · 7 live · max 412k`.
- **Cost**: per stop, O(new bytes). The status line reads the sidecar
  directory through `mtime_cache`.
- **Defaults**: on everywhere (measurement only).
- **Failure modes**: sidecar-directory growth (prune with the session);
  double counting across resumes (key by `requestId`, which is idempotent).
- **Tests**: dedup across resume generations; offset-cache correctness when a
  file is appended, truncated or replaced (inode change); CLI golden output.

### L8: CLAUDE.md diet (daemon-generated block)

- **Mechanism**: the generated guidance block keeps one line per handler and
  moves the long prose behind `explain-rule`. Alternatively, ship `omitClaudeMd`
  agent definitions for scouts and reviewers.
- **Saving**: an upper bound of about 6 % of subagent ite, plus about 13 % of
  each fresh agent's first-request write.
- **Risk**: agents that do not know a rule hit more denies, and each deny is a
  turn at full context. **Measure the blocked-call rate before and after**
  from `logs/hooks/verdicts.jsonl`. Medium build cost, because it touches the
  generator and docs QA.

### L9: review-round convergence advisory

- **Mechanism**: PreToolUse Agent. When the description or prompt matches
  `review` and names a plan number or branch, it increments a per-key counter.
  At round ≥ `advise_at` (4) it advises the coordinator: "round N on <key>:
  compare this round's findings count to the last; consider an owner
  decision".
- **Evidence**: review agents are 23.2 % of subagent ite. Plan 463 dispatched
  12 review agents.
- **Deterministic?** The trigger (the count) is; whether the rounds are
  converging is not. Advisory only.
- **Default**: advisory on in this repo, off for clients.
- **Tests**: counter keying and a regex fixture table.

## 4. Ranking: (spend saved) / (build cost × risk)

| Rank | Lever                                               | Saved (this session, subagent ite)                                | Build                               | Risk                                                      | Note                                                        |
| ---- | --------------------------------------------------- | ----------------------------------------------------------------- | ----------------------------------- | --------------------------------------------------------- | ----------------------------------------------------------- |
| 1    | L1 autocompact recommendation (window ~230k)        | ~40-48 % gross                                                    | tiny (report)                       | low; owner's trade-off on coordinator recall              | biggest ratio, no enforcement code                          |
| 2    | L2 subagent context budget (soft 150k / hard 250k)  | 30-40 % realistic (46 % net upper bound at 200k)                  | medium                              | medium (lockout, mitigated by allowlist and SubagentStop) | the only lever that guarantees a clean handoff; overlaps L1 |
| 3    | L3 cold-resume guard (150k)                         | 5.8 % (46 events, 15.5 M cache write avoided)                     | small                               | low                                                       | complements L2: avoids paying the cold write first          |
| 4    | L6 and L7 spend ledger and meter                    | 0 directly; enables tuning                                        | small (extends existing aggregator) | very low                                                  | prerequisite for measured thresholds                        |
| 5    | L4 concurrency cap (3-4) plus L5 five-hour governor | ~0 % total; cuts peak rate (86.5 % of spend ran at >3 concurrent) | medium                              | medium (stale count lockout)                              | the lever for "hit the 5-hour limit"                        |
| 6    | L8 CLAUDE.md diet                                   | ≤6 %                                                              | medium                              | medium (more denies)                                      | measure blocked-call rate first                             |
| 7    | L9 review convergence advisory                      | unknown, within the 23 % review share                             | small                               | low (advisory)                                            | heuristic                                                   |

**Combined estimate requested by the brief** (150k soft budget, a resume
guard and a 3-agent cap):

- The budget at 150k, if followed as a handoff: about 55 % gross, about 52 %
  after coordinator overhead, **about 35-45 % realistic** after rework.
- The resume guard's marginal addition on top of that is about 1.2 % (the
  cold writes). Its standalone 5.8 % is mostly subsumed.
- The 3-agent cap saves no total tokens. It would have spread the busiest
  5-hour window (538 M ite) over several windows, which is what avoids the
  limit.
- In total, roughly **40 % less subagent spend**, which is **35 % of the
  whole session**, plus the peak rate cut.

## 5. Open questions for Task 1.2 (owner)

1. Autocompact: accept compacting the coordinator at ~200k as well, or keep
   main large and rely on L2 for subagents?
2. Should a budget gate that cannot measure fail open (proposed) or closed?
3. The cap value (3, 4 or 5) and whether it counts resumes.
4. Whether per-dispatch budget overrides (`budget: 400k` in the brief) are
   acceptable.
5. The Phase 2 prerequisite: capture a real subagent PreToolUse payload to
   confirm whether its `transcript_path` is the agent's own or main's.

## 6. Token-efficiency best practice for multi-agent work

**Sources.** `PC` = `remote-docs/code.claude.com/docs/en/prompt-caching.md`
and `SA` = `sub-agents.md` (vendored copies, licence marked unreviewed). "This
session" means the section 1.3 data. A claim with no cited source is marked
**unverified**.

### 6.1 Forking versus a fresh subagent

**What the docs say.**

- A fork inherits the parent's system prompt, tools, model and full history
  (SA:1147-1196).
- Because the fork's prefix is identical, its first request reads the parent's
  cache, and forking is "cheaper than spawning a fresh subagent for tasks that
  need the same context" (SA:1194; PC:337).
- A fresh subagent's first request cannot read the parent's cache and warms its
  own (PC:331).
- Forks and subagents sit in the "everything else" TTL bucket: 5 minutes,
  even on a subscription (PC:267-277, 333).
- `/subtask` forks into a background subagent. With agent view on, `/fork`
  instead copies the whole session into a new background session, and that
  copy also keeps the original's cache intact (SA:1149-1151; PC:340).
- A fork cannot spawn forks (SA:1196).

**What the docs leave out.** A cheap first request is the whole of the
saving. Every later fork request re-sends the parent's inherited context
(PC:25-27, "re-sends the full context"). Those re-sends are cheap cache
reads, but they still carry the parent's full size.

**Arithmetic.** For n fork turns on a parent context of C, and a fresh agent
built from a brief of size B:

- fork ≈ n·C·0.1;
- fresh ≈ 1.25·B + n·B·0.1, plus the turns it spends rediscovering what the
  parent knew.

The fork only wins when C is small, or when rediscovery would cost more than
about n·(C − B)·0.1. Take a fork of this session's coordinator (mean context
259k) for a 68-turn task (the fresh-agent median here). It would pay about
1.76 M ite in inherited reads alone. A fresh agent from a 36k base pays about
0.29 M ite before its own growth.

**What this session shows.**

- The 21 forks were all spawned by subagents (spawnDepth 1). None was spawned
  by main.
- Their first requests read only 7,660 cached tokens and wrote about 29k:
  median first context 36,753, against 36,406 for fresh agents. They did
  **not** share the parent's history cache as SA:1194 describes. **Why is
  unverified.** The likely cause is that a fork spawned from a subagent does
  not inherit that subagent's history, but the docs describe forking only
  from the main session.
- Forks cost 23k ite per request against 35k for all others. They were short.

**Rule.** Fork from main only when main's context is small (under about
100k) or the task is a few turns long. Otherwise start fresh from a brief
file.

### 6.2 How cache reads are billed and counted

- A cache read is billed at "roughly 10% of the standard input rate". A cache
  write is billed at the write rate (PC:319-320).
- A 1-hour TTL write costs more than a 5-minute one. The docs link to API
  pricing for the figure (PC:261).
- A compact while the cache is warm costs "a fraction" of the context size. A
  compact after the TTL has expired reprocesses the full history uncached
  (PC:180-182).
- Resumed subagents can read the cache the original run warmed (PC:343), but
  only within the 5-minute TTL. That is the case section 3 L3 separates.
- **How cache reads count toward the subscription's 5-hour and weekly usage
  limits is unverified.** The vendored docs describe API billing and TTL
  choice only (PC:272-279). They say nothing about limit accounting.
  - The limit is visible only as `rate_limits.five_hour.used_percentage` in
    the Status payload (section 1.1).
  - Phase 2 can measure the relationship: log that percentage against the
    session's summed cache_read, cache_write and output from the L6 ledger.
  - Until that is measured, treat context size × turns as the cost driver.
    Even at 0.1×, cache reads were most of this session's ite. For example,
    `plan464-impl`: 1,829 requests at a mean context of 330k.

### 6.3 Model and effort per role

- The docs recommend routing tasks to cheaper models "like Haiku" to control
  costs (SA:33).
- Model resolution order: per-invocation `model`, then frontmatter, then
  `CLAUDE_CODE_SUBAGENT_MODEL`, then main's model (SA:365-371).
- The `opus` alias resolves to main's exact model when main is in that family
  (SA:373).
- Explore has inherited main's model since v2.1.198. To keep it cheap, define a
  project `Explore` with `model: haiku` (SA:53-55).
- In this repo's `.claude/agents/`:
  - the dedupe scout and qa-runner are Haiku;
  - python-developer and qa-fixer are Sonnet;
  - the reviewers and docs-qa are Opus.
- Yet Haiku was **0.4 %** of subagent ite in this session. Most spend came
  from ad-hoc named teammates: Sonnet 53.6 %, Opus 45.2 %. The cheap tier
  caught almost none of the volume.
- The `effort` frontmatter overrides the session effort per subagent
  (SA:321). **How much lower effort saves in tokens is unverified.** No
  vendored figure exists. It plausibly cuts thinking output, which is priced
  at the output rate.

### 6.4 Brief files and reports as files

- **Brief files.** The Agent `prompt` is part of the coordinator's tool call,
  so it stays in the coordinator's context and is re-sent on every later
  coordinator request until a compaction (PC:25-27).
  - Here main compacted 28 times in 8,314 requests, about 300 requests per
    cycle.
  - So a 3k-token inline brief costs about 3k × 150 × 0.1 ≈ 45k ite in the
    coordinator. A one-line pointer to a brief file costs almost nothing.
  - The subagent pays the same either way.
  - This is arithmetic from the docs' mechanism, not a measured figure.
- **Reports as files.** Subagent results return into main's context, and
  "many subagents that each return detailed results can consume significant
  context" (SA:984-986).
  - An inline report is re-sent on every coordinator request by the same
    arithmetic: about 60k ite for a 4k-token report.
  - A roughly 24k-token inline return was also silently cut in the middle
    (Plan 00307 evidence, `dispatch_declaration.py:3-7`).
  - The daemon already enforces this: `dispatch_declaration` on the way out and
    `subagent_report_size_blocker` at 4,000 characters.

### 6.5 Workflow scripts versus ad-hoc agents

- In a workflow fan-out of agents with the same prefix, Claude Code holds all
  but the first agent for up to 5 seconds. Their first requests can then read
  the prefix the first agent cached (PC:344).
- Workflow agents follow their own concurrency limits, not the subagent cap
  (SA:1055).
- Otherwise the workflow docs are **not vendored**. Any further claim, such as
  scripts bounding rounds or reducing coordinator turns, is **unverified**
  (the local `workflow-authoring` skill is the reference to check).
- Inferred, not documented: a script that runs a fixed review, fix and
  re-review loop with a round cap would bound L9's non-converging reviews
  deterministically. It would also keep those turns out of the 259k-context
  coordinator.

### 6.6 Other levers, briefly

- **Compaction threshold.** See L1. The override applies to subagents
  (SA:1130).
- **Cold starts.** A subagent's CLAUDE.md load and first-request cache write
  are paid for every fresh agent (SA:1063-1068; PC:331). This favours fewer,
  mid-sized agents over many tiny ones, and `omitClaudeMd` for scouts
  (SA:1072). Measured here: the median first context is 36k, of which the
  90 KB CLAUDE.md is about 22k.
- **Side questions.** For a question about something already in context, use
  `/btw`, not a subagent: it has no tools and adds nothing to history
  (SA:1013).

### 6.7 Best-practice rules for this repo's coordinator

| #   | Rule                                                                                                                                                                                 | Source                                                         | Daemon-enforceable?                                                                                                                          |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| C1  | One task per agent. Never send a second "NEW TASK" to a finished agent. Start fresh from its report.                                                                                 | 1.3 (reuse: 14-19 inbound messages on the top agents); SA:1088 | **Yes:** L3 resume guard (a deny when cold and large)                                                                                        |
| C2  | An agent hands off at about 150k. The coordinator dispatches a successor from the handoff file.                                                                                      | section 3 L2 sim                                               | **Yes:** L2 budget                                                                                                                           |
| C3  | Keep at most 3-4 agents running, fewer as the 5-hour percentage rises.                                                                                                               | 1.3 concurrency; SA:1048-1055                                  | **Yes:** L4 and L5                                                                                                                           |
| C4  | Brief in a file. The Agent prompt carries a path and a few lines.                                                                                                                    | 6.4; PC:25-27                                                  | **Yes:** extend `dispatch_declaration` with a prompt-length ceiling plus a path requirement (advisory first)                                 |
| C5  | Reports go to files. The inline reply is 3 lines plus a path.                                                                                                                        | 6.4; SA:984                                                    | **Already:** `dispatch_declaration`, `subagent_report_size_blocker`                                                                          |
| C6  | Model by role: Haiku for search, scouting and mechanical QA; Sonnet for implementation; Opus only for review and judgement.                                                          | SA:33, 365-373                                                 | **Partly:** advisory on Agent when `model`/`subagent_type` is missing or Opus for a scout-shaped description. The role match is a heuristic. |
| C7  | Do not fork from a large coordinator. Fork only under about 100k of main context.                                                                                                    | 6.1; SA:1194                                                   | **Yes:** Agent with `subagent_type: fork` from main, with main's context read from the Status sidecar (advise or deny)                       |
| C8  | Cap review rounds (for example 4), then take it to the owner, or run the loop as a Workflow with a round limit.                                                                      | 1.3 (Plan 463: 12 reviewers); 6.5                              | **Advisory only:** L9 counter                                                                                                                |
| C9  | Do not resume an agent idle over 5 minutes unless it is small.                                                                                                                       | PC:267-277, 343                                                | **Yes:** L3 (`warm_seconds`)                                                                                                                 |
| C10 | L1 (lowering the autocompact window) was **dropped by the owner** in Task 1.2: the only setting also compacts the orchestrator, and nothing targets subagents alone. C2 replaces it. | L1; SA:1130                                                    | **No.** Owner env (X1). Superseded by L2.                                                                                                    |
