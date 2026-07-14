# Plan 00161: idle housekeeping mode

**Status**: In Progress
**Created**: 2026-07-14
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The daemon ships a non-durable hourly **failsafe recovery cron** that fires a
`FAILSAFE RECOVERY CHECK` prompt while the REPL is idle, so work stalled by an
external factor (Claude API overload, rate limit, 5-hour usage limit, network
failure) gets resumed. When there is genuinely nothing to resume, each tick is
a deliberate no-op and the agent simply re-stops. Observed in this very session:
a long run of consecutive no-op ticks, each answered with a near-identical
`STOPPING BECAUSE: ... failsafe tick found nothing to resume`. That idle time is
wasted.

This plan explores turning repeated no-op ticks into a signal: after the session
is demonstrably idle-and-caught-up (clean tree, nothing to resume, N consecutive
no-op ticks), the agent should enter a bounded **housekeeping mode** and spend
the free time on genuinely useful, safe, low-priority maintenance (plan-tree
hygiene, doc/truth drift, QA/coverage health, stale-artifact reaping, etc.)
instead of re-stopping. The mechanism should ideally be daemon-supported — a
handler that detects the repeated-no-op condition and injects ranked
housekeeping guidance — and it must be dogfooded in this repo first.

The critical constraints: housekeeping is strictly LOWER priority than real work
and any genuine recovery; it must yield instantly to a real user prompt; it must
never make risky unattended changes, create noisy/empty commits, fight the Stop
handler, or loop forever burning quota. When housekeeping runs dry it must
genuinely idle-stop.

## Goals

- Characterise the repeated-no-op-tick signal from this session's transcript
  (how many, how identical) and define a robust detection rule with
  false-positive guards.
- Produce a ranked catalogue of housekeeping tasks worth doing in free time,
  each scored by value × autonomy-safety, drawn from this repo but generalisable.
- Sketch a dogfoodable handler design (event type, priority band, terminal flag,
  state persistence for the no-op counter, config options, report-only vs.
  mutate-and-commit boundary).
- Decide an MVP slice small enough to build and dogfood here, then (pending user
  approval of the brainstorm) implement it under TDD.

## Non-Goals

- No autonomous risky changes: housekeeping never force-pushes, deletes user
  work, rewrites history, or makes decisions that are the user's to make.
- Not a heartbeat/pacing mechanism — this must not cause the agent to pace itself
  to the cron or burn quota during genuine idleness.
- Not looping through background agents or other sessions (out of scope, as with
  the supervisor foreground work in Plan 00160).

## Tasks

### Phase 1: Brainstorm & Design (divergent)

- [x] ✅ **Task 1.1**: Fable brainstorm agent explored the problem using this
  session's transcript + the repo, writing `BRAINSTORM.md` (detection mechanism,
  ranked housekeeping catalogue, safety guardrails, handler design sketch, open
  questions, MVP slice).
- [x] ✅ **Task 1.2**: Reviewed the brainstorm with the user; decisions captured
  (sub-agent dispatch, threshold 2, hello_world deprecation, beta/opt-in,
  report-only markdown files) — see Technical Decisions.

### Phase 2: Beta MVP Implementation (TDD) — opt-in, report-only, markdown reports

- [x] ✅ **Task 2.0**: Debug-confirmed a cron-originated prompt DOES raise
  UserPromptSubmit (observed directly this session: every failsafe-recovery tick
  arrives with a `UserPromptSubmit hook additional context` line). The
  UserPromptSubmit host (BRAINSTORM §A.2 Option B) is viable; no fallback needed.
- [ ] ⬜ **Task 2.1**: TDD the `idle_housekeeping_advisor` detector — matches the
  canonical `FAILSAFE RECOVERY CHECK` marker, transcript-tail no-op counter
  (threshold 2), guards (pending AskUserQuestion / real-user-prompt /
  interleaved tool_use), pass-cap sidecar (RED → GREEN → REFACTOR).
- [ ] ⬜ **Task 2.2**: Guidance injects an instruction to **fire specialist
  housekeeping sub-agent(s)** (protecting main-thread context) that run scoped,
  report-first audits and each write a **shareable markdown report file**.
- [ ] ⬜ **Task 2.3**: Reports mechanism — reports are markdown files written to
  an untracked reports directory (`untracked/reports/` by convention, gitignored,
  no size limit); add the dir to `extra_allowed_markdown_paths` so the
  markdown_organization handler permits them; dogfood-enable in this repo.
- [ ] ⬜ **Task 2.4**: Ship a how-to-create-reports guide (`docs/guides/…`)
  covering the report structure and the three sharing channels (agent-to-agent,
  Slack/colleague, GitHub issue for the public).
- [ ] ⬜ **Task 2.5**: Config options (`get_default_enabled() → False` — opt-in
  beta, OFF by default; `noop_threshold` default 2; `max_passes_per_session`;
  `reports_dir`); `get_claude_md()`; acceptance tests; `config-changes` manifest
  entry (recommended: leave OFF — beta); full QA; daemon restart RUNNING.

## Technical Decisions

### Decision 1: Housekeeping runs via specialist sub-agents, not inline

