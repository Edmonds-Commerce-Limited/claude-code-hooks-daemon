# Plan 00169: Prior-Art / SOTA Research and Feature Brainstorm

**Status**: In Progress
**Created**: 2026-07-16
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Before the next release, take a deliberate step back and scan the outside world.
This project has grown a large, opinionated surface of Claude Code hook handlers
(guardrails, workflow enforcement, plan QA, a PTY supervisor, status line, plan
journalling). It has largely been built inward-out from felt pain during
dogfooding. This plan asks the complementary question: **what is the rest of the
world doing, and what good ideas are we missing?**

The deliverable is not code. It is a well-sourced research + brainstorm dossier:
(1) a survey of prior art and state-of-the-art in Claude Code hooks, agentic-CLI
guardrails, and AI-dev-tooling policy/observability; (2) a gap analysis mapping
their ideas against our current handler set; and (3) a ranked backlog of
candidate features — including blue-sky ideas — each captured as a one-paragraph
brief that could seed its own future plan.

This is explicitly a **research + ideation** plan. Any idea that survives triage
graduates into its own implementation plan later; nothing here ships directly.

## Goals

- Survey **prior art** across the ecosystem: community Claude Code hook
  collections, competing/adjacent agentic CLIs (Codex CLI, Gemini CLI, Aider,
  Cursor, Windsurf, Continue, opencode, etc.) and how they do guardrails,
  rules, permissions, and observability.
- Identify **SOTA patterns** for the categories we already play in: policy/guardrail
  engines, workflow enforcement (TDD/commit hygiene), agent observability &
  telemetry, context/compaction management, multi-agent orchestration safety.
- Produce a **gap analysis**: for each external idea, do we already have it,
  partially have it, or miss it entirely.
- Produce a **ranked candidate-feature backlog** with short briefs (problem,
  sketch, why-it-fits, rough effort signal, novelty) — including genuinely novel
  ideas not obviously present in prior art.
- Leave a durable, tracked dossier under this plan folder that can seed future
  implementation plans.

## Non-Goals

- No implementation, no new handlers, no config changes ship from this plan.
- Not a competitive-marketing exercise — the audience is our own roadmap.
- No commitment to build any specific idea; triage/ranking only.
- Does not block the pending release on anything except producing the dossier
  (the user asked for this "before we release").

## Context & Background

Current active surface (from `.claude/HOOKS-DAEMON.md`): 37 PreToolUse handlers,
7 PostToolUse, 10 SessionStart, plus Stop/SubagentStop/Status/PreCompact/etc.
Themes already covered: destructive-command blocking, security antipatterns,
error-hiding, QA-suppression, TDD enforcement, plan QA (edit/commit-gate/sweep),
plan journalling, LSP-over-grep enforcement, recovery-cron & background-process
advisories, a stdlib PTY supervisor that auto-`/compact`s at red context, and a
rich status line. Recent plans (00161 idle housekeeping, 00163 journalling,
00166/00168 supervisor) show the direction of travel: observability + self-driving.

The research should be scoped to what a **hooks/guardrail daemon** can plausibly
own — not "rebuild Cursor". Bias toward ideas expressible as handlers, advisories,
CLI subcommands, or supervisor behaviours.

## Tasks

### Phase 1: Parallel External Research (fan-out)

- [ ] 🔄 **Task 1.1**: Community Claude Code hooks prior art — awesome-claude-code
  lists, popular hook repos/gists, blog posts on hook patterns. Capture the
  concrete hook ideas people actually build.
- [ ] ⬜ **Task 1.2**: Adjacent agentic-CLI guardrails — Codex CLI, Gemini CLI,
  Aider, opencode, Continue, Cursor/Windsurf rules & permission models. How
  do they gate dangerous actions, enforce workflow, and scope tool access.
- [ ] ⬜ **Task 1.3**: SOTA policy / guardrail engines & agent-safety — OPA/Rego,
  sandboxing (seatbelt/landlock/bubblewrap), permission brokers, secret
  scanners, LLM-guardrail frameworks (NeMo Guardrails, Llama Guard, etc.).
- [ ] ⬜ **Task 1.4**: SOTA agent observability / telemetry / eval — OpenTelemetry
  GenAI, LangSmith/Langfuse-style tracing, session analytics, prompt/response
  capture, cost/usage dashboards — what's transferable to a local hooks daemon.
- [ ] ⬜ **Task 1.5**: Context / compaction / long-running-agent management &
  multi-agent orchestration safety — memory systems, context budgeting,
  checkpoint/resume, orchestration guardrails.

### Phase 2: Synthesis & Gap Analysis

- [ ] ⬜ **Task 2.1**: Merge agent findings into `RESEARCH-FINDINGS.md`
  (deduped, sourced, one section per research angle).
- [ ] ⬜ **Task 2.2**: Build `GAP-ANALYSIS.md` — table mapping each external idea
  to have / partial / missing against our handler set.

### Phase 3: Brainstorm & Ranked Backlog

- [ ] ⬜ **Task 3.1**: Write `FEATURE-BACKLOG.md` — ranked candidate features with
  short briefs (problem, sketch, fit, effort signal, novelty), including
  blue-sky ideas.
- [ ] ⬜ **Task 3.2**: Recommend the top few to graduate into their own plans;
  note which are quick wins vs. large.

## Success Criteria

- [ ] Five research angles covered with sourced findings (URLs captured).
- [ ] `RESEARCH-FINDINGS.md`, `GAP-ANALYSIS.md`, `FEATURE-BACKLOG.md` committed
  under this plan folder.
- [ ] Backlog contains a ranked list with at least a handful of genuinely novel
  ideas plus clear have/partial/missing mapping.
- [ ] Top recommendations flagged for graduation into future plans.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is SSoT for "when"). -->

- Plan scaffolded and recovery cron armed (cron `4c8c64ca`).
