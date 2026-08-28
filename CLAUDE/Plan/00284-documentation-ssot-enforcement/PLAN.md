# Plan 00284: Documentation SSoT — one canonical home per fact, everything else points

**Status**: In Progress
**Created**: 2026-08-28
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The Claude Code landscape now offers many places to record durable knowledge, and
**there are far more ways to do this wrong than right**. Each surface is individually
good, but together they invite conflicting, distributed sources of truth:

- `.claude/rules/*.md` — excellent glob (`paths:`) matching
- `.claude/skills/` — excellent intent/metadata matching
- `.claude/agents/*.md` — carry their own instructions, but drift into carrying
  generally-relevant docs, or duplicating docs instead of pointing at the SSoT
- `CLAUDE.md` — root **and** sub-folder copies
- code comments
- GitHub issues / PRs
- `./docs/`
- `./CLAUDE/`
- plan folders (`CLAUDE/Plan/NNNNN-*/`) that end up holding persistently-relevant docs

**The right picture** (as directed by the user):

1. **One canonical home per fact.** Durable agent-facing truth lives in `./CLAUDE/`
   as clearly-named files broken into logical sections.
2. **Audience split.** `./docs/` is for **humans** — less verbose, easy to digest;
   `./CLAUDE/` is for **agents** — can be far more verbose and information-dense.
   Human docs MAY point at `CLAUDE/` for full depth. The agent tree owns the depth;
   the split is by AUDIENCE, never a licence to state a fact twice and let copies drift.
3. **Everything else POINTS, never DUPLICATES.** Rules, skills, agents, sub-folder
   `CLAUDE.md`, comments, issues/PRs, plan folders must LINK to the canonical doc,
   never restate its content.
4. **Plan folders are a drafting ground, not a home.** Docs may be created/generated
   inside a plan folder, but the final canonical version must be promoted into the
   project-level doc tree, leaving a pointer behind.

This is the documentation analogue of the **Plan QA system** (Plan 00144), which is
working well and is the reference: most doc rot is cross-file (a fact stated twice, a
pointer gone stale, a canonical doc that grew a second copy elsewhere), so enforcement
is a shared check catalogue consumed by three surfaces — edit-time PreToolUse lint, a
bulk/commit scan, and a SessionStart sweep.

This plan also **rolls in the progressive-disclosure strand** (user direction): the
tracked-docs progressive-disclosure model shipped by Plan 00131 is the delivery
mechanism for this strategy (rules + thin skills + plain links, no `@`-imports), and
the open progressive-disclosure work items are absorbed here rather than left as
scattered sibling plans.

## Goals

- **Firm up the RULES first.** A written, unambiguous policy: what "durable truth"
  is, which tree owns which audience, what counts as duplication vs a legitimate
  pointer, and the plan-folder promotion rule. Precise enough to enforce mechanically
  without the false-positive rate that gets a handler disabled (Plans 00208/00214
  measurement discipline).
- **Enforcement architecture** modelled on `plan_qa`: one pure check core, three
  surfaces (edit-time lint, bulk/commit scan, session sweep), config-driven,
  grandfathering allowlist.
- **Real-time guard**: PreToolUse detection of a write that duplicates canonical
  content or drops durable knowledge into a pointer-only surface.
- **Bulk scanner** (`hooks-daemon docs-qa` or similar, CI-able exit code) — a
  write-time rule cannot see what predates it (Core Standard 15 corollary).
- **Session sweep** advisory surfacing drift once per session.
- **A shipped `hooks-daemon-docs-qa` agent** (USER-DIRECTED): a read-only,
  daemon-deployed agent — delivered via the Plan 00279 generic agent install
  subsystem, like `hooks-daemon-plan-dedupe-scout` — that scans ALL project docs
  for conflicting truths, distributed truths, and duplication. It covers the
  semantic half the deterministic scanner cannot: paraphrase drift, two docs
  asserting incompatible facts, a truth scattered across surfaces with no
  canonical home. Reports findings with citations; never edits.
- **Absorb the progressive-disclosure strand**: supersede Plan 00132; absorb Plan
  00131's deferred residue (scaffolding skill; dogfood migration of this repo's own
  memory/doc drift); reconcile with Plan 00116's just-in-time guidance delivery.
