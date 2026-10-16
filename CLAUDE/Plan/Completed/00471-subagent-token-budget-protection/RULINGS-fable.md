# Plan 00471: Fable rulings on Task 1.2

**Standing**: Fable ruling under the owner's delegation ("use fable to answer
questions"). These are engineering choices only. They are recorded as Fable
rulings, never as the owner's. Anything marked **left to owner** is unruled.

**Evidence base**: `subagent-reports/260925-p471-brainstorm-opus-5-5.md`
("471-B"), PLAN.md Task 1.2 (L1 already dropped), the sibling rulings in
[../00472-subagent-model-tier-selection/RULINGS-fable.md](../../00472-subagent-model-tier-selection/RULINGS-fable.md),
and the state of the tree as checked while ruling:

- The reuse points 471-B names all exist: `subagent_cache_aggregator.py`,
  `context_sidecar.py`, `mtime_cache.py`, `dispatch_declaration.py`,
  `core/handler_scope.py`, plus `pre_tool_use/agent_dispatch_recorder.py` and
  `utils/agent_dispatch_registry.py` (Plan 00518), which already record a
  per-session row per named dispatch and are the natural home for any
  per-dispatch override.
- No handler named in 471-B exists yet (no `subagent_context_budget`,
  `resume_guard` or similar in `src/` or `tests/`).
- `payload_capture` is off and scoped to `Status`; `untracked/payload-capture/`
  is empty. No subagent `PreToolUse` payload has ever been captured, so
  471-B's open question 5 is still open on evidence.
- 471-B's analysis script is gone; its output
  `untracked/scratch/p471_spend.json` survives and is the measured baseline.

## 1. Rulings on the open questions (471-B section 5)

### Q1. Autocompact: compact the coordinator at ~200k too, or keep main large and rely on L2?

**Ruling: keep main large; L2 is the subagent lever. L1 stays dropped.**

PLAN.md Task 1.2 already records the owner's decision, and the evidence
supports it: the one setting (`CLAUDE_CODE_AUTO_COMPACT_WINDOW`) also compacts
the coordinator, main compacted 28 times at 566k in the measured session, and
471-B notes that past about 8 compactions a summary chain loses fidelity. A
coordinator that loses recall costs more re-dispatches than the 13.5 % of
session ite that main spends. The daemon can change no env in any case (X1),
and the owner's user settings are out of scope. The daemon ships the measured
`compact_boundary` distribution in the spend report (L6) so the owner can
revisit with numbers, and nothing else.

### Q2. A budget gate that cannot measure: fail open or closed?

**Ruling: fail open, with a recorded `unmeasured` verdict, and the count
surfaced.**

A context budget is a cost control, not a security gate. Failing closed would
deny every tool call of every subagent the moment Claude Code changes its
transcript format or moves the file, which is a whole-session lockout the
owner cannot clear while away. Failing open silently would hide the same
format change. So the gate allows, records one `unmeasured` verdict per
`(agent_id, reason)` in `logs/hooks/verdicts.jsonl`, and the spend report and
status segment show the unmeasured count. The build must test that an
unmeasured agent costs exactly one record, not one per tool call.

### Q3. The concurrency cap value, and whether it counts resumes.

**Ruling: 4, counting cold resumes, as an advisory. Deny mode is not built
now.**

471-B is explicit that L4 saves almost no total tokens; it cuts peak rate,
which is the lever against the 5-hour limit. Its failure mode is a stale
"live" count locking the coordinator out of spawning, which is the one
outcome worse than the inferno while the owner is away. So the live count is
built and measured (it feeds the ledger and the status segment), and at 4 or
more live agents a spawn or cold resume draws an advisory naming the live
agents. A cold resume counts because in cost terms it is a spawn with a
336k mean cache write (471-B section 3 L3). Clients: off. This repo: advise
at 4. Whether to add a deny mode is decided later from the ledger's evidence
that the count is accurate (see section 3).

### Q4. Per-dispatch budget overrides (`budget: 400k` in the brief)?

**Ruling: accepted, bounded, and recorded.**

