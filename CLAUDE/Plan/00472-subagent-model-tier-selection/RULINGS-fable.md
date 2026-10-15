# Plan 00472: Fable rulings on Task 1.2 and Phase 2

**Standing**: Fable ruling under the owner's delegation ("use fable to answer
questions"). These are engineering choices only. They are recorded as Fable
rulings, never as the owner's. Anything marked **left to owner** is unruled.

**Evidence base**: `subagent-reports/260925-p472-brainstorm-opus-5-5.md`
("472-B", section 6 decisions), `subagent-reports/260925-p472-workflow-fanout-sonnet-5.md`
("472-W"), the sibling rulings in
[../00471-subagent-token-budget-protection/RULINGS-fable.md](../00471-subagent-token-budget-protection/RULINGS-fable.md)
("471-R"), and the tree as checked while ruling:

- `resolve_model_family` and the rank table live in
  `handlers/status_line/downgrade_state.py` (haiku 0, sonnet 1, opus 2,
  fable 3) and `utils/subagent_tool_resolution.py` already resolves agent
  definitions, so the classifier's two inputs exist.
- `pre_tool_use/agent_dispatch_recorder.py` with
  `utils/agent_dispatch_registry.py` (Plan 00518) already writes one row per
  named dispatch at PreToolUse `Agent`. The T1 ledger row extends that record
  rather than opening a new store.
- No `Workflow` handler, fixture or captured payload exists anywhere in the
  repo (472-W section 0 verified again: `untracked/payload-capture/` is
  empty). The daemon has never seen the tool's `tool_input`.