- **Ship OFF by default / opt-in**; dogfood in THIS repo first, then clients.

## Non-Goals

- Auto-rewriting or auto-deleting docs. Detection + guidance only; a human/agent
  moves the content (same stance as `plan_qa`).
- Re-litigating what Plan 00131 shipped (untracked-memory block) or redoing Plan
  00116 — this plan builds on them.
- Semantic duplication detection in the DETERMINISTIC checks. Exact/near-exact
  copy and stale pointers are the mechanically-checkable subset; conflicting
  truths and paraphrase drift belong to the `hooks-daemon-docs-qa` AGENT, which
  reports rather than blocks — no deterministic check should attempt them.
- Enforcing prose STYLE (per-audience verbosity is guidance, not a blocking rule)
  unless the review finds a cheap, low-false-positive signal.

## Context & Background — prior art already in the tree

- **`markdown_organization`** (Plan 00131, shipped v3.23.0/v3.24.0): enforces markdown
  *location*, blocks untracked Claude memory by default, and its specialist deny
  message + `get_claude_md()` already teach the progressive-disclosure model. Natural
  home for the audience split + pointer policy, OR the reference for a sibling handler.
- **Plan 00132** (PostToolUse progressive-disclosure reminder, Not Started): a strict
  subset of this plan — to be superseded by it.
- **Plan 00131 deferred residue**: Phase 4 scaffolding skill (inventory docs,
  `@`-import audit, auto-build rules/skills) and Phase 6 dogfood (migrate this repo's
  own memory into tracked docs) — absorbed here.
- **Plan 00116** (CLAUDE.md token compression, Dormant): same spirit — guidance
  delivered just-in-time from one home instead of duplicated everywhere.
- **Plan 00144** (Plan QA): the architectural template — pure check core + three
  surfaces + one config policy block + grandfathering.
- **Plan 00172**: the SSoT-via-test-locked-registry pattern applied to metadata.

## Tasks

### Phase 1: Firm up the rules (review-driven)

- [x] ✅ **Task 1.1**: Dispatch a **Fable review agent** (read-only) to pressure-test
  the "right picture": survey every doc surface in THIS repo, find existing
  duplication and stale pointers as evidence, and imagine how OTHER hooks-daemon
  client projects would drift. It returns a proposed written ruleset, open questions
  it cannot settle, and candidate mechanically-checkable signals each with a
  false-positive assessment. Output: `REVIEW-fable.md` in this folder.
  DELIVERED — see `REVIEW-fable.md`: 12-rule draft ruleset (content-class pointer
  test), file:line-cited drift evidence (structured facts drift, prose mostly
  does not; agents lack a charter and hold most violations), 9 enforcement
  signals with FP assessments, and 7 human-judgement questions (its §E).
- [x] ✅ **Task 1.2**: Write the canonical policy doc `CLAUDE/DocumentationStrategy.md`
  — the SSoT for the SSoT rules, itself obeying them (pointed at from `CLAUDE.md`,
  not duplicated) — incorporating all seven Technical Decisions, the review's
  12-rule draft (its §C) and the sub-CLAUDE.md supplement. On the feature branch
  (Decision 3).
- [x] ✅ **Task 1.3**: Decide handler shape — settled as Decision 5: sibling
  `docs_qa/` package on the plan_qa template.
- [x] ✅ **Task 1.5**: Execute Decision 3 on the feature branch: gut
  `docs/PLAN_SYSTEM.md` to a human overview → `CLAUDE/PlanWorkflow.md`; fold
  `docs/QA-INFRASTRUCTURE.md` + `docs/QA-RUNNER-SETUP.md` into one accurate human
  QA doc; fix `CONTRIBUTING.md`'s forbidden handler skeleton; fix the five
  agent-facing files still instructing the denied `run_all.sh` (review §A.1).
  Final cross-check review before merge.
- [x] ✅ **Task 1.4**: Supersede Plan 00132 (status flip + archive move + README row,
  atomically) citing this plan; mark the absorbed 00131 residue as tracked here.

### Phase 2: Enforcement design (post-review)

All five Phase 2 designs are in `DESIGN-enforcement.md` (this folder),
critiqued by the review agent and amended (2 MUST + 5 SHOULD findings applied):