A legitimately long task (a full migration, a large security sweep) must not
hit the hard budget mid-flight with no route but a handoff; the override is
deterministic and visible, which 471-B's own criteria ask for. The form is a
line `budget: <N>k` in the Agent `prompt`. It is read at PreToolUse `Agent`
and stored by agent `name` in the existing `agent-dispatch-registry` row
(the dispatch call is the only moment the pair is visible, which is exactly
why `agent_dispatch_recorder` exists). An unnamed agent cannot carry an
override. The value is clamped to `max_override_tokens` (this repo: 450k,
below the 567k the environment compacts at) so an override can raise the
budget but never switch the gate off, and every override is a ledger row.

### Q5. Capture a real subagent PreToolUse payload to confirm `transcript_path`.

**Ruling: the implementer captures it in this repository; the resolver is
built to work either way, so the capture confirms rather than gates.**

This needs no owner: flip `payload_capture.enabled: true` with
`events: [PreToolUse]` in a dogfood session, restart the daemon, dispatch one
subagent, read one captured record, then revert the config. The transcript
resolver accepts both documented possibilities: if `transcript_path`'s
basename is `agent-<agent_id>.jsonl` it is used directly; otherwise the path
is `<dirname(transcript_path)>/<session_id>/subagents/agent-<agent_id>.jsonl`.
If neither exists the gate is `unmeasured` (Q2). The captured record goes in
`subagent-reports/` as the fixture source.

## 2. Build scope (implementable now, TDD, no further owner input)

Order matters: 2.0 and 2.1 are prerequisites for everything else and are
shared with Plan 00472 (its decision 7 rules one ledger for both plans).

### Task 2.0: transcript readers (utils)

- A tail reader: last non-`<synthetic>` assistant `usage` and `message.model`
  from a seek-to-EOF window that doubles on a miss (471-B section 1.4).
- An offset cache `{path: (inode, size, offset, totals)}` persisted to a
  sidecar, reset on inode change or shrink, giving cumulative spend in
  O(new bytes).
- The agent-transcript resolver of Q5.
- Tests: fixture transcripts with `<synthetic>` tails, a 300 KB trailing
  line and a `compact_boundary`; the tail reader proven by read-count
  scaling (same number of reads for a 1 MB and an 8 MB fixture, no timing
  asserts); offset-cache correctness on append, truncate and replace.

### Task 2.1: spend ledger and CLI (L6)

- Extend `subagent_cache_aggregator` to the offset cache and record per agent:
  `requests`, `max_ctx`, `mean_ctx`, ite, `compactions`, `inbound_messages`,
  the plan key (from `gitBranch`/`cwd`), and the fields 00472 needs
  (`model_param`, `source`, `resolved`, `per_model_requests`).
- `hooks-daemon spend [--session] [--by plan|agent]` printing the 471-B
  section 1.3 tables for the live session, plus the `compact_boundary`
  distribution (Q1) and the unmeasured count (Q2).
- Tests: dedup by `requestId` across resume generations; CLI golden output
  from fixtures.

### Task 2.2: subagent context budget (L2)

- PreToolUse handler `subagent_context_budget`, scope SUB.
- Soft band: `additionalContext` once per `(agent_id, band)`; the advice
  names the handoff path convention (`<plan>/subagent-reports/…-handoff.md`),
  WIP commit, and SendMessage to the lead.
- Hard band: deny every tool except Write/Edit under `handoff_globs`, Bash
  matching `allowed_bash_prefixes` (`git status|diff|add|commit|log`),
  SendMessage, and Read of the handoff file; the reason names the exact path
  and the three steps; after 3 consecutive denials the reason escalates to
  "stop now; your worktree state is the handoff".
- SubagentStop companion: block the stop of an over-hard-budget agent until
  the handoff file exists (reuse `subagent_report_path_verifier`).
- The Q4 override and the Q2 unmeasured path.
- Config: `options.{soft_tokens, hard_tokens, handoff_globs, allowed_bash_prefixes, exempt_agent_types, max_override_tokens}`.
- **Shipped defaults**: clients soft 300k, hard off (`null`). This repo soft
  150k, hard off. Hard mode is built and proven by tests and an acceptance
  test; enabling it in this repo's config is **left to owner** (section 3).
