# Plan 00472 Task 1.1: brainstorm on subagent model tier selection

Author: p472-brainstorm (Opus 5.5). Research only: no source changed. This
builds on the Plan 00471 brainstorm (`../../00471-subagent-token-budget-protection/subagent-reports/260925-p471-brainstorm-opus-5-5.md`,
"471-B" below) and does not repeat its spend and caching ground.

- Analysis script: `untracked/scratch/p472_tiers.py`. Output:
  `untracked/scratch/p472_tiers.json`. It streams all 4 main transcripts and
  389 subagent transcripts in one pass.

- **ite** is the same unit as 471-B (input 1, cache write 1.25, cache read
  0.1, output 5). **$eq** means ite × the model's list input price per MTok,
  from the `claude-api` skill's model table:

  | Model     | Input $/MTok | Output $/MTok |
  | --------- | ------------ | ------------- |
  | Fable 5.1 | 10           | 50            |
  | Opus 5    | 5            | 25            |
  | Opus 5.5  | 4            | 20            |
  | Sonnet 5  | 2            | 10            |
  | Haiku 4.5 | 1            | 5             |

  $eq is a price-weighted proxy for comparing tiers. It is not a bill: the
  subscription's weighting is unpublished (471-B §6.2).

- Docs: `SA` = `remote-docs/code.claude.com/docs/en/sub-agents.md`, `HK` =
  `hooks.md`. These are vendored copies with an unreviewed licence.

## 1. Observability: what the daemon can see

### 1.1 Surfaces