- [x] ✅ **Task 2.1**: Design the pure check core — drafted: `docs_qa/` package
  with a cached corpus index (link graph, quote index, block hashes) and ten
  declarative checks, each naming its stages and block-eligibility.
- [x] ✅ **Task 2.2**: Design the three surfaces + config — drafted: edit /
  commit-gate / sweep handlers + CLI over one core; top-level `documentation:`
  config block with per-check modes, grandfather allowlist, generated-doc
  manifest, module-doc registry; block-eligibility enforced structurally.
- [x] ✅ **Task 2.3**: Design the `hooks-daemon-docs-qa` agent — read-only agent
  definition (system prompt embedding the DocumentationStrategy ruleset, report
  format with file:line citations, scan strategy for large doc trees), shipped
  through the Plan 00279 agent install subsystem (version + md5 ledger,
  customisation detection, config-gated deploy). Starting design in review §D.10:
  inventory pass → topic-sharded deep reads; stable finding ids + an
  "adjudicated as fine" list feeding the grandfathering allowlist; invocation
  routes compose (on-demand primary / sweep-suggested / idle-housekeeping per
  Plan 00161). Per Decision 7 the agent explicitly hunts verbose comment blocks
  and treats them as documentation to cross-check.
- [x] ✅ **Task 2.4**: Design the `ssot-quote` mechanism (Decision 2): quote-block
  markup, heading/marker anchoring, mdformat-normalised comparison, edit-time
  verification of the quoting file + corpus-index re-verification of quoters when
  a SOURCE is edited.
- [x] ✅ **Task 2.5**: Design the docs-qa SKILL — a thin SHIM/helper for the
  docs-qa sub-agent (USER-DIRECTED): the intent-triggered entry point that
  dispatches the agent, bundling the deterministic helper scripts the agent uses
  (find/list long comment blocks, and other finders). The skill carries no doc
  body of its own — per the skills charter it points, and per Decision 7 the
  scripts are finders feeding the agent's worklist, never gates.

### Phase 3: Implement (order per DESIGN-enforcement.md; TDD throughout)

- [x] ✅ **Task 3.1a**: config model + `docs_qa/` skeleton + `pointer-resolves` +
  CLI. Delivered `62203a92` (details: JOURNAL 26-08-28).
- [x] ✅ **Task 3.1b**: `generated-doc-hand-edit` + generated-docs manifest.
  Delivered `d1a8a85a`.
- [x] ✅ **Task 3.1c**: `rules-file-shape` (worse-only) + `docs_qa_edit`/
  `docs_qa_sweep` handlers + dogfood enablement (warn modes). Delivered
  `1e0fbf8e` + `9282f28c`; commit gate deferred to 3.1e per plan_qa precedent.
- [x] ✅ **Task 3.1d**: `ssot-quote` verifier (`quote-drift`,
  `quote-source-stale`) per the hardened §2.4 spec. Delivered `2503a881`.
- [x] ✅ **Task 3.1e**: STAGED stage + `docs_qa_commit_gate` + STAGED-only checks
  - `module-doc-budget` + `at-import-census` + advisory cap. Delivered
    `e2ff33df` / `bbe9015e` / `080ffd1b` (+ scope-gap fix `f5f06b31`);
    generated-doc STAGED-half omission recorded in its module docstring.
- [x] ✅ **Task 3.1f**: `duplicate-block` (hard-coded advisory-only) + the
  mandatory hand-triage — see `TRIAGE-duplicate-block.md` (11 shared blocks /
  198 docs; floor held). Delivered `96afa291`.
- [x] ✅ **Task 3.1g**: `hooks-daemon-docs-qa` agent + docs-qa skill shim (via the
  Plan 00279 agent subsystem). Delivered `674f6a11`. `find-comment-blocks`
  CLI (Decision 7) reuses the existing comment-extraction engine;
  `install/skills.py` generalised to deploy every bundled skill dir.
  Deterministic pipeline verified end to end against this repo
  (168 sweep findings, 33 comment blocks in `src/`). Acceptance closed by a
  REAL dispatch of the built agent from the orchestrating session — full
  findings persisted in `AUDIT-dogfood-run-1.md` (9 new findings, 7 backlog
  confirmations, 6 tooling/definition follow-ups).