- Plan 00280 (Not Started, owner's) is the standing-authorisation text for a
  workflow model cap. It is prose replayed on every prompt, not a hook. Its
  own Non-Goals anticipate "an optional advisory PreToolUse surface" as a
  later phase; the handler ruled here is that surface. The plans stay
  separate and cross-linked.
- 472-B's analysis script is gone; `untracked/scratch/p472_tiers.json`
  survives and is the measured baseline.

## 1. Rulings on the seven owner decisions (472-B section 6)

### D1. Set `CLAUDE_CODE_SUBAGENT_MODEL=sonnet` in this repo's settings?

**Ruling: not now. Ship the recommendation and the measurement; the flip is
left to owner.**

It is the largest, simplest lever, but three facts in 472-B say it is not a
safe engineering default today: whether it reaches agent-team teammates
without `_FORCE` is unverified, and 272 of 389 agents were teammates; it
moves every inherited reviewer and security check (about 76 agents) down to
Sonnet unless floors are enforced, and floors here are advisory; and it
changes what runs in the owner's own sessions, which is the owner's call. So
the daemon reports it instead: the `tiers` CLI prints whether the project
`settings.json` `env` block sets the key (a file read, which sidesteps the
hook-environment gap in 472-B section 1.2) beside the inherited-top-tier
share, and the docs page recommends the value with the reviewer-floor
caveat. The teammate probe (472-B Task 1.3) and the flip go to the follow-up
in section 3.

### D2. The ceiling table: `python-developer` on Sonnet, Opus up-override needs a `tier:` reason?

**Ruling: yes, as advisory policy in this repo's config.**

The up-override of `python-developer`'s own `sonnet` frontmatter was the
single largest pattern, 27 % of subagent $eq, and all 22 instances were
deliberate. A deliberate choice should cost one line of reason, not be
blocked: the advisory asks, the `tier: <reason>` token answers, and the
ledger records both. This repo's table: `python-developer: sonnet`,
`qa-fixer: sonnet`, `qa-runner: haiku`,
`hooks-daemon-plan-dedupe-scout: haiku`, `Explore: sonnet`,
`default_ceiling: sonnet` for a type with no frontmatter model. The client
default ships an empty table: the advisory still fires on the two
source-based triggers (inherited top tier, explicit above the definition),
which need no table, and a client's roles are not this repo's to guess.

### D3. Floors: Opus for review, security, adversarial and rulings; client default or off?

**Ruling: floors on in this repo, advisory; off for clients.**

The floor is the inverse advisory and exists for one reason 472-B section 5
makes concrete: Plan 00470 Task 4.3's Sonnet main loop would silently make
every inherited reviewer a Sonnet reviewer. This repo: `code-reviewer`,
`security-reviewer`, `hooks-daemon-docs-qa` floor `opus` (matching their
frontmatter, so the floor only fires on an explicit down-override or a
missing definition) and `role_floors: {security: opus, adversarial: opus, decide: opus}`.
Clients: empty, because a floor names a model family as policy and that is
a per-project decision the docs page explains with this repo's table as the
example. 00470 is Blocked; its Task 4.3 should not run before this lands,
and that note belongs in 00470, not here.

### D4. Enforcement: advise only, or `require_explicit` in this repo?

**Ruling: advise only. `require_explicit` is not built now.**

The plan's Non-Goal is "blocking a delegation on tier alone", and while
`require_explicit` technically honours it (any explicit value passes), it
costs a denied turn every time the orchestrator forgets, in sessions the
owner is not watching. The advisory's own hit rate is unknown until the
ledger runs: 472-B's replay estimate is about 50 of 389 dispatches. Build
the measurement, watch it, then decide enforcement from evidence in the
follow-up (section 3). The config schema reserves `mode: advise` so the
later addition is one value, not a schema change.

### D5. T6: should the daemon ever suggest spending up (Fable for rulings)?

**Ruling: no. Dropped.**

The evidence cuts against it: all 10 Fable escalations in the corpus were
already explicit and cost $40 in total, so the orchestrator escalates
correctly unprompted; a misfire raises spend; and Fable may be unavailable
or substituted by the safety fallback (472-B section 1.3). An opt-in nudge
that is right when nobody needed it and costly when wrong is not worth its
handler. The review-round counter it would have shared goes to 00471 Task
2.6 alone.

### D6. T7: ship a project `Explore` definition with a cheaper model to clients?

**Ruling: left to owner for clients; not added in this repo now.**

Shipping an agent definition changes every client's Explore behaviour
silently, which 472-B itself flags as the owner's call. In this repo the
addressable waste was 8 Explore dispatches, and the T3 advisory names
Explore's inherited top tier each time, so the lever is covered without
shadowing a built-in whose tool set a project override might change. The
docs page describes the `model: sonnet` project override as an option.

### D7. One shared ledger with 00471, sequenced after its L6?

**Ruling: yes. One per-agent store, built in 00471 Task 2.1; this plan adds
rows to it.**

The same agents dominate both plans' spend, the join keys are proven (0
unjoined of 389), and two stores would disagree on resume generations. So:
00471 Task 2.0 and 2.1 land first; this plan's T1 is a PreToolUse row (the
classifier output) extending the `agent-dispatch-registry` record, a
PostToolUse `resolvedModel`/`modelsUsed` join by `tool_use_id`, and the
per-request model counts the shared aggregator already records. The status
segment is 00471's, with per-family live counts added here.

## 2. Rulings on the Workflow fan-out levers (472-W section 4)

**(a) Advisory naming fan-out and tier: build, as the one Workflow handler.**
It asserts only what the script and the session model already say. It
parses `tool_input.script` when it is a string, resolves `tool_input.args`
when it is a JSON array, reads `scriptPath` when it is an absolute path that
exists, counts literal arrays, literal-bound loops and `Array.from({length: N})`,
and classes everything else as unknown. The message states "at least N"
when any site is unknown, and names M sites with no `model`, the session
model they inherit, and whether N is over the ceiling (c).

**(b) Require explicit `model` on fanned-out `agent()` calls: dropped.** It
is the highest-friction, highest-false-positive lever, denying on a role
classification of a whole script that 472-B already rejected for a single
dispatch. The advisory in (a) already says which sites lack a `model`.

**(c) Per-tier fan-out ceiling: built into (a), advisory only, counting
lifetime total.** Lifetime total, because the owner's concern is $eq per
request, which scales with total agents, not concurrent slots (472-W's own
reasoning). Unknown fan-out counts as at the ceiling. This repo's ceilings:
`fable: 10, opus: 25, sonnet: 60, haiku: 60`. Clients: the same table,
advisory, since it only ever adds a sentence. Deny mode is not built until
a real payload has confirmed the script shape (section 3).

