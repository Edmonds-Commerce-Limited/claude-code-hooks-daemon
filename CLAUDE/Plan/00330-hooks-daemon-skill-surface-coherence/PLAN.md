# Plan 00330: hooks daemon skill surface coherence

**Status**: In Progress
**Created**: 2026-09-04
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The `hooks-daemon` skill is the surface a HUMAN touches, and it has drifted
from the daemon behind it. Owner ruling: it "MUST be fully up to date and
coherent for every release".

Three asks, one theme.

**Coverage.** `optimise` scores handlers from a hardcoded list across five
areas rather than enumerating the registry: **21 of 110 configurable handlers**
are named. It therefore cannot be current by construction — every new handler
must be added by hand and nothing requires it. Plan 00323 added a contract test
that every name in the checklist RESOLVES to a live handler, so the checklist
cannot recommend a retired handler; the untested direction is the other one,
whether it names enough of them. In this repo all 89 uncovered handlers happen
to be enabled, so the blind spot is invisible here — a client on defaults is
where it bites, which is exactly why dogfooding did not surface it.

**Surface size.** The skill exposes subcommands a human never types. Some are
capabilities that should be documented rather than routed. A smaller surface
is easier to keep coherent, so this is not only tidiness.

**One command.** The human wants a single "do all the housekeeping"
invocation — config optimise, skills scan, docs QA, plan QA, the rest — rather
than remembering which subcommand does what.

A worked example of the drift shipped in `8bbd5bec`: `/hooks-daemon optimise`
was documented in three places, including as a MANDATORY upgrade step, while
missing from the routing table entirely. The entry point existed; only the
route did not. A test now pins both directions, and that test is the model
this plan generalises.

## Goals

- `optimise` derives its handler set from the registry, so a handler cannot
  ship without being considered.
- One skill invocation performs the full housekeeping pass.
- The routed subcommand surface is only what a human actually invokes.
- A release cannot proceed while the skill surface disagrees with the shipped
  handlers, config, or CLI.

## Non-Goals

- **Not** auto-enabling handlers. `optimise` recommends and applies on
  confirmation; wider coverage must not become wider automatic change.
- **Not** deleting capabilities when trimming the subcommand list. A command a
  human does not type becomes documentation, not a removal.
- **Not** re-litigating `daemon.exclude_paths` versus
  `documentation.qa.scope_exclude_globs` (see Task 1.4 — recorded, not fixed
  here).

## Tasks

### Phase 1: Establish the true surface

- [x] ✅ **Task 1.1**: Inventory every routed subcommand against evidence of
  human use. Classify each: routed, documented-only, or retire. Evidence
  before opinion — the owner reports never using several, and which ones is a
  question for the data. **Done in `e5f48101`** —
  [SURFACE-INVENTORY.md](SURFACE-INVENTORY.md) §1.1: 16 routed subcommands,
  zero typed `/hooks-daemon` invocations in 25 session transcripts; proposes
  6 routed, 10 documented-only, none retired.

- [x] ✅ **Task 1.2**: Inventory what `optimise` covers against the handler
  registry. The headline is 21 of 110, but the fair denominator is smaller:
  status-line components and always-on handlers are not things it should
  score. Produce the real actionable gap. **Done in `e5f48101`** —
  §1.2: 22 of 116 registered handlers named; 96 scorable after excluding 14
  status-line and 6 daemon-integrity handlers; real gap 74, of which 13 are
  off-by-default by design (and the checklist already recommends one of
  them, `lsp_enforcement`).

- [x] ✅ **Task 1.3**: Confirm the five scored areas are still the right
  taxonomy for a registry-derived checklist, or replace them. A hardcoded
  list can carry an arbitrary grouping; a derived one needs a rule that
  assigns any new handler to an area without human judgement. **Done in
  `e5f48101`** — §1.3: no registry field names the five areas; a tag
  precedence rule classifies 63 of 96 and leaves 33 unclassified (11
  untagged, 22 `workflow`-only), so the areas can only be derived after a
  tagging pass. Seven owner decisions listed at the end of the document.