- Tests: deny/allow matrix across the allowlist; once-per-band; escalation
  after 3 denials; SubagentStop block; override clamp; unmeasured allows with
  one record; an acceptance test through a real subagent in the main thread.

### Task 2.3: resume guard (L3)

- PreToolUse `SendMessage`: resolve `to` to a transcript (newest
  `agent-a<name>-*.jsonl`, confirmed by `meta.json` `name`, or the raw
  agentId); deny when the agent is stopped (`end_turn` or TeammateIdle seen),
  cold (mtime older than `warm_seconds`, 300), and at or above
  `max_resume_tokens`. The reason names the fresh-spawn route and the last
  report or handoff file when found. Override prefix `RESUME-LARGE: <reason>`
  is honoured and recorded. No match (a cross-session peer) fails open.
  Messages to a running agent are never gated.
- **Defaults**: clients advise at 250k; this repo deny at 150k. The deny is
  acceptable here because it never strands anything: the coordinator can
  always spawn fresh, and the override is one prefix.
- Tests: two generations of one name; warm/cold via `os.utime`; running vs
  stopped; the override; the no-match fail-open.

### Task 2.4: live count and five-hour percentage (L4, L5, measurement plus advisory)

- Live count: subagent transcripts in the session directory with mtime within
  `liveness_seconds` (120) whose last real record is not `end_turn`, reconciled
  against `background_tasks[]` at Stop and SubagentStop in a registry shaped
  like `thread_registry`.
- `context_sidecar` gains `five_hour_pct` and `resets_at`.
- One advisory handler on PreToolUse `Agent` and on L3's resume path: at
  `max_concurrent` (this repo 4, clients off) name the live agents; at
  `advise_pct` (this repo 70, clients 80) say "serialise now" and name the
  reset time. A sidecar older than `max_age_seconds` is unknown and draws no
  advisory. No deny mode in either.
- Tests: fixture session directories with `os.utime`; reconcile from a Stop
  payload; `end_turn` agents not counted; sidecar fresh/stale/missing matrix.

### Task 2.5: status segment (L7, shared with 00472 T2)

- One segment from the ledger through `mtime_cache`: summed subagent ite, live
  count, largest live context, unmeasured count, and 00472's per-family live
  counts. Tests: render from fixture sidecars.

### Task 2.6: review-round advisory (L9)

- PreToolUse `Agent`: when description or prompt matches `review` and names a
  plan number or branch, count per key; at `advise_at` (4) advise the
  coordinator to compare findings counts and consider an owner decision. The
  counter is the one 00472 would have shared with T6 (dropped there), so it
  lives here alone. This repo on, clients off. Tests: keying and a regex
  fixture table.

### Task 2.7: docs, config manifest, dogfood, baseline

- `docs/guides/HANDLER_REFERENCE.md` entries, the config-changes manifest,
  and the holding-area entry for release-bound consequences.
- Copy `untracked/scratch/p471_spend.json` into `subagent-reports/` as the
  measured baseline; it is the only surviving artefact of the analysis.
- Dogfood: one real session in this repo whose `hooks-daemon spend` output
  and `verdicts.jsonl` show ledger rows and at least one soft advisory. The
  journal records the run.

**Not in scope** (section 3 says where each goes): L8 CLAUDE.md diet; L4 and
L5 deny modes; enabling L2 hard mode in this repo; any env or user setting.

## 3. What cannot be done now, and where it goes

