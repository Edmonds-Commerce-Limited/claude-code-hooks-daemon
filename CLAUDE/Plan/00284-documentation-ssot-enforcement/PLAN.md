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
- [ ] ⬜ **Task 1.2**: Resolve the remaining open questions (below), then write the
  canonical policy doc `CLAUDE/DocumentationStrategy.md` — the SSoT for the SSoT
  rules, itself obeying them (pointed at from `CLAUDE.md`, not duplicated).
- [ ] ⬜ **Task 1.3**: Decide handler shape — extend `markdown_organization` vs a new
  sibling handler + `docs_qa` check core. Record as a Technical Decision.
- [ ] ⬜ **Task 1.4**: Supersede Plan 00132 (status flip + archive move + README row,
  atomically) citing this plan; mark the absorbed 00131 residue as tracked here.

### Phase 2: Enforcement design (post-review)

- [ ] ⬜ **Task 2.1**: Design the pure check core (candidate checks: `pointer-resolves`,
  `no-duplicate-canonical`, `plan-doc-promoted`, `audience-placement`) — declarative
  registry, `plan_qa`-style.
- [ ] ⬜ **Task 2.2**: Design the three surfaces (edit-time lint, bulk/commit scan,
  session sweep), the config policy block, and the grandfathering allowlist.
- [ ] ⬜ **Task 2.3**: Design the `hooks-daemon-docs-qa` agent — read-only agent
  definition (system prompt embedding the DocumentationStrategy ruleset, report
  format with file:line citations, scan strategy for large doc trees), shipped
  through the Plan 00279 agent install subsystem (version + md5 ledger,
  customisation detection, config-gated deploy). Decide how it is invoked:
  on-demand dispatch, suggested by the session sweep when drift is found, and/or
  an idle-housekeeping specialist (Plan 00161 integration).

### Phase 3: Implement (expanded after Phase 2)

- [ ] ⬜ **Task 3.1**: Placeholder — TDD per surface, bulk-scan CLI, daemon-restart
  verification, client-mode fixture verification, dogfood in this repo, full QA gate.

## Technical Decisions

### Decision 1: `docs/` points at `CLAUDE/` for depth (USER-DIRECTED)

**Context**: two trees could either be independent renditions (drift risk) or a
thin/deep pair. **Decision**: `docs/` is the human-facing rendition — terse and
digestible — and MAY link into `CLAUDE/` for full depth. `CLAUDE/` owns the depth.
This keeps one depth-owner per fact and makes the drift rule mechanical: a `docs/`
file restating canonical `CLAUDE/` content at length is a violation; a summary +
link is the intended shape.

## Open Questions (for the review to inform, Task 1.2 to settle)

1. **What is a legitimate pointer** vs a duplication? (One-line summary + link is
   fine; how much restatement before it is a second copy that will go stale?)
2. **Comments**: `comment_changelog` already bans changelog narrative in comments.
   Is "durable knowledge that belongs in a doc" a checkable comment signal, or
   advisory-only?
3. **Agents/skills**: how to detect an agent/skill `.md` that has grown a general
   doc instead of staying a thin pointer, with a low false-positive rate?
4. **Detection method**: content-hash/shingling for near-duplicate blocks?
   Link-graph resolution for stale pointers? Which fit a PreToolUse latency budget
   vs batch-only?
5. **Generated docs**: `.claude/HOOKS-DAEMON.md` and the `<hooksdaemon>` CLAUDE.md
   block are machine-generated FROM handler source — generation from one source is
   compliant SSoT, but the scanner must know that or it will flag every generated doc.

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