**(d) Runtime live counter: dropped as a separate lever.** It cannot block,
cannot reach the orchestrator, and 00471 Task 2.4's live count is the same
measurement surfaced where the orchestrator reads it.

**Session model source**: 00471 Task 2.0's tail reader on the spawner's
transcript first, then `context_sidecar` `model_id`, else unknown, and
unknown means silent.

## 3. What cannot be done now, and where it goes

| Item                                                  | Why not now                                                                                  | Ruling                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| ----------------------------------------------------- | -------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Task 2.2: one real PreToolUse(`Workflow`) payload     | Only an owner-opted-in workflow run produces one                                             | **(a) build defensively, and make the handler its own probe.** On the first `Workflow` call it sees per session it writes the `tool_input` key names and value types (never the script text) to `untracked/payload-capture/workflow-shape.json` and records a verdict. Any shape it cannot parse is allowed with an `unparsed` verdict. Task 2.2 is reworded to that and closes with the handler; confirming against a real payload goes to the follow-up plan. |
| D1 flip and the teammate probe (472-B Tasks 1.3, 1.4) | Changes which model runs in the owner's sessions; probe needs a session run with the env set | **Left to owner** for the flip; **(b) follow-up plan** carries the probe beside it.                                                                                                                                                                                                                                                                                                                                                                             |
| `require_explicit` mode                               | Enforcement decided from the advisory's measured hit rate                                    | **(b) follow-up plan**, opened when the ledger shows the advisory firing on more than a configured share of dispatches.                                                                                                                                                                                                                                                                                                                                         |
| Workflow ceiling deny mode                            | Needs the confirmed payload shape first                                                      | **(b) same follow-up plan** as Task 2.2's confirmation.                                                                                                                                                                                                                                                                                                                                                                                                         |
| T7 client `Explore` definition                        | Silent client behaviour change                                                               | **Left to owner.** Documented as an option.                                                                                                                                                                                                                                                                                                                                                                                                                     |
| Re-measurement after a representative run (472-B 4.3) | Needs a run after the levers ship                                                            | **(c) dropped as a closing criterion.** `untracked/scratch/p472_tiers.json` is copied into `subagent-reports/` now as the baseline; `hooks-daemon tiers` against it is a one-off comparison later.                                                                                                                                                                                                                                                              |
| Plan 00280's authorisation text                       | Owner's plan, Not Started                                                                    | Not touched. 00280's PLAN.md gains one cross-reference line saying its optional PreToolUse phase is delivered by this plan's `workflow_fanout_advisor`, so the two are not built twice.                                                                                                                                                                                                                                                                         |

## 4. Build scope (implementable now, TDD, no further owner input)

Sequenced after 00471 Tasks 2.0 and 2.1.

- **Task 3.1**: move `resolve_model_family` and the rank table to `utils/`
  with alias and full-id normalisation and the Explore cap rule; the status
  line imports from there. Tests: alias, full id, unknown, Explore under an
  Opus and a Fable main.
- **Task 3.2**: dispatch-source classifier as a pure function (472-B
  section 1.2 table): `fork`, `explicit`, `definition`, `env` (from the
  project `settings.json` `env` block), `inherited-capped`, `inherited`, plus
  the role label with fix/resume checked before `review` (the 28 % keyword
  false positive). Tests: the fixture matrix.
- **Task 3.3**: T1 ledger rows in the shared store: PreToolUse row,
  PostToolUse `resolvedModel`/`modelsUsed` join, per-request model counts and
  a `downgraded` flag at SubagentStop (reusing `model_fallback_records`
  parsing). Tests: explicit, definition, inherited, fork, Explore-capped; the
  join; a fallback swap counted per request.
- **Task 3.4**: `hooks-daemon tiers [--session] [--by type|role|source]`
  printing 472-B section 2's tables, the `CLAUDE_CODE_SUBAGENT_MODEL` line
  (D1), and the downgraded-agent list. Tests: golden output from fixtures.