| Surface                       | Model-relevant fields                                                                                                                                                                                               | Source                                                                                                                             |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| PreToolUse `Agent`            | `tool_input.model` (an alias, optional), `subagent_type`, `name`, `description`, `prompt`. **No resolved model and no parent model.**                                                                               | HK:1764-1773                                                                                                                       |
| PostToolUse `Agent`           | `tool_response.resolvedModel` on **both** `completed` and `async_launched`, plus `modelsUsed` when the model was swapped mid-run (v2.1.212+). It covers the model at launch, not later swaps of a background agent. | HK:1782-1793. Verified: 49 `resolvedModel` records in the e5e72775 main transcript                                                 |
| SubagentStart                 | `agent_id` and `agent_type` only. **No model.** Cannot block.                                                                                                                                                       | HK:2375-2390                                                                                                                       |
| SubagentStop                  | `agent_type` and `agent_transcript_path`. The model is in that transcript.                                                                                                                                          | HK:2413                                                                                                                            |
| SessionStart                  | `model` (the orchestrator's model), sometimes omitted                                                                                                                                                               | HK:1162-1167                                                                                                                       |
| Status (status line)          | `model.id` of main. `context_sidecar` already persists it as `model_id` on every render                                                                                                                             | `handlers/status_line/context_sidecar.py:124-142`                                                                                  |
| Transcript assistant records  | `message.model` per API request. This is ground truth, including safety-fallback swaps                                                                                                                              | measured below                                                                                                                     |
| `subagents/agent-*.meta.json` | `agentType`, `customAgentType`, `name`, `model`, `toolUseId`, `isFork`, `spawnDepth`, `parentAgentId`                                                                                                               | measured below                                                                                                                     |
| Agent definitions             | frontmatter `model:` (an alias, a full id, or `inherit`)                                                                                                                                                            | `utils/subagent_tool_resolution.py:213` `resolve_agent_definition` already resolves project, user, built-in and plugin definitions |

### 1.2 Resolution order and how to classify the source

Claude Code resolves a subagent's model in this order (SA:364-369):

1. the per-invocation `model` parameter;
2. the frontmatter `model` (`inherit` means main's model);
3. `CLAUDE_CODE_SUBAGENT_MODEL`;
4. main's model.

Exceptions that a classifier must model (SA:49-55, 371-422):

- A family alias names main's **exact** model when main is in that family.
  For example, `model: opus` under an Opus 5.5 main runs Opus 5.5.
- Built-in Explore inherits main's model **capped at Opus** on the Claude API.
  Env step 3 does not apply to Explore or Plan. A project-level `Explore`
  definition overrides the built-in.
- A fork always inherits.
- `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` overrides everything except forks and
  `inherit` skills.
- `availableModels` substitution. Interactive sessions show a warning.
- A per-invocation `model` persists across resume (v2.1.211+).

**Daemon classifier at PreToolUse:**

| Condition                                                      | Source label       |
| -------------------------------------------------------------- | ------------------ |
| `subagent_type == "fork"`                                      | `fork`             |
| `tool_input.model` set                                         | `explicit`         |
| the definition's frontmatter model is set and is not `inherit` | `definition`       |
| the env variable is set                                        | `env`              |
| built-in Explore                                               | `inherited-capped` |
| otherwise                                                      | `inherited`        |

- It is cheap: one definition lookup (already done by
  `dispatch_declaration`/`agent_isolation_advisor`) plus a dict read.
- The one input it lacks is main's model. There are two sources:
  - The `context_sidecar` `model_id`. It is headful only and one stat through
    `mtime_cache`.
  - A tail read of the spawner's transcript for the last non-`<synthetic>`
    `message.model`: 59 µs (471-B §1.4). This works headless and **also for a
    subagent that spawns a subagent** (the spawner's own transcript, path
    derived as in 471-B §1.1).
- Recommended: tail read first, then the sidecar, then "unknown". Unknown
  means the advisory is not given (fail open; this is not a security gate).
- **The env variable is a gap.** The daemon process's environment is not the
  Claude Code process's. Phase 1 must probe whether the hook subprocess
  inherits `CLAUDE_CODE_SUBAGENT_MODEL`. Until that is confirmed, PostToolUse
  `resolvedModel` corrects any misclassification after the fact.

**`meta.json`'s `model` field is not usable as the source.** Measured over
389 agents:

- It holds the explicit parameter when one was passed.
- Otherwise it holds the frontmatter value (55 `sonnet`), the parent's model
  in varying spellings (67 `opus`, 33 `claude-opus-5-5`), `inherit` (21
  forks), or null (61).
- So "inherited" and "definition" cannot be told apart from it. The
  PreToolUse `tool_input` plus the definition lookup is the only clean source
  of *how* the model was chosen. `resolvedModel` and the transcript are the
  clean source of *what* model ran.

### 1.3 Mid-run swaps are real

Three security-review agents (`review-guards-5`, `-v3`, `-v4`) started on Opus
5.5 and ran **60 %, 55 % and 69 % of their requests on Opus 4.8**. This is
the safety-classifier fallback that `model_fallback_detector` watches for on
the main thread, happening inside subagents.

The consequence for the ledger: it must record per-request models from the
agent transcript (or `modelsUsed`), not only `resolvedModel` at launch. It
should also surface "subagent silently downgraded", which is the inverse of
this plan's problem and currently invisible.

## 2. Measurement: the real tier mix

Corpus: 4 main sessions. Main ran Opus 5 (9,921 requests), Opus 5.5 (3,278)
or Sonnet 5 (5). **No orchestrator here ran on Fable**, so the owner's
"Fable main gives Fable subagents" case appears in this repo as "Opus main
gives Opus subagents". The mechanism, step 4 of the resolution order, is the
same. Of 389 subagents, 388 were spawned by an Opus-family agent.

### 2.1 How each subagent's model was chosen

| Source                 | Agents | Ran on                                 | ite (M) | Share of subagent ite |
| ---------------------- | ------ | -------------------------------------- | ------- | --------------------- |
| explicit `model`       | 133    | sonnet 46, opus 62, haiku 15, fable 10 | 563     | 33.9 %                |
| definition frontmatter | 114    | sonnet 75, haiku 25, opus 14           | 764     | 46.0 %                |
| inherited (implicit)   | 121    | opus 114, haiku 4, sonnet 3            | 312     | 18.8 %                |
| fork (always inherits) | 21     | opus 21                                | 22      | 1.3 %                 |

- The explicit parameter was always honoured: param = used family in 133 of
  133\.
- 36.5 % of agents (142) never had a model chosen for them. 135 of those 142
  ran on Opus.
- The 3 haiku and sonnet "inherited" agents are types whose built-in
  definitions set a model (`claude-code-guide` runs on Haiku), which is why
  the classifier needs the built-in table.

### 2.2 Tier mix by price

$eq over both sessions, 1,661 M ite in total:

| Model               | Agents | $eq    | Share |
| ------------------- | ------ | ------ | ----- |
| Opus 5.5            | 152    | $2,700 | 55 %  |
| Sonnet 5            | 124    | $1,843 | 37 %  |
| Opus 5              | 56     | $247   | 5 %   |
| Fable 5.1           | 10     | $40    | 0.8 % |
| Opus 4.8 (fallback) | 3      | $27    | 0.6 % |
| Haiku 4.5           | 44     | $5     | 0.1 % |

Haiku took 44 agents (11 %) but 0.1 % of spend: all of it was scouts,
renames and probes.

### 2.3 By role

The role comes from a regex over `agent_type` and `description`, checked in
the order security, adversarial, decide/rule, fix, implement, review,
verify/qa, scout, docs. It is noisy; §3 quantifies the noise.

| Role         | Opus (n / ite M) | Sonnet   | Haiku    | Fable   |
| ------------ | ---------------- | -------- | -------- | ------- |
| fix          | 33 / 257         | 69 / 658 | —        | —       |
| implement    | 41 / 298         | 22 / 164 | 1 / 0    | —       |
| review       | 60 / 85          | 3 / 7    | —        | —       |
| security     | 34 / 37          | —        | —        | 1 / 0.4 |
| adversarial  | 9 / 11           | —        | —        | 1 / 0.3 |
| decide/rule  | 6 / 5            | —        | —        | 8 / 3.4 |
| verify/qa    | 8 / 18           | 6 / 11   | 2 / 0.4  | —       |
| scout/search | 11 / 8           | 5 / 1.6  | 37 / 4.5 | —       |
| other        | 7 / 7            | 17 / 69  | 4 / 1    | —       |

**Findings:**

1. **Fix and implement work on Opus is the whole opportunity.** 74 agents,
   555 M ite, **$2,238 = 46 % of subagent $eq**. At Sonnet prices the same
   tokens cost $1,111, a **$1,127 (23 %) upper-bound saving**. It is an
   upper bound because Sonnet fix and implement agents averaged 278 requests
   against 218 on Opus. That difference is confounded by task size, so
   discount by about a quarter: roughly **17 % realistic**.

2. **The largest single pattern is an explicit up-override of a cheaper
   definition.**

   - `python-developer`'s frontmatter is `sonnet`. It was dispatched with
     `model: opus` 22 times: 326 M ite, about $1,300 $eq, **about 27 % of
     subagent $eq**.
   - All 22 were deliberate. Most were fixer continuations on the hardest
     fail-closed/security defect lines (N23, N24, N53, Plans 463 and 464),
     dispatched in one burst after Sonnet rounds.
   - The same lines went back to Sonnet afterwards.
   - Neither tier visibly shortened the review loop: N23 reached review 5
     either way. That is anecdotal, not a measurement.

3. **The silent default is the second pattern.** 114 inherited agents ran
   on Opus (310 M ite, 18.7 %). Their names show what they were:

   - 16 `sec-*` security-sweep checks;
   - about 60 `review-*`;
   - about 20 `d-*`, `n422-*` and `integrate-*` implementers;
   - Explore ×8.

   The reviews and security checks are arguably right on Opus. The
   implementers are the addressable part: about 20 agents and about 120 M ite.

4. **Explicit Fable escalations already happen, and they are cheap.** All 10
   Fable agents were explicit, spawned by an Opus 5 main:

   - 8 rulings ("Decide…" and "Rule on… gate");
   - 1 adversarial review;
   - 1 secret-guard ruling.

   They made 11-20 requests each, $40 in total. This is exactly the
   escalation shape the plan wants to keep. It shows escalation is cheap
   when the task is a bounded judgement.

5. Reviews stayed on Opus (60 against 3). No reviewer was dispatched to
   Sonnet except `review-n56-3` (explicit) and two `defence-before-fix`
   searchers.

**Not verified:** there were 104 `fork` dispatches but only 21 fork
transcripts. Most were probably denied by a hook or failed before starting,
but that was not traced. It does not affect the tier figures, which count
agents that ran.

## 3. Safety signals

"FP" here means **the signal says "a lower tier is safe" when the task
needed the top tier**. That can only be estimated. Where a figure is
measured it says so; otherwise it is a judgement.

### 3.1 Signals that a lower tier is safe

| Signal                                                                                                    | Evidence                                                                                                                                   | FP risk                                                                                                                                                         |
| --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **An explicit model above the definition's own frontmatter** (for example `python-developer` + `opus`)    | 22 + 13 of the `claude-opus-5-5 \| param=opus \| fm=sonnet` rows. Deterministic.                                                           | **Low as a trigger, high as a verdict.** Every instance here was a deliberate choice. The advisory should ask for a reason, not assert one.                     |
| **An inherited top tier on a type with no frontmatter model** (general-purpose, named teammates, Explore) | 135 inherited or forked agents on Opus                                                                                                     | **Low as a trigger.** Nobody chose the tier, so asking the orchestrator to choose costs a line. Whether the cheaper tier is right depends on the role (below).  |
| `subagent_type` in a cheap list (`qa-runner`, dedupe scout, `claude-code-guide`, Explore for search)      | 37 scout agents on Haiku cost $4.5 in total. Explore ×8 inherited Opus.                                                                    | **Low.** Search and mechanical QA are the documented cheap-tier use (SA:33). Explore on Opus is pure waste unless it is a design search.                        |
| The description says fix, implement, rename, sweep or batch                                               | 91 on Sonnet against 74 on Opus. Mechanical batches (renames, "denominators batch A/B/C", literal sweeps) all ran fine on Sonnet or Haiku. | **Medium.** The escalated Opus fixers were *fix* tasks on fail-closed security code. A fix label is not easy work. Pair it with the absence of a security term. |
| "Targeted tests" or a narrow verify ("N47 narrow verify", "finish mypy fixes")                            | Several ran on Sonnet with 19-80 requests                                                                                                  | **Low to medium.** A bounded scope is a good signal, but a "verify" that is really a review of reasoning needs judgement.                                       |
| **A brief file referenced in the prompt**                                                                 | Measured: 125 Opus and 95 Sonnet agents had one; 83 Opus and 29 Sonnet did not.                                                            | **High. Not a tier signal.** Briefs mark a disciplined orchestrator, not an easy task. Drop it.                                                                 |
| **A read-only tool set**                                                                                  | `code-reviewer` and `security-reviewer` are read-only **and** Opus by definition                                                           | **High. Not a tier signal.** Read-only marks *search or review*, and reviews are the top-tier work. Useful only in combination with a scout-type name.          |

### 3.2 Signals that the top tier is really needed

| Signal                                                                                   | Evidence                                                                                                                     | FP risk (flags top tier when not needed)                                                                                                                                 |
| ---------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Security terms (`secur`, `sec-`, secret, safeguard, fail-closed), or `security-reviewer` | 35 agents                                                                                                                    | Low. The owner's standing rules treat security callers as special.                                                                                                       |
| Adversarial, "rule on", "decide", design, brainstorm, triage                             | 25 agents, including all 8 Fable rulings                                                                                     | Low.                                                                                                                                                                     |
| "review" in the name or description                                                      | **Measured: 146 agents carry "review", of which 41 are fix/resume tasks** (24 are `python-developer` fixing review findings) | **28 % FP** on the bare keyword. The type (`python-developer`) or verb order must win over the keyword. Code: check fix/resume before review, or key on `subagent_type`. |
| Ambiguous scope: no plan, ledger or file path in the prompt, and a prompt under N chars  | Not measured                                                                                                                 | Unknown. Only a weak heuristic.                                                                                                                                          |
| A repeat dispatch on the same key after ≥ 3 rounds (471-B L9)                            | The N23/N24/N53 lines went to Opus in round 4 or 5                                                                           | Medium. Repetition can mean the task is hard, or that the reviewer is too strict. This is the "escalation" trigger, never a demotion trigger.                            |

**Net:** no signal is safe enough to *deny* on. Two are safe enough to
*advise* on: an up-override of a definition, and an implicit top tier on a
type with no model. The role heuristics decide **which** cheaper tier to
name, and whether to stay silent.

## 4. Levers, least to most intrusive

Handler shapes use this repo's conventions: `core/handler_scope.py` for
MAIN/SUB, `mtime_cache` for sidecar reads, and `resolve_model_family`
(`handlers/status_line/downgrade_state.py:66`) for the family and rank table
(haiku 0, sonnet 1, opus 2, fable 3). That table should move to `utils/` so
the status line and the pre_tool_use handlers share it.

### T0: zero-code owner settings (report only)

`CLAUDE_CODE_SUBAGENT_MODEL=sonnet` is the default at step 3, **below** the
parameter and the frontmatter since v2.1.251 (SA:368, 380).

- **What it would change:** every *inherited* agent moves off main's model,
  while explicit escalations and definition models are untouched.
- **What it would have covered here:** the 121 inherited agents (312 M ite),
  **but not** Explore or Plan (SA:378; that needs a project `Explore`
  definition with `model: haiku` or `sonnet`, SA:55) and not forks.
- **Not verified:**
  - whether it applies to agent-team teammates without `_FORCE` (SA:399
    mentions teammates only for the FORCE variant). 272 of the 389 agents
    were teammates, so this must be probed.
  - whether that is a good idea for the 60-odd inherited reviewers. With
    this set, reviewers must be dispatched with `model: opus` or have a
    frontmatter model. That is the "floor" problem again (T4).
- **Daemon's part:**
  - a report line in the T1 CLI;
  - a `docs/` recommendation;
  - optionally a SessionStart advisory when the variable is unset and the
    ledger shows more than X % implicit top tier.
- **Cost:** tiny. **Risk:** the owner's call on the review floor.
- **This is this plan's analogue of 471-B's L1.** It is the largest saving
  for the least code, and it removes the "Fable main makes Fable
  subagents" mechanism entirely.

### T1: dispatch ledger and session report (measure)

- **PreToolUse Agent** (MAIN+SUB, advisory-silent). It appends one JSONL row
  per dispatch to `untracked/.../subagent-tiers/<session>.jsonl`:
  - `tool_use_id`, the spawner (main or `agent_id`), the spawner's model (tail
    read);
  - `subagent_type`, `name`, `description`, `model_param`, the definition's
    model;
  - the source label (§1.2), the predicted model, and the role label.
- **PostToolUse Agent** joins `resolvedModel` and `agentId` by
  `tool_use_id`.
- **SubagentStop** adds per-request model counts from the agent transcript,
  using 471-B's offset cache in `subagent_cache_aggregator`. That catches
  fallback swaps (§1.3) and gives ite and $eq per tier.
- **CLI:** `hooks-daemon tiers [--session] [--by type|role|source]`. It
  prints §2's tables for the live session.
- **Cost:** small. The parsing is already in `p472_tiers.py`, and the join
  keys are proven: 0 unjoined of 389.
- **Risk:** very low (it never speaks).
- **Tests:** fixture transcripts and payloads covering the explicit,
  definition, inherited, fork and Explore-capped cases; alias-to-exact
  resolution; the resolvedModel join; a fallback swap counted per request.

### T2: status-line tier-mix segment

Example: `⚙ F1 O6 S9 H2 · 38% inh`. That is the live agents per family, plus
the share of this session's dispatches whose tier was inherited.

- It reads the T1 ledger through `mtime_cache`, beside the 471-B L7 spend
  meter. The two should share one segment.
- **Cost:** tiny. **Risk:** status-line clutter. Make it opt-in, or show it
  only when the inherited top-tier share is above a threshold.

### T3: dispatch-time advisory naming the cheaper tier

- **PreToolUse Agent**, MAIN+SUB. It fires when **both** of these hold:

  - (a) the predicted tier is at or above `advise_at_rank`, defaulting to
    main's rank, so it covers "top tier by default";
  - (b) the source is `inherited`, `fork`, or `explicit` above the
    definition's own model.

- It stays **silent** when:

  - the role matches a top-tier signal (§3.2);
  - the prompt carries a justification token such as `tier: <reason>`,
    recorded in the ledger;
  - the source is `explicit` and not above the definition. An explicit
    choice is the orchestrator's decision.

- **Message** (2 lines, via `additionalContext`): "This `<type>` dispatch
  runs on `<model>` because `<source>`. Routine `<role>` work fits
  `<cheaper>`: pass `model: <cheaper>`, or add `tier: <reason>` to keep
  `<model>`."

  - The advice lands in the orchestrator's context and is re-sent on every
    later request (471-B §6.4), so it must stay short.
  - Once per (session, subagent_type, source) until the next compaction.
    Dispatches are few (485 across this whole corpus), so the context cost
    is small.

- **Would have fired here** (a replay estimate, not a live measurement):

  - the 22 up-overrides;
  - about 20 inherited implementers;
  - 8 Explores;
  - the silent forks.

  That is roughly 50 of 389 dispatches. It would have stayed silent on the
  16 `sec-*` checks, about 60 reviews and the 10 Fable rulings.

- **Cost:** small. It reuses T1's classifier. **Risk:** low, because it is
  advisory. The failure mode is nagging; mitigate it with the `tier:` token
  and the once-per-key rule.

- **Tests:** the fire/silent matrix across source × role × rank; the token;
  the once-per-key rule; the unknown-main-model case (silent).

### T4: per-project tier policy in config

```yaml
handlers:
  pre_tool_use:
    subagent_tier_policy:
      options:
        mode: advise            # advise | require_explicit
        default_ceiling: sonnet # for types with no entry
        types:                  # subagent_type -> {ceiling, floor}
          python-developer: {ceiling: sonnet}
          qa-runner: {ceiling: haiku}
          Explore: {ceiling: sonnet}
          code-reviewer: {floor: opus}
          security-reviewer: {floor: opus}
        role_floors: {security: opus, adversarial: opus, decide: opus}
```

- **Ceiling:** T3's advisory names the ceiling tier.
- **Floor:** the *inverse* advisory, when a dispatch resolves **below** a
  floor. This matters for Plan 00470 Task 4.3. A Sonnet orchestrator makes
  every inherited reviewer a Sonnet reviewer, and that is the quality risk
  this plan must not create.
- **`require_explicit`** is the only enforcing mode worth offering. It
  **denies a dispatch whose model would be implicitly inherited above the
  ceiling**, and says "pass `model:` explicitly".
  - Any explicit value passes, **including the top tier**, so a needed
    escalation is never blocked. That satisfies the Non-Goal.
  - It turns the silent default into a conscious choice, one line per
    dispatch.
  - It never judges the task. It only refuses to let nobody decide.
- **Cost:** medium, because of config schema, docs and the per-type table.
- **Risk:** low in advise mode. In `require_explicit` mode it costs one
  denied turn when the orchestrator forgets. That is cheap next to a 300-
  request Opus agent.

### T5: stop-time summary

- **Stop handler**, main only, at most once per N dispatches: "Since the
  last summary: 12 dispatches: 7 Sonnet, 4 Opus (3 inherited), 1 Fable
  (explicit). About $X at top tier went to routine roles."
- **Cost:** small. **Risk:** it adds to the Stop path, which already
  carries many handlers, and it repeats T2.
- **Prefer T1's CLI plus T2.** Make T5 a line in the existing
  `session_actions_directive` or failsafe tick only when the implicit
  top-tier share crosses a threshold.

### T6: escalation prompting (nudge up)

- **PreToolUse Agent.** It fires when the predicted tier is **below the top
  available tier** and the role matches a strict top-tier set (decide/rule,
  adversarial, design ruling). It also fires on the third or later review or
  fix round on the same plan or ledger key (shared counter with 471-B L9).
- The message: "This looks like a bounded judgement. A top-tier (`fable`)
  pass costs about $4 for a 15-request ruling. Consider `model: fable` for
  it, not for the fixer."
- **Evidence:** the 10 Fable rulings cost $40 in total. The deadlocked review
  lines instead cost hundreds of $eq in repeated Opus rounds.
- **Cost:** small. **Risk:**
  - It raises spend when it misfires.
  - Fable is not always available: `availableModels`, or the safety
    fallback substitutes it (§1.3).
- Make it **opt-in** and keep it to rulings, never implementers.

### T7: ship cheaper agent definitions (template level)

- A daemon-shipped project `Explore` with `model: haiku` or `sonnet`
  (SA:55). This overrides Claude Code's Opus-capped inherit for every client.
- `general-purpose` cannot be given a model by the daemon without shadowing
  a built-in, which is too surprising. Leave it to T0, T3 and T4.
- **Cost:** tiny. **Risk:** it changes client behaviour silently. It is the
  owner's call, and it needs a docs line and an opt-out.

### Rejected

| Lever                                         | Why rejected                                                        |
| --------------------------------------------- | ------------------------------------------------------------------- |
| Deny on role heuristics                       | FP up to 28 % on the "review" keyword alone. Violates the Non-Goal. |
| Rewrite `tool_input.model` via `updatedInput` | The daemon would choose the model, which is Non-Goal 1.             |
| Setting FORCE                                 | Kills escalation. Owner-only in any case.                           |
| Deciding at SubagentStart                     | It cannot block and does not carry the model.                       |

## 5. Interaction with Plans 00471 and 00470

- **00471 (context budget)** bounds *how many tokens*; this plan sets *the
  price per token*. The two savings multiply.
  - The same agents dominate both: the top-30 giants of 471-B were
    implementers and fixers, and those are exactly §2.3's addressable Opus
    fix and implement set.
  - The ledgers should be one artefact: 471-B L6's per-agent sidecar gains
    `model_param`, `source`, `resolved`, `per_model_requests`. T1 is then
    mostly a join, not a new store.
  - The status segment should be one: L7 and T2.
  - The review-round counter should be one: L9 and T6.
  - L2's handoff successor should **inherit the tier decision
    explicitly**. The successor brief should carry `model:`. The per-
    invocation value persists on resume (v2.1.211) but not across a fresh
    spawn, so a handoff silently reverts to inherit. T3 would catch that.
  - L3 (resume guard) is tier-neutral.
- **00470 (orchestrator model).** Task 4.3 A/Bs a Sonnet main loop.
  - Under the current resolution order, **a cheaper main moves every
    inherited subagent down with it**. That includes about 60 reviewers and
    16 security checks here.
  - So 00470 Task 4.3 is unsafe without either T4 floors or T0 plus explicit
    reviewer models. Conversely, T0 plus T4 make the orchestrator's model
    and the workers' tiers **independent**, which is what 00470's A/B needs
    in order to measure the orchestrator alone.
  - Recommendation for 00470: pin reviewer and security definitions to
    `model: opus` (already true for `code-reviewer` and `security-reviewer`;
    add a floor for ad-hoc named reviewers) before running Task 4.3.
  - SessionStart's `model` field and the sidecar `model_id` feed both plans.

## 6. Recommendation

### Phased task list for PLAN.md

**Phase 1: Probes (orchestrator, main thread)**

- 1.3: Probe whether `CLAUDE_CODE_SUBAGENT_MODEL` applies to (a) agent-team
  teammates without `_FORCE`, and (b) named agents dispatched with
  `subagent_type: general-purpose`. Record `resolvedModel` for each.
- 1.4: Probe whether a hook subprocess sees `CLAUDE_CODE_SUBAGENT_MODEL`,
  which decides whether the classifier can report the `env` source.
- 1.5: Capture one real PostToolUse `Agent` payload of each shape
  (`completed`, `async_launched`, teammate), and one subagent PreToolUse
  payload. This is shared with 471-B's open question 5.

**Phase 2: Measure (python-developer on Sonnet, TDD)**

- 2.1: Move `resolve_model_family` and the rank table to `utils/`, and add
  alias and full-id normalisation plus the Explore cap rule.
- 2.2: Add a dispatch-source classifier (§1.2) as a pure function, with a
  fixture matrix.
- 2.3: The T1 ledger. PreToolUse row, PostToolUse `resolvedModel` join, and
  SubagentStop per-request models (built on 471's offset-cache aggregator
  work if it lands first).
- 2.4: `hooks-daemon tiers` CLI (§2 tables), with golden-output tests from
  fixture transcripts.
- 2.5: A subagent fallback-swap surfacing: reuse `model_fallback_records`
  parsing on agent transcripts at SubagentStop.

**Phase 3: Advise**

- 3.1: The T3 advisory: the fire/silent matrix, the `tier:` token and the
  once-per-key rule.
- 3.2: The T4 config schema: ceilings, floors and role floors, in advise mode
  only.
- 3.3: The T2 status segment, merged with 471's L7.
- 3.4: The docs page covering the T0 recommendation, and the T7 opt-in
  project `Explore` template, if the owner accepts it.

**Phase 4: Optional, owner-gated**

- 4.1: T4 `require_explicit` mode in this repo.
- 4.2: T6 escalation nudge for rulings and round ≥ 3.
- 4.3: After a representative run, re-measure with `hooks-daemon tiers` and
  compare against §2 (the baseline is `untracked/scratch/p472_tiers.json`;
  copy it into the plan folder if it is to be kept).

### Decisions for the owner (Task 1.2)

1. **T0:** set `CLAUDE_CODE_SUBAGENT_MODEL=sonnet` in this repo's settings?
   It is the largest, simplest lever. The trade-off is that reviewers then
   need an explicit `opus` (a floor). The probe (1.3) must confirm that it
   reaches teammates.
2. **The ceiling table:** is `python-developer` on Sonnet the policy, with an
   Opus up-override needing a `tier:` reason? That pattern was 27 % of
   subagent $eq here.
3. **Floors:** Opus for review, security, adversarial and rulings in this
   repo? Should this ship as the client default, or be off for clients?
4. **Enforcement:** advise only, or `require_explicit` (deny implicit
   top-tier inheritance, allow any explicit model) in this repo?
5. **T6:** should the daemon ever suggest spending *up* (Fable for rulings)?
6. **T7:** ship a project `Explore` with a cheaper model to clients (opt-in
   or opt-out)?
7. **A shared ledger with 00471:** build one per-agent store for spend and
   tier, sequenced after 00471's L6?