- [x] ✅ **Task 3.1h**: Follow-ups flagged by 3.1f's delivery (both verified real):
  (a) corpus cache-reuse gap — mtime/size-keyed reuse silently carries forward
  a pre-schema-extension record with empty new fields; add an index schema
  version that invalidates the whole cache on change; (b) sweep advisory cap
  starvation — checks accumulate in registration order so late checks never
  reach the capped 8 shown; give the cap per-check minimum representation.
  Both fixed: `corpus.py` gained a `_CACHE_SCHEMA_VERSION` constant embedded
  in the cache payload, discarding the whole index on mismatch/absence;
  `report.py`'s `format_advisory` now round-robins one finding per distinct
  check (BLOCK checks before ADVISE, stable) before filling remaining
  capacity in registration order, so a prolific check can no longer starve
  a rarer one out of the capped 8.
- [ ] ⬜ **Task 3.2**: Dogfood-migration worklist (deferred by the branch cross-check;
  each verified, none blocking):
  - `CLAUDE/AgentTeam.md` (~20 instructive `run_all.sh` sites + stale "all 7
    checks" counts) and `CLAUDE/Worktree.md` (~14 sites) → llm_qa.py + R5 cleanup
  - `CLAUDE/PlanWorkflow.md` still teaches 3-digit plan numbering (`001-`) while
    the system is 5-digit — the canonical deep doc is the wrong half of its pair
  - release SKILL.md's four incompatible step numberings (review §A.2.2) — belongs
    to skill thinning
  - ✅ `CLAUDE/CLAUDE.md` prose index → routing table (R7d) — done in slice E
  - ✅ both `.claude/rules/` files now pass the pointer-only contract (slice E):
    hot-reload contract promoted to a registered `.claude/ccy/CLAUDE.md`
    (`documentation.qa.registered_module_docs`); `ccy-supervisor-dogfooding.md`
    thinned to an 11-line pointer body; `importing-reports.md` thinned to a
    13-line pointer body against root CLAUDE.md's Report Handling section, with
    its identifier-replacement table promoted into
    `CLAUDE/development/DOC-CONVENTIONS.md`
  - **Audit run 1 additions**: findings N1–N9 in `AUDIT-dogfood-run-1.md`
    (worklist detail lives THERE). Headline: N1 venv layout stated four
    incompatible ways (severe), N2 68 non-allowlisted `@`-imports, N3
    priority table in 12 places with 3 wrong copies
  - ✅ N1, N8, N9 fixed (slice A, commit 33d4dd49): SELF_INSTALL.md now the
    canonical "Venv layout" home; stale spellings corrected/pointed in 7 docs;
    three dead links repaired; BUG_REPORTING.md points at llm_qa.py.
  - ✅ N2, N7 fixed (slice B): all 68 non-allowlisted `@`-imports converted to
    plain relative links (census now reports only root CLAUDE.md's 8
    grandfathered); `docs/CLAUDE.md` + `.claude/skills/CLAUDE.md` charters now
    point at DocumentationStrategy.md, routing tables kept.
  - ✅ N3, N5 fixed (slice C): `CLAUDE/HANDLER_DEVELOPMENT.md#priority-guide`
    (ssot-anchored) is now the single documented priority-band statement,
    corrected to 56-65 advisory with real handler examples and `priority.py`
    named as the R5 source; the other copies were pointed (ARCHITECTURE ×2,
    HooksSystem, LLM-INSTALL, PlanWorkflow, QA, RELEASING, HANDLER_REFERENCE,
    PROJECT_HANDLERS), ssot-quoted (CONFIGURATION, CONTRIBUTING) or corrected
    inline (dev-handlers.md — client-deployed, so a quote source would dangle);
    stale band docstrings in `constants/priority.py` + `core/handler.py` fixed.
    N5: HooksSystem.md's core.utils import mirror now points at
    PROJECT_HANDLERS.md, with `core/utils.py` docstrings as the API source.
  - ✅ N4 fixed (slice D): LLM-INSTALL.md ssot-anchored as canonical for all
    five shared blocks; LLM-UPDATE.md's copies now ssot-quote them (debug
    snippet enriched over the 80-char quote floor; Support list flattened so
    quote markers sit at column 0).
  - ✅ Triage quote-candidate #3 fixed (slice D): QA.md#qa-summary-example
    anchored canonical; CodeLifecycle/General.md now ssot-quotes it. Candidates
    #5/#7 are N4 above; #6 was already closed as N5 (slice C); #2
    (AgentTeam/Worktree) stays with its own worklist line.
  - ✅ N6 fixed (slice E): `CLAUDE/development/CLAUDE.md` rewritten as a
    13-line routing table covering all 5 files, audience framing corrected to
    point at DocumentationStrategy.md (R3).