- **Task 3.5**: T3 advisory handler `subagent_tier_advisor` on PreToolUse
  `Agent`, MAIN and SUB, with the T4 config (`mode: advise`,
  `default_ceiling`, `types`, `role_floors`): fires on inherited top tier,
  fork, or explicit above the definition; silent on top-tier roles, the
  `tier:` token, explicit-not-above, and unknown main model; once per
  `(session, subagent_type, source)`; the floor advisory on a resolve below
  a floor. Two-line message. Tests: the fire/silent matrix across source,
  role and rank; the token; once-per-key; unknown main.
- **Task 3.6**: `workflow_fanout_advisor` on PreToolUse `Workflow` per
  section 2, with fixtures authored from the `workflow-authoring` skill's
  worked examples (literal array, `Array.from`, literal loop, `args`-driven,
  script-computed list, budget loop) and the self-probe sidecar. Tests: each
  fixture's count and bucket; `args` resolution; unknown as at-ceiling;
  unparsed allows with one verdict; shape sidecar written once.
- **Task 3.7**: per-family live counts in 00471's status segment.
- **Task 3.8**: docs page (`docs/guides/`) covering the D1 recommendation
  and caveat, the ceiling and floor tables with this repo as the example,
  the `tier:` token, the project `Explore` option, and the Workflow
  advisory; `HANDLER_REFERENCE.md` entries; the config-changes manifest;
  the holding-area entry; the one-line cross-reference in 00280; the
  baseline JSON copied into `subagent-reports/`; a dogfood run in this
  repo whose `hooks-daemon tiers` output and `verdicts.jsonl` show at
  least one tier advisory. The plan's GitHub issue (named in the PLAN.md
  header) gets the implementation summary and is closed on completion, per
  the plan directory's conventions.

## 5. Success criteria after this ruling (each verifiable)

01. Every `Agent` dispatch in a session has a ledger row with
    `subagent_type`, `name`, `model_param`, the definition's model, the
    source label, the predicted model, the role label, and after PostToolUse
    the `resolvedModel`; a fixture session proves 0 unjoined rows.
02. The classifier returns the 472-B section 1.2 label for every row of the
    fixture matrix, and labels a `python-developer` "fix review findings"
    dispatch as fix, not review.
03. `hooks-daemon tiers` prints the by-source, by-model and by-role tables,
    the `CLAUDE_CODE_SUBAGENT_MODEL` line, and the downgraded-agent list from
    fixtures; a subagent transcript with a mid-run swap is listed with its
    per-model request counts.
04. The tier advisory fires on an inherited top tier, a fork from the top
    tier, and an explicit model above the definition; it is silent on a
    security, adversarial or ruling role, on a `tier:` token, on an explicit
    model not above the definition, and when the main model is unknown; it
    fires once per key; the floor advisory fires on an explicit `sonnet` for
    `code-reviewer` under this repo's config. The acceptance test shows one
    advisory through a real dispatch in this repo, and shows none on a
    dispatch carrying `tier:`.
05. No handler in this plan ever returns a deny; a test asserts the
    advisory handlers' decisions are allow for the whole matrix.
06. The Workflow advisor reports N and M for each fixture script, resolves an
    `args`-driven fan-out exactly, reports a script-computed list as unknown
    and at the ceiling, states "at least N" when any site is unknown, allows
    an unparsable `tool_input` with one `unparsed` verdict, and writes the
    shape sidecar once per session.
07. The status segment shows per-family live counts from fixture sidecars.
08. `docs/guides/HANDLER_REFERENCE.md`, the docs page and the config-changes
    manifest describe every new handler, option and the CLI; the
    pending-release holding area records this plan's release-bound
    consequences (new handlers, new config keys, the new CLI command, the
    D1 recommendation); Plan 00280's PLAN.md carries the cross-reference.
09. `untracked/scratch/p472_tiers.json` is copied into `subagent-reports/`
    as the baseline; the dogfood journal entry cites a `hooks-daemon tiers`
    run and a tier-advisory verdict from a real session.
10. The plan's GitHub issue is commented with the implementation summary
    and closed.
11. Targeted QA is green on the work branch; the coordinator's full gate is
    green before merge.

When all eleven hold, the plan closes with the D1 flip, the teammate probe,
`require_explicit`, the Workflow deny mode and the real-payload confirmation
recorded as the follow-up plan in section 3, T7 left to the owner, and
nothing else waiting on the owner.