| Item                                                     | Why not now                                                                                                                              | Ruling                                                                                                                                                                                                  |
| -------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| L1 autocompact window                                    | Owner env; also compacts the coordinator                                                                                                 | **(c) dropped**, already decided in Task 1.2. The spend report carries the distribution so the owner can revisit.                                                                                       |
| Enabling L2 hard mode (`hard_tokens: 250k`) in this repo | A one-line config change that alters how the owner's live sessions behave, with a lockout failure mode the owner cannot clear while away | **(a) build it off, proven by tests.** The flip is **left to owner**; the ruling recommends 250k once the dogfood run shows the soft band firing with zero unmeasured events.                           |
| L4 and L5 deny modes                                     | Stale-count and stale-sidecar lockouts; the rate benefit is unproven until the live count is shown accurate                              | **(b) follow-up plan**, opened only if the ledger shows the live count matches `background_tasks[]` and the 5-hour percentage is being hit. Advisory modes ship now.                                    |
| L8 CLAUDE.md diet                                        | Touches the generator and docs QA; the risk (more denies) can only be judged against a blocked-call baseline                             | **(b) follow-up plan.** First deliverable there is the blocked-call rate from `verdicts.jsonl`, which this plan's ledger makes cheap.                                                                   |
| Relationship between cache reads and the 5-hour limit    | Unpublished weighting (X6); needs a long real run                                                                                        | **(a) build defensively.** The sidecar logs `five_hour_pct` beside the ledger totals, so the relationship can be read off later. No lever assumes it.                                                   |
| Proof of realistic savings (30-40 %)                     | Needs a representative coordinated run after the levers ship                                                                             | **(c) dropped as a closing criterion.** Success is that the levers fire and are measured, not a savings figure. Re-measurement is a one-off `hooks-daemon spend` comparison against the baseline later. |
| The subagent PreToolUse payload shape                    | Never captured                                                                                                                           | **(a)** the implementer captures it (Q5); the resolver works either way.                                                                                                                                |

## 4. Success criteria after this ruling (each verifiable)

01. `hooks-daemon spend` prints, for the live session, per-agent `requests`,
    `max_ctx`, `mean_ctx`, ite, `compactions`, `inbound_messages` and the plan
    key, plus the `compact_boundary` distribution and the unmeasured count;
    a golden-output test covers it from fixture transcripts.
02. The tail reader's read count is the same for a 1 MB and an 8 MB fixture,
    and the offset cache gives the same totals after append, truncate and
    inode replacement; unit tests assert both.
03. In a SUB-scoped PreToolUse at or above `soft_tokens`, the budget handler
    injects `additionalContext` exactly once per band; the acceptance test
    shows it through a real subagent in this repo.
04. With `hard_tokens` set in a test config, every tool outside the allowlist
    is denied with a reason naming the handoff path, the allowlisted writes,
    commit and SendMessage pass, the reason escalates after 3 consecutive
    denials, and SubagentStop is blocked until the handoff file exists; the
    shipped config has `hard_tokens: null` everywhere.
05. An unreadable or missing agent transcript allows the call and writes one
    `unmeasured` verdict per `(agent_id, reason)`; the spend report shows the
    count.
06. A `budget: <N>k` line in a named dispatch's prompt raises that agent's
    budget, clamped to `max_override_tokens`, and is a ledger row; an unnamed
    dispatch's line is ignored.
07. The resume guard denies a SendMessage to a stopped, cold, at-or-above-
    threshold agent under this repo's config, allows warm, running, overridden
    and unresolvable targets, and the deny reason names the last report file
    when one exists.
08. The live count excludes `end_turn` agents and reconciles against a Stop
    payload's `background_tasks[]`; the concurrency and five-hour advisories
    fire at their thresholds and never deny; a stale sidecar draws nothing.
09. The status segment renders spend, live count, largest live context and
    unmeasured count from fixture sidecars.
10. The review-round counter advises at round 4 on the same key and is silent
    below it.
11. `docs/guides/HANDLER_REFERENCE.md` and the config-changes manifest
    describe every new handler and option; the pending-release holding area
    records this plan's release-bound consequences (new handlers, new config
    keys, the new CLI command).
12. `untracked/scratch/p471_spend.json` is copied into `subagent-reports/`
    as the baseline, and the dogfood journal entry cites a `hooks-daemon spend` run and a soft-advisory verdict from a real session.
13. Targeted QA is green on the work branch; the coordinator's full gate is
    green before merge.

When all thirteen hold, the plan closes with L2 hard mode, the L4/L5 deny
modes and L8 recorded as the follow-ups in section 3, and nothing waiting on
the owner.