- [x] ✅ **Task 3.3**: Tooling/agent-definition follow-ups T1–T6 in
  `AUDIT-dogfood-run-1.md` (duplicate-block line numbers; worktree exclusion
  in the corpus indexer; agent-definition prompt fixes; shipped-vs-deployed
  copies in the generated-docs manifest) — commit 129aee17. Sweep findings
  dropped 96 → 42 (module-doc-budget 61 → 7, 0 remaining worktree mentions).

## Technical Decisions

Seven user decisions settled 2026-08-28 (full context: `REVIEW-fable.md` §E,
`RULESET-sub-claude-md.md`, JOURNAL 26-08-28). Their normative content is now
CANONICAL in `CLAUDE/DocumentationStrategy.md` (R1–R13); one line each here:

1. **Two docs sites** — human + agent trees; NAMES are config, the SPLIT is
   mandatory when enabled; agent tree owns depth; plan dir under it.
2. **`ssot-quote` mechanism** — tracked verbatim quotation with source-naming
   metadata, mechanically drift-checked; replaces any idiom allowlist (R4b).
3. **Gut drifted human docs NOW, on a feature branch** with a final
   cross-check before merge. (Executed: Task 1.5.)
4. **Sub-CLAUDE.md** — outside-reader test + config registry; firm:
   `.claude/rules/*.md` are pointers ONLY (R7a/R7d).
5. **Sibling `docs_qa/` package** on the plan_qa template; one shared config
   block (R13 architecture).
6. **Block-capable, default-warn** — `block` is a per-check, per-project
   ratchet; fuzzy signals can never deny (structural block-eligibility).
7. **Comments** — the docs-qa agent hunts verbose comment blocks and treats
   them as documentation; finder scripts ship in a skill SHIM for the agent;
   no new deterministic comment check.

## Open Questions

All settled — see Technical Decisions above. The review's answers to this plan's
original five open questions are recorded verbatim in `REVIEW-fable.md` (final
section).

## Success Criteria

- [ ] A written, agreed ruleset exists as `CLAUDE/DocumentationStrategy.md`, obeying
  its own rules.
- [ ] Duplication + stale-pointer detection ships as a bulk scanner with a CI-able
  exit code, an edit-time guard, and a session sweep — config-driven, OFF by
  default upstream, dogfooded here.
- [ ] A `hooks-daemon-docs-qa` agent ships via the agent install subsystem and,
  dispatched against this repo, produces a useful conflicting/distributed-truth
  report (dogfood = its acceptance test).
- [ ] Plan 00132 superseded; 00131 residue and 00116 reconciled, cited not redone.
- [ ] Full QA green, daemon restart RUNNING, client-mode verified.

## Risks & Mitigations

| Risk                                          | Impact | Probability | Mitigation                                                                                              |
| --------------------------------------------- | ------ | ----------- | ------------------------------------------------------------------------------------------------------- |
| False positives get the handler disabled      | High   | High        | Measure FP rate on this repo before shipping anything blocking (00208/00214 discipline); advisory-first |
| "Duplication" is semantically hard            | High   | Med         | Scope automation to exact/near-copy + stale pointers; paraphrase drift stays advisory                   |
| Scope balloons into a repo-wide doc rewrite   | Med    | High        | Detection + guidance only (Non-Goal); no auto-edits; dogfood migration is its own bounded task          |
| Overlap/conflict with `markdown_organization` | Med    | Med         | Task 1.3 decides extend-vs-sibling explicitly                                                           |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00284-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan scaffolded (counter 283 → 00284).
- Task 3.1h (docs_qa cache schema versioning + advisory cap starvation fix) delivered at a03f2bba.
