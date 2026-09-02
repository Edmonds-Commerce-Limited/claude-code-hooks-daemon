# Plan 00315: hidden agent budget detection

**Status**: In Progress
**Created**: 2026-09-02
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Research agents first; build only what the evidence supports

## Overview

Beyond the visible 5-hour/weekly token allowances, agent sessions carry
opaque operational budgets that surface only as mid-task tool failures: a
web search/fetch budget, the bounded subagent return channel, background
task concurrency, output-size truncation, and possibly others we have not
named. None announce themselves up front; an agent that does not recognise
the failure shape retries uselessly or silently degrades — the same failure
class as silent model substitution, which `model_fallback_detector` already
makes loud.

This plan is research-first: enumerate what is actually budgeted, find the
source of truth for each (documented vs observed-only), and capture the
exact refusal/error shapes from EXISTING evidence — our own session
transcript archive and public documentation — because deliberately
exhausting a live search budget to dogfood a detector would be disruptive
and expensive. Only after the catalogue exists do we decide what a
PostToolUse detector + occurrence ledger should match.

## Goals

- A catalogue document (BUDGETS.md in this plan folder) enumerating every
  budgeted/limited thing an agent session can hit, each entry recording:
  what it limits, where the source of truth is (official docs URL,
  harness-observed, or unknown), the exact observable failure shape
  (verbatim error/refusal text where captured), and whether it is
  detectable from a hook event payload.
- Verbatim failure-shape fixtures extracted from our transcript archive
  (redacted as needed) — the detector's future test corpus, so no live
  exhaustion dogfood is ever required.
- A build/no-build decision per budget: detector-worthy (stable shape,
  actionable response) vs not (unstable, invisible to hooks, or too rare).
- If the evidence supports it: a Phase 2 scope for a PostToolUse
  budget-exhaustion advisory handler + untracked JSONL occurrence ledger,
  tests driven entirely by the captured fixtures.

## Non-Goals

- Deliberately exhausting any live budget to generate evidence (owner
  ruling: difficult and disruptive; fixtures come from the archive and
  docs, not live provocation).
- Raising, pre-querying, or working around harness-side limits — only
  recognition and response are ours to own.
- Statusline integration (defer; decide after the catalogue exists).

## Tasks

### Phase 1: Research

- [x] ✅ **Task 1.1**: Documentation sweep — what do Anthropic/Claude Code
  docs actually say about search budgets, tool-use limits, subagent
  channel bounds, background task caps and any other per-session limits;
  record each with its URL as the source of truth, and note explicitly
  which limits have NO documented source (observed-only).
- [x] ✅ **Task 1.2**: Transcript archive mining — search this machine's
  session transcripts (~/.claude/projects/\*.jsonl via a subagent) for
  budget-shaped tool errors: search/fetch budget refusals, rate-limit
  errors, truncation markers, "budget" / "limit" / "exceeded" shapes in
  tool_result payloads. Extract verbatim (redacted) fixtures with event
  type and payload field locations.
- [x] ✅ **Task 1.3**: Synthesise BUDGETS.md from 1.1 + 1.2; per-budget
  build/no-build recommendation. Owner review checkpoint NOW OPEN — three
  questions at the foot of BUDGETS.md gate Phase 2.

### Phase 2: Detection (owner-ruled scope: GENERIC budget-exhaustion detector)

Owner ruling at the checkpoint: build a GENERIC PostToolUse detector that
matches budget/exhaustion messaging in any tool response — catching the
web-search shape today and any future budget message without a new
handler — and its advisory MUST make the agent surface budget issues to
the user VERY CLEARLY, with bold prominent prompting.

- [ ] ⬜ **Task 2.1**: PostToolUse `budget_exhaustion_detector` handler,
  fixture-driven TDD: generic pattern family (budget/exhausted/quota
  shapes, plus the pinned web-search fragments "Web search was not
  performed" / "web search budget" — never keyed on the configurable
  ceiling number), precision-conscious (no firing on ordinary prose about
  budgets in file contents the tool merely read — scope to tool_response
  of non-file-read tools by default, configurable). Advisory instructs the
  agent it MUST report the budget hit to the user prominently (bold 🚨
  banner wording), name the budget if identifiable, state what work is
  affected, and stop retrying the exhausted tool.
- [ ] ⬜ **Task 2.2**: Occurrence ledger — append each detection to
  `untracked/budget-exhaustion-events.jsonl` (timestamp, session, tool,
  matched fragment) so recurrence is visible across a session and to the
  owner afterwards.
- [ ] ⬜ **Task 2.3**: Full QA green; acceptance test entries via
  `get_acceptance_tests()`; ship enabled-by-default advisory (never
  blocks); document in generated guidance.

## Success Criteria

- [ ] BUDGETS.md exists with source-of-truth attribution per entry and
  explicit "unknown/observed-only" honesty where docs are silent.
- [ ] At least the search-budget failure shape is pinned by a verbatim
  fixture (or documented as never-yet-observed in our archive).
- [ ] Phase 2 decision recorded with owner sign-off, whatever it is.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00315-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