- [x] ✅ **Task 1.4**: Decide whether docs QA and plan QA should honour the
  project-wide `daemon.exclude_paths`. **Decided and done in Plan 00362 Task
  2.9 (commit `406cbeef`)**: honour it; a fixture tree that must keep
  producing findings is declared by NOT listing it, never exempted by
  omission. Docs QA carries the globs on `DocumentationPolicy.exclude_paths`,
  plan QA on `CheckContext.exclude_paths`, both through
  `utils/path_exclusion`; all six handlers and both CLIs consult it.
  Original finding: **zero** references to it in either package, against 12
  handler modules that honoured it via `utils/path_exclusion.py`. It
  mattered because the shipped guidance repeatedly offers
  `daemon.exclude_paths` as the project-wide way to exempt paths, so a user
  configuring "ignored dirs" through it got silence from docs QA — the same
  symptom as the reported `scope_exclude_globs` bug fixed in `0054105b`.

  Mechanically small: `path_exclusion` is pure stdlib (so importing it does
  not break docs_qa's deliberate daemon/pydantic decoupling), and
  `policy_from_config` has only two production callers.

  NOT done on sight, because the blast radius runs the other way. Projects
  set `daemon.exclude_paths` broadly to exempt deliberately-bad fixture trees
  from the CONTENT blockers. Honouring it in docs QA would make those trees
  silently stop producing documentation findings — plausibly unwanted, and
  invisible when it happens. That is the argument for docs QA having its own
  narrower `scope_exclude_globs` in the first place. Settle the intent before
  changing the semantics; an owner decision, not an implementation detail.

### Phase 2: Make optimise registry-derived

- [x] ✅ **Task 2.1**: Drive the checklist from the registry, so a new handler
  appears without anyone remembering to add it. **Done in `bf5da1f5`** —
  `config_optimisation/checklist.py` builds one item per handler from
  `registry.iter_builtin_handler_classes()` plus the pseudo-event registry;
  the new `hooks-daemon optimise-checklist` verb renders it and
  `optimise-invoke.sh` Steps 3–5 run the verb instead of naming handlers
  (116 scored here, was 22).
- [x] ✅ **Task 2.2**: Decide how a handler declares it is NOT optimise's
  business. A derived list needs an opt-out at the handler, not a subtraction
  list in the skill — the subtraction list would rot exactly like the
  hardcoded list it replaces. **Done in `bf5da1f5`** per Decision 1: no
  opt-out; `Handler.get_relevance(context) -> Relevance` (default always
  relevant) overridden on `lsp_enforcement`, the two npm handlers,
  `validate_eslint_on_write`, the four ccy handlers and the flaggable trio.
  No standalone PHP guard exists in the registry (PHP is a strategy inside
  multi-language handlers), so nothing to override there.
- [x] ✅ **Task 2.3**: Keep the output readable as coverage grows. A review a
  human abandons because it is too long fails the same way Plan 00329's report
  does. **Done in `bf5da1f5`** — six computed areas
  (`config_optimisation/areas.py`, Decision 3); a fully-enabled area
  collapses to one line; only shortfalls and not-applicable handlers (with
  reason) are listed; totals and the numbered recommendations are computed.

### Phase 3: One housekeeping command

- [x] ✅ **Task 3.1**: Define what "full housekeeping" runs, and in what
  order. Some steps mutate (`optimise` edits config; the format check
  auto-fixes), so ordering and re-entrancy are load-bearing. **Done in
  `59b11a0a`** — `daemon/housekeeping.py` holds the 20-step list (12
  report-only, then 8 mutating, `optimise` last per Decision 5); tests pin
  the order and that every CLI-backed step names a verb the parser accepts.
- [x] ✅ **Task 3.2**: Decide which steps are report-only and which may act
  without confirmation. The safe default is report-everything, act-on-request;
  a single command that silently changes many things is worse than several
  explicit ones. **Done in `59b11a0a`** — Decision 6 as code: only
  `format-markdown` and `regenerate-docs` are RUN unconfirmed; the other six
  mutating steps are HELD until named on `--apply <step>`.
- [x] ✅ **Task 3.3**: Orchestrate independent steps as subagents, each
  returning what it CHANGED rather than what it read, so the coordinator's
  context does not accumulate every step's full output. **Done in
  `59b11a0a` / `f458057e`** — the `housekeeping` CLI verb prints the pass as
  a one-sub-agent-per-step procedure with a five-line reply contract; the
  skill routes `housekeeping` to it and `idle_housekeeping_advisory` derives
  its candidate audits from the same step list (Decision 7). The Decision 4
  surface trim (route 8, document 10) shipped in `f458057e`.

### Phase 4: The release-time guarantee

- [x] ✅ **Task 4.1**: A QA gate failing when a configurable handler is
  invisible to `optimise`, generalising the dispatchability test from
  `8bbd5bec`. **Done in `bf5da1f5`** —
  `tests/integration/test_skill_surface_coherence.py::TestOptimiseCoverage`:
  checklist paths equal the registry, the procedure runs
  `optimise-checklist`, and names no handler by hand.
- [x] ✅ **Task 4.2**: Extend it to the rest of the surface: a documented CLI
  command that does not exist, a skill doc naming a removed capability, a
  config key the skill references that the schema does not define. **Done in
  `bf5da1f5`** — same module: documented verbs (wrapper, `DAEMON_CLI`
  command lines, passthrough arms) against cli.py subparsers and aliases;
  retired handlers in code context on lines that do not call them retired;
  dotted config keys walked through the pydantic `Config` schema with
  handler names under `handlers.<event>` checked against `HandlerID`.
- [x] ✅ **Task 4.3**: Wire the gate into the release pipeline's blocking QA
  step so a drifted skill surface cannot ship. **Done in `bf5da1f5`** — the
  gate lives under `tests/`, so `llm_qa.py all`'s `tests` check (RELEASING.md
  Step 8, BLOCKING) already runs it; Step 8 now says so.

