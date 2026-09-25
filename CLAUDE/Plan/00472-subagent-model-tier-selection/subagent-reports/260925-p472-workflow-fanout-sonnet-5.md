# Plan 00472 Task 2.1: Workflow fan-out research

Author: p472-workflow-fanout (Sonnet 5). Research only: no source changed.
Builds on the Plan 00472 brainstorm
(`../subagent-reports/260925-p472-brainstorm-opus-5-5.md`, "472-B" below),
PLAN.md Overview/Phase 2, and Plan 00280 (`workflow-orchestration` standing
authorisation, advisory-text-only, not a hook).

Docs cited: `HK` = vendored `remote-docs/code.claude.com/docs/en/hooks.md`
(licence unreviewed); `TR` = `tools-reference.md`; the `workflow-authoring`
skill (packaged instructions, not a vendored remote doc — no provenance
frontmatter, so treat its claims as slightly less authoritative than `HK`).
No vendored `workflows.md` exists in `remote-docs/` — `TR:75` links
`/docs/en/workflows` but the tree only carries `hooks.md`,
`sub-agents.md`, `tools-reference.md` and five others; **this is itself a
finding**, not an oversight to route around (§0).

## 0. What's missing before any lever can ship

Searched this repo end to end for the three evidence classes the brief asked
for and found **none** of them:

- **No `##### Workflow` section in `HK`.** The `tool_input` field tables are
  itemised per tool (`HK:1668` Bash … `HK:1764` Agent … `HK:1797`
  AskUserQuestion … `HK:1806` ExitPlanMode); `Workflow` has no entry. `TR:75`
  is the only vendored line that describes the tool at all, and it's one
  row of a table, not a schema.
- **No captured payload.** `grep -c '"type":"tool_use","name":"Workflow"'`
  over all three of this session's main transcripts
  (`.claude/ccy/projects/-workspace/{e5e72775,9679b063,ec5d431d}*.jsonl`)
  returns 0 in each. The `"name":"Workflow"` hits that do exist are the tool
  **definition** (the system-prompt description block quoted in §1), not a
  call. No `Workflow` PreToolUse fixture exists in `tests/` either —
  `tests/integration/handlers/test_pre_tool_use_workflow.py` is misleadingly
  named: it covers `NpmCommandHandler`, `GhIssueCommentsHandler` and four
  others, none of which matches on the `Workflow` tool.
- **No existing handler.** `grep -rn '"Workflow"' src/.../*.py` (excluding
  tests) returns nothing. Every `Workflow`-named file in `src/` is about
  `CLAUDE/PlanWorkflow.md` (the planning process), an unrelated meaning of
  the word: `plan_workflow.py`, `plan_workflow_asset_checker.py`,
  `PlanWorkflow.core.md`. The daemon has never intercepted this tool.