**Context**: The brainstorm MVP had the main thread execute a checklist inline.
**Decision** (user, 2026-07-14): housekeeping is delivered by **specialist
housekeeping sub-agents** the main thread fires. This protects main-thread
context (audits don't bloat it) and uses focused specialists that return concise
summaries. The advisory handler's role is to detect the idle condition and inject
guidance to *dispatch* those sub-agents — the main thread orchestrates, agents do
the work. Report-first still holds; any mutation/commit remains gated per the
three-tier boundary (BRAINSTORM §C).

### Decision 2: No-op threshold default = 2

**Decision** (user, 2026-07-14): trip at 2 consecutive no-op ticks
(config-overridable `noop_threshold`).

### Decision 3: Root-cause the doubled-stop via hello_world deprecation

**Context**: `hello_world_*` handlers inject `✅ <event> hook system active` on
every event; on Stop this makes Claude Code grant another turn (doubled idle
burn). **Decision** (user, 2026-07-14): these are debug/dogfooding confirmations
— deprecate/hide them from normal projects (default-disabled), keep enabled in
THIS repo for dogfooding/debugging. Tracked in its own plan (see README index);
this also removes the field-side doubled-stop independent of the housekeeping MVP.

### Decision 4: Ship as opt-in BETA, off by default, report-only

**Decision** (user, 2026-07-14): the handler ships in a **beta** stage — ready
for release but **off by default** (`get_default_enabled() → False`), with docs
suggesting users leave it off unless they want to try it. When enabled, it is
strictly **report-only**: it surfaces issues/suggestions, it does NOT
auto-mutate or auto-commit. (This resolves BRAINSTORM §E.2 — the MVP is
report-only; the Tier-M auto-fix mode is a deliberate later increment.)

### Decision 5: Reports are shareable markdown files (no size limit)

**Decision** (user, 2026-07-14): housekeeping (and reports generally) produce
**markdown report files**, not just in-context summaries. Markdown files are
chosen deliberately to encourage verbose, detailed reports that can embed
transcripts, logs, and code snippets with **no particular size limit**. Each
report is written to an untracked reports directory (`untracked/reports/` by
convention — gitignored, permitted via `extra_allowed_markdown_paths`) so it can
be shared through three channels:

- **Agent-to-agent** (direct dogfooding hand-off),
- **Colleague share** via Slack/etc.,
- **GitHub issue** for the general public.

A how-to-create-reports guide ships alongside so the format and sharing channels
are documented for users.

### Decision 6: `hooks-daemon-` prefix for all deployed skills/agents/commands

**Context** (user, 2026-07-14): the daemon will actively deploy skills/agents
into client projects and needs to manage/clean them up cleanly as they change.
**Decision**: every daemon-deployed artifact under `.claude/{skills,agents,commands}/`
is named with the canonical prefix **`hooks-daemon-`** (matching the existing
`hooks-daemon` skill and the `hooksdaemon.*` git-config namespace). The installer
enumerates `.claude/{skills,agents,commands}/hooks-daemon-*` to reconcile against
the currently-bundled set and remove stale artifacts on upgrade — no per-file
manifest needed, and client-authored artifacts (any other name) are never
touched. Short alias `hd-` is a fallback only if invocation verbosity bites; keep
ONE canonical prefix. The MVP handler dispatches generic sub-agents (no deployed
agent yet); this convention governs the deployment mechanism when it lands
(likely a follow-up plan).

## Success Criteria

- [ ] A robust detection rule that never trips while the user is waiting, mid-plan,
  or blocked only on human input.
- [ ] A ranked, safety-scored housekeeping task catalogue the user has reviewed.
- [ ] An MVP handler dogfooded in this repo that converts repeated no-op ticks
  into useful, bounded, report-first housekeeping without fighting the Stop
  handler or burning quota.

## Notes & Updates

### 2026-07-14

- Plan scaffolded from a live user request after observing ~15 consecutive
  no-op failsafe recovery ticks in this session.
- Failsafe recovery cron already live for this session: `a8af59d9`
  (`:37` hourly, non-durable). Reused — not duplicated.
- Phase 1 brainstorm delegated to a Fable sub-agent (transcript + repo as
  source); output at
  `CLAUDE/Plan/00161-idle-housekeeping-mode/BRAINSTORM.md`. Delivered Task 1.1.
- Brainstorm headline: recommend a **UserPromptSubmit advisory** handler
  (`idle_housekeeping_advisor`, ~priority 56, opt-in) that matches the canonical
  `FAILSAFE RECOVERY CHECK` marker, uses the **transcript tail as the no-op
  counter** (threshold 2), guards on pending-AskUserQuestion / real-user-prompt,
  and injects a **report-only, hard-capped** housekeeping checklist. Three-tier
  action boundary (Report / do+commit-under-daemon-gate / never-unattended);
  pass-cap + finding-dedupe + instant-yield anti-loop rules.
- Incidental dogfooding finding (own follow-up candidate): `hello_world_stop`
  injects context on **every** Stop, which makes Claude Code grant another turn —
  so each idle tick cost **two** stops (19 ticks → 38 turns). Rate-limiting or
  blanking that injection halves idle burn independently of this plan.
- Phase 1 awaiting user steer on the open questions (threshold 2 vs 3;
  report-only vs auto-commit for plan-qa/generate-docs; whether to fix the
  doubled-stop here or separately; multithread lock). See BRAINSTORM.md §E.