## Technical Decisions

Owner rulings on the seven questions [SURFACE-INVENTORY.md](SURFACE-INVENTORY.md)
ends with, taken 2026-09-08. They bind Phases 2 to 4.

### Decision 1: no opt-out mechanism — a relevance predicate instead

"Default" and "optimal" are different things: the default is what is safe
without knowing the project; optimal means enabled, making the most of the
system. So `optimise` scores EVERY registered handler and never needs an
exemption list. What a handler declares instead is when it is RELEVANT —
most are always relevant; `lsp_enforcement` needs an LSP, the npm handlers a
`package.json`, the PHP guards PHP, the ccy handlers (`goal_injection`,
`compaction_signal`, `model_fallback_detector`, `tool_disable_advisor`) the
supervisor, the flaggable-content trio that workflow. The optimal state of a
relevant handler is enabled; an irrelevant one is reported as "not
applicable here", never as a shortfall. Status-line components and the six
daemon-integrity handlers are scored too: their optimal state is enabled, and
a config that disabled one deserves the recommendation.

### Decision 2: default-off handlers are conditional, not inferior

Every default-off handler bar `idle_housekeeping_advisory` (beta) is off
because it is CONDITIONAL, which is Decision 1's relevance predicate. So the
rule is one rule: recommend enabling every relevant handler, whatever its
default. The current checklist's unconditional `lsp_enforcement`
recommendation is the inverse defect and goes away with the derivation.

### Decision 3: five derived areas plus a sixth catch-all

The five proposed areas stand, derived by the inventory's tag precedence
rule; a sixth area, "other guards", takes the remainder so no handler is
silently unclassified and no tagging pass gates delivery.

### Decision 4: route 6, document 10, keep `report` and `bug-report` both routed

They are different actions (an LLM-driven investigation versus a diagnostic
bundle); the skill text says which to reach for.

### Decision 5: report-only steps first, mutating steps after, `optimise` last

`optimise` restarts the daemon, so every other step runs against the config
the pass started with and `optimise` closes the pass.

### Decision 6: only the idempotent formatters act without confirmation

`format-markdown` and `regenerate-docs` may act; every other mutating step
reports and acts only on explicit request, as the plan's own default says.

### Decision 7: the housekeeping command reuses the idle advisory's runner

Phase 3 is a routed `/hooks-daemon housekeeping` invocation built on the
audit runner `idle_housekeeping_advisory` already has ("each sub-agent
returns what it CHANGED"), extended to the full step list; the advisory stays
the opt-in idle trigger for the same pass.

## Success Criteria

- [x] Adding a handler with no skill change fails the gate. (`bf5da1f5` —
  it cannot: the checklist is derived, and the gate fails if the derivation
  and the registry ever disagree.)
- [x] `optimise`'s covered set is derived, and a handler's relevance is
  declared at the handler rather than listed in the skill. (`bf5da1f5`)
- [x] One invocation runs the full housekeeping pass and reports what it did
  (`59b11a0a`, `f458057e`).
- [x] Every routed subcommand is one a human invokes; the rest are documented
  capabilities (`f458057e`).

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00330-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Milestone A — the real surface and the real coverage gap are measured.
- Milestone B — `optimise` is registry-derived and cannot silently omit a
  handler. Delivered in `bf5da1f5`.
- Milestone C — a single housekeeping invocation exists.
- Milestone D — the release gate blocks a drifted skill surface. Delivered in
  `bf5da1f5`.