**Consequence:** every answer below is doc-plus-source-code reasoning, not a
measurement. Phase order for 00472 Phase 2 should put a payload capture
(analogous to 472-B's own Phase-1 probes) before any handler is written, the
same discipline 472-B already applied to `resolvedModel`/`env` gaps in its
§1.2. A concrete probe: run a `Workflow` call with `ultracode` on (the
description in §1 shows the daemon can't authorise this itself — see the
opt-in gate) and capture the PreToolUse and PostToolUse JSON with
`DEBUGGING_HOOKS.md`'s `debug_hooks.sh`.

## 1. What PreToolUse(`Workflow`) exposes

The one concrete fact this repo does hold is the tool's own **description**
string, captured verbatim in the three main transcripts (identical in all
three, so it's the current build's fixed text, not session-specific):

> "Execute a workflow script that orchestrates multiple subagents
> deterministically. Workflows run in the background — this tool returns
> immediately with a task ID, and a `<task-notification>` arrives when the
> workflow completes... ONLY call this tool when the user has explicitly
> opted into multi-agent orchestration..."

Two consequences for hook design:

1. **The description, not a hook, is the client-side gate today.** It's a
   system-prompt instruction to the calling model, which is not
   enforcement — exactly Plan 00280 Decision 3's point about the sibling
   `agent()` `model` parameter, generalised to the whole tool. A
   PreToolUse handler is the first point that can actually see and act on
   the call regardless of whether the calling model honoured the gate.
2. **"Runs in the background... returns immediately with a task ID."**
   PreToolUse fires at call time, before the workflow (or any of its
   agents) has started — so a PreToolUse deny genuinely stops the fan-out
   before a single agent spins up. This is the plan's premise in
   `PLAN.md:36-39` and it holds: unlike an ad-hoc `Agent` call that a
   handler can only catch one dispatch at a time, `Workflow` is one event
   gating N dispatches.

By construction (per `workflow-authoring`, un-vendored but consistent with
`TR:75`'s "a script"), the tool takes one of three input shapes:

- `script` — the full JS text inline. No disk read needed; the fan-out is
  in `tool_input.script` directly.
- `{scriptPath}` — re-invocation on a previously authored/edited script. The
  skill states "Every invocation automatically persists its script to a
  file under the session directory and returns the path **in the tool
  result**" — i.e. the file is written as a side effect of a *prior*
  successful call, so by the time a second call names that `scriptPath`,
  the file already exists on disk and a PreToolUse handler running in the
  same filesystem as the daemon (this project's daemon always is — see
  `HANDLER_DEVELOPMENT.md`) **can** read it. Not verified: whether the
  session directory path is derivable from `hook_input` alone (a
  `transcript_path`-relative guess, by analogy with 471-B's subagent
  transcript path derivation) or whether `scriptPath` in `tool_input` is
  already absolute — assume the latter until probed, since every other
  file-tool `tool_input.file_path` HK documents is absolute (HK: file-tools
  paragraph above `##### Write`).
- `{name}` — a saved/named workflow. Where the named script lives is
  **not documented anywhere in this repo** (§0) and no local directory
  under `.claude/` or `~/.claude` matches `*workflow*` (checked both). This
  is the one shape a static PreToolUse read cannot resolve without a probe
  establishing the registry location — flag it as the fail-safe case in
  §3.

`resumeFromRunId` (workflow-authoring "Resume" section) is a fourth field,
orthogonal to fan-out size: it replays a cached prefix of `agent()` calls
and executes only the first changed call onward. A resumed run can still
fan out to the same width as the original if nothing upstream of the
`parallel()`/`pipeline()` call changed — a ceiling handler must not treat
`resumeFromRunId` as automatically cheap.

## 2. Model resolution inside a workflow script, and hook visibility

**`agent()`'s model, undocumented option:** from the `workflow-authoring`
skill verbatim: *"opts.model overrides the model for this agent call.
Default to omitting it — the agent inherits the main-loop model (the
resolved session model), which is almost always correct."* This is the
same mechanism 472-B's §1.2 resolution order calls step 4 ("main's
model") for the ordinary `Agent` tool, and it is the **default the
authoring instructions themselves recommend** — the skill doesn't merely
allow implicit inherit, it tells the model to prefer it. Combined with
472-B §2's measurement that Opus mains already put 121 of 389 dispatches on
implicit inherit, a `Workflow` script authored under this skill's own
guidance is *more*, not less, likely to omit `model` on every `agent()`
call than an ad-hoc dispatch is. **The owner's 60-agent Fable observation is
the expected case, not an edge case, given the skill's own default advice.**
The script CAN override per call (`opts.model`) or per phase (`meta.phases[].model`,
"Add `model` to a phase entry when that phase uses a specific model
override") — so an explicit low-tier default is available to a script
author; nothing in the runtime forces it.

**Can the script itself override?** Yes, per-call and per-phase, as above.
No global "cap this script's model" primitive is described — each
`agent()` call is independent, so a script that sets `model: 'sonnet'` on
its first fan-out `parallel()` call and omits it on a later one gets a
mixed-tier run. A ceiling handler that inspects only the first `agent()`
call site would miss that.

**SubagentStart/SubagentStop — do they fire, and are they attributable?**
HK's own text says SubagentStart runs "when Claude spawns a subagent with
the Agent tool... and each time an in-process agent team teammate handles a
new message" (`HK:2371`) — it does not name `Workflow`-spawned agents as a
third case, but `sub-agents.md`'s "workflow" model (a script that
"orchestrates many subagents") makes it near-certain each `agent()` call
spins up a real Claude Code subagent, and every other real subagent this
repo's fixtures show (472-B §1.1's `subagents/agent-*.meta.json` corpus)
fires both events. Treat "they fire" as high-confidence, not certain
without a capture.

**Attribution is the harder half, and here the documented fields say no.**
`SubagentStart` input is exactly `agent_id` + `agent_type` (`HK:2377`,
confirmed by the JSON example at `HK:2379-2388` — no `parentAgentId`, no
"spawned by Workflow" flag, no workflow run id). `SubagentStop` adds
`agent_transcript_path` and `last_assistant_message` (`HK:2413`) — still no
spawner field. `core/handler_scope.py:12-24` (this repo) makes the same
point from the daemon's own side: `HandlerScope` classifies MAIN vs SUB
purely off **`agent_id` presence**, and the module's own docstring says
`agent_type` is "deliberately NOT consulted" because a session-wide
`--agent` flag can set it on a MAIN-thread event too — i.e. the daemon's
own scoping primitive was built to not lean on the one field that might
have hinted at workflow-vs-ad-hoc, for an unrelated correctness reason.
472-B §1.2's own conclusion about `meta.json`'s `model` field — "the
PreToolUse `tool_input` plus the definition lookup is the only clean
source of *how* the model was chosen" — generalises here: **there is no
documented field, at any event, that distinguishes a workflow-spawned
subagent from an ad-hoc one.** `agentType` in the local `meta.json`
corpus (e.g. `agent-ap472-workflow-73582a3ff2e9a29d.meta.json`, which is
this very dispatch — a named teammate, not a `Workflow`-tool run) shows
`taskKind: "in_process_teammate"` for a teammate dispatch; whether a
`Workflow`-spawned agent's `meta.json` carries an analogous
`taskKind: "workflow"` or similar is unverified — `TR:2575`'s
`background_tasks[].type` enum (`shell`, `subagent`, `monitor`,
`workflow`, `teammate`, ...) shows Claude Code **internally** tags a task
as `workflow`-typed at the `Stop`-hook `background_tasks` list level, which
is the one documented signal close to what's needed — but that's a
property of the *parent* Workflow task shown to the orchestrator's own
Stop hook, not a field on the *child* agent's SubagentStart/Stop event.

**Net for lever design:** the daemon can see the fan-out and its model
choices exactly once — at PreToolUse(`Workflow`), reading the script — and
essentially never again per-agent, because nothing downstream names the
spawner. A PreToolUse(`Agent`) handler (T3/T4 in 472-B) simply never fires
for these dispatches: there is no `Agent` tool call to intercept, each
`agent()` invocation is a JS-runtime function call inside the already-
approved `Workflow` tool call, not a new tool use Claude Code's permission
layer sees. This is the rejected-lever line in 472-B's §4 table
("Deciding at SubagentStart: it cannot block and does not carry the
model") applied one level up: **for workflows, PreToolUse(`Workflow`) is
not merely the earliest catch point, it is functionally the *only* one.**

## 3. Can a static read of the script bound the fan-out?

Only partially, and the shakiest cases are also the cheapest to reach for
in a real script.

**Bounded by construction (a static count is exact or near-exact):**

- A literal array to `parallel()`/`pipeline()`: `parallel([a, b, c].map(...))`
  or `pipeline(['x.ts', 'y.ts'], ...)` — count the array literal's elements.
- Direct `agent()` call sites at the top level or inside a fixed-iteration
  `for` — count call sites × static iteration bound, when the bound is a
  numeric literal (`for (let i = 0; i < 8; i++)`).
- `Array.from({length: N}, ...)` with `N` a literal — the "Adversarial
  verify" pattern in the skill (`Array.from({length: 3}, ...)`) is exactly
  this shape and is common enough per the skill's own worked examples to be
  worth a dedicated match.

**Not bounded by a static read — the fail-safe cases:**

- `.map`/`parallel()`/`pipeline()` over `args` — the size is whatever the
  calling model passed as the `Workflow` tool's own `args` input, which
  *is* present in the same `tool_input` the script came in on, so a
  handler that also reads `tool_input.args` (when it's a JSON array) CAN
  resolve this one exactly, without executing the script. This is the one
  "unbounded-looking" shape that is actually free to bound.
  Worth calling out because it's easy to assume `args`-driven fan-out is
  opaque when it isn't.
- `.map`/`pipeline()` over a value computed inside the script itself — e.g.
  a first-phase `agent()` call whose *returned* list becomes the next
  phase's fan-out list (`const files = await agent('list changed files', {schema: ...}); await pipeline(files, ...)`). This is unknowable without
  running the script; the skill's own "hybrid" pattern (§ opening
  paragraph: "scout inline first... then call `Workflow` to pipeline over
  it") explicitly recommends the model do the *scouting* outside the
  workflow specifically so the fan-out width becomes a static array by the
  time `Workflow` is called — meaning a disciplined caller already produces
  the bounded case above, and only an undisciplined or single-shot-authored
  script produces the unknowable one.
- `budget`-driven loops (`while (budget.total && budget.remaining() > 50_000) { ... agent(...) }`) — the skill's own worked "Loop-until-budget"
  example. Bound is `budget.total / (per-agent cost)`, and `budget.total` is
  set by the *user's* own "+500k"-style directive in the turn, which is
  not part of `tool_input` at all (it's parsed from the user prompt
  upstream of the tool call) — a PreToolUse handler cannot see it.
- `while (bugs.length < 10)` (loop-until-count) and `while (dry < 2)`
  (loop-until-dry) — bounded in the *output* dimension (10 bugs, 2 dry
  rounds), not in agent count: each iteration can itself contain a
  `parallel()` over an unknown-sized `fresh` array (the "Composing
  patterns" worked example does exactly this), so the total agent count is
  the product of two runtime-only values.
- The runtime's own backstop, documented in the skill and independent of
  anything the script author does: **concurrency capped at
  `min(16, CPUs-2)` at any moment, total agent count capped at 1000 for
  the workflow's lifetime, and a single `parallel()`/`pipeline()` call
  capped at 4096 items (hard error above that, not a truncation).** These
  are real ceilings but they're two orders of magnitude above the owner's
  60-agent complaint — 1000 is not a cost control, it's a runaway-loop
  backstop, so it cannot substitute for a per-tier ceiling far below it.

**Fail-safe reading, where static analysis can't resolve the count:** treat
an unresolvable fan-out as **unbounded**, not as zero or as some assumed
default — i.e. the same "unknown means the advisory is not given (fail
open; this is not a security gate)" principle 472-B §1.2 applies to
*classification*, but fan-out ceilings are cost controls, not classifiers,
so the fail-safe direction inverts: an unclassifiable fan-out should be
treated as *at the ceiling*, not exempt from it, wherever the lever is
advisory (never for a deny — see §4c's false-positive risk). Concretely: if
the script's `parallel()`/`pipeline()` argument is not a literal array, not
a literal-bound loop, and not `args` itself, count it as "fan-out unknown,
size ≥ N" for whatever N triggers the loudest advisory tier, rather than
silently passing it through as size-1.

## 4. Levers

All four build on the same primitive: a regex/AST-lite static read of
`tool_input.script` (or the resolved `scriptPath`/`args`, per §1 and §3) at
PreToolUse(`Workflow`), classifying each `agent()`/`parallel()`/
`pipeline()` call site by (a) whether `model` is set, and (b) the fan-out
count per §3's three buckets (exact, `args`-resolved, unknown). None of
these can see model-family *rank* the way 472-B's T3/T4 do for `Agent`,
because — per §2 — there is no resolved-model signal until after the fact;
they can only see "`model` present or absent" and infer the effective tier
is the **session's own model** when absent (the same tail-read 472-B §1.2
recommends for main's model, already needed by this handler for a
different reason: the session's tier IS the predicted tier for every
`agent()` call with no `model`).

### (a) Advisory naming the fan-out and tier

**Shape:** PreToolUse(`Workflow`), never denies. Parses the script,
computes total exact-or-resolved fan-out N (§3) and the count of
`agent()`/fan-out call sites with no `model`, tail-reads the session's own
model (471-B's 59µs technique, reusable verbatim — it's the same "read the
spawner's transcript" operation whether the spawner is a subagent or the
main thread). Fires `additionalContext` such as: \*"This workflow's script
fans out to ~N agents; M of them have no `model:` option and will inherit
`<session-model>`. At `<session-model>` prices that's roughly `$eq`
before assuming per-agent cost." No denial, ever.

**False-positive risk:** low, because it asserts nothing except what the
script and session model already say — it can't be wrong about "M call
sites have no `model`", only about the runtime fan-out size when §3's
unknown-bucket applies (state the uncertainty in the message: "at least N"
rather than "exactly N" when any call site fell in the unknown bucket).
The owner's decision: whether to gate this on a `advise_at_rank` threshold
(fire only when session model is at or above some rank, mirroring 472-B
T3's `(a)`) or always show the estimate regardless of tier — the latter
is friendlier to the plan's Goal of "surface a clear picture" even at
Sonnet, the former keeps it silent on the routine case.

### (b) Require an explicit `model` on every `agent()` inside a fan-out, when session model is the top tier

**Shape:** PreToolUse(`Workflow`), MAIN-scoped (a `Workflow` call is always
issued from the main thread's own tool-use stream, per §2's point that
nested `workflow()` calls don't re-trigger `Workflow`'s own PreToolUse —
they're an in-script function). Deny only when (i) the tail-read session
model is at the configured top rank (fable, by 472-B's rank table), AND
(ii) at least one `agent()`/fan-out call site inside a `parallel()`/
`pipeline()` (i.e. genuinely fanning, not a lone `agent()` call at top
level — a single judgement call shouldn't need this) has no `model` and
falls outside a small allowlist of role signals that are legitimately
top-tier by default (mirror 472-B §3.2's low-FP set: security/adversarial/
decide-rule keywords in the surrounding prompt string literal, matched the
same imprecise-but-cheap way 472-B's role regex already works over
`description`). Deny reason: "This `Workflow` script fans out on `<model>`
with no explicit `model:` on N agent() calls — pass `model:` on each, or
set a lower `meta.phases[].model`."

**False-positive risk:** the highest of the four levers, for the same
reason 472-B rejected role-heuristic denies outright ("FP up to 28% on the
`review` keyword alone. Violates the Non-Goal"): this is denying on the
*fan-out's* role classification, which is even noisier than a single
`Agent` dispatch's role classification, because one script can contain
several conceptually different phases (a "Design" judge panel legitimately
wants the top tier per-agent; a "Fix" pipeline over the same script doesn't).
A script author who genuinely needs Fable for all 60 (a from-scratch
migration audit, say) is blocked on every run until they add 60 near-
identical `model: 'fable'` annotations — cheap to satisfy but real
annoyance, and exactly the "needed escalation must never be blocked" Non-
Goal if the owner reads "deny" as absolute rather than "deny until you say
so explicitly", which this lever technically satisfies (any explicit value
passes, top tier included, same escape hatch as 472-B T4's
`require_explicit`) but *feels* like a block to the author mid-flow. Owner
must decide: is "explicit per call site" the right unit, or should a
single `meta.phases[].model` count as satisfying the whole phase (much
lower friction, and the skill already treats phase-level model as a first-
class option)?

### (c) A per-tier fan-out ceiling in config, deny above it

**Shape:**

```yaml
handlers:
  pre_tool_use:
    workflow_fanout_ceiling:
      options:
        mode: advise            # advise | deny
        ceilings:                # session-model rank -> max resolved fan-out
          fable: 10
          opus: 25
          sonnet: 60
          haiku: 60
        unknown_fanout: at_ceiling   # §3's fail-safe: unresolved counts as "at the ceiling"
```

Deny fires when the tail-read session model's rank has a configured
ceiling and the script's resolved-or-assumed fan-out (§3) exceeds it. The
owner's 60-Fable case is exactly `fable: 10` denying a 60-wide fan-out
outright before it starts — this is the lever that most directly answers
the complaint, because (a) and (b) are both silent-or-friction on a script
that already sets `model` correctly on all 60 calls (b passes clean; a
merely notes the cost) while a 60-wide Fable fan-out is expensive
*regardless* of whether each call site is annotated.

**False-positive risk:** medium, and it's a different shape of risk than
(a)/(b) — it's not "wrong classification of one call", it's "wrong count
of a genuinely-needed width". A large mechanical sweep across many files
(the skill's own "Migrate" example: "discover sites → transform each") can
legitimately need N > any reasonable ceiling on Sonnet, and denying it
forces splitting one workflow into several smaller `Workflow` calls purely
to duck the ceiling — busywork, not safety. Two mitigations already implied
by the skill's own vocabulary: (i) ceilings should probably be checked
against **concurrent** width (the `parallel()` slot cap the runtime
already enforces at min(16, CPUs-2)) rather than lifetime total, since a
`pipeline()` over 200 items run in bounded concurrency batches is a very
different cost profile from `parallel()` over 200 items all-at-once — but
per-request $eq is the actual owner concern (472-B §2.2), and that scales
with lifetime total, not concurrency, so this mitigation trades one
false-positive risk for another and the owner should pick which dimension
the ceiling counts; (ii) `mode: advise` as the shipped default, matching
472-B's own T4 recommendation of advise-only until the owner has watched
it fire a few times and confirmed the ceilings aren't routinely wrong.

### (d) A runtime concurrent-subagent counter as a backstop

**Shape:** not a PreToolUse handler at all — SubagentStart/SubagentStop
increment/decrement a per-session live-count (keyed off the session id
already in every hook's common input fields), independent of whether the
spawner was `Workflow` or an ad-hoc `Agent` call (§2 established the
daemon can't tell them apart at these events anyway, so this lever doesn't
need to). When the live count crosses a configured threshold,
SubagentStart's only available response is `additionalContext` injected
into the **new** subagent (HK:2390-2403) — it "can't block subagent
creation" (HK:2390, explicit), so this can only ever be advisory, and the
advisory lands inside the 61st agent's own context, not the orchestrator's.
That's a real limitation: the orchestrator that caused the fan-out never
sees this lever fire at all unless the daemon separately surfaces the
counter somewhere the orchestrator reads (e.g. 472-B's T2 status-line
segment, or a Stop-time summary per T5) — SubagentStart firing on child
#61 doesn't tell child #1's parent anything.

**False-positive risk:** low as a *count* (it's counting real live
subagents, not inferring anything), but it's the weakest lever of the four
against the owner's actual complaint: it fires **after** the spend has
already happened, since by the time N subagents are concurrently live,
their tokens are already being spent — it's a rate signal, not a
prevention. Its genuine value is as the backstop the runtime's own 1000-
agent cap (§3) is too coarse to serve as a cost control: a session-level
counter can catch a *pattern* across several smaller workflows/dispatches
in the same session that individually pass every per-call ceiling (a/b/c)
but sum to the owner's complaint anyway — e.g. five separate 15-wide
Sonnet workflows in one session, none of which trips a 60-wide `fable`
ceiling. Owner's call: is this worth building at all given it can't block
and can't reach the orchestrator's own context directly, or is (c) with a
session-level (not per-call) ceiling a strictly better version of the same
idea, reusing PreToolUse instead of two new event handlers?

## Summary for Task 1.2 / PLAN.md Phase 2

1. §0/§1: no vendored doc or capture exists for `Workflow`'s `tool_input`;
   the only concrete evidence is the tool description string and the
   `workflow-authoring` skill. **Recommend a payload-capture probe before
   any handler PR**, same discipline as 472-B's Phase 1.
2. §2: `agent()` defaults to inheriting the session model, and the
   authoring guidance itself tells the model to prefer that default — so
   the owner's 60-Fable case is the expected outcome of following the
   skill as written, not a misuse. SubagentStart/Stop cannot attribute a
   child agent to a `Workflow` run; PreToolUse(`Agent`) never fires for
   `agent()` calls at all. **PreToolUse(`Workflow`) is the only catch
   point**, not merely the earliest one.
3. §3: a static read exactly or near-exactly bounds literal arrays,
   literal-bound loops, and (perhaps surprisingly) `args`-driven fan-out,
   since `args` is sibling data in the same `tool_input`. It cannot bound
   script-computed lists, budget-driven loops, or count/dry loops with an
   inner `parallel()`. Fail-safe: treat unresolved fan-out as "at the
   ceiling", never as exempt.
4. §4: (a) is safe to ship now (asserts only what's in the script). (b) is
   the highest-friction, highest-FP lever — decide the unit (per-call vs
   per-phase). (c) most directly targets the 60-Fable complaint but needs
   an owner decision on concurrent-vs-lifetime counting and starts in
   advise mode. (d) is the weakest individually (after-the-fact, can't
   reach the orchestrator) but is the only lever that catches a pattern
   spread across several smaller dispatches in one session.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
