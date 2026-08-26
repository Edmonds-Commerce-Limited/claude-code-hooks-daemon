# Plan 00270: bash safe mode forcer

**Status**: In Progress
**Created**: 2026-08-26
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

An OPT-IN, configurable PreToolUse handler (`bash_safe_mode`) that enforces a
bash safety prelude — `set -e` (errexit), `set -o pipefail`, and optionally
`set -u` (nounset) — on Bash tool invocations. The user's framing: "maybe this
should be an option at least, configure a set -e forcer, along with pipefail
etc - bash safe mode forcer".

This is explicitly the opt-in counterpart that Plan 00268 DEFERRED. That plan's
Non-Goals reject enforcing `set -e` as a standalone blanket rule ("Offer it as
remedy text in the block message, not as its own gate"), because forced errexit
breaks legitimate shapes: `grep -q p f; echo done`, labelled diagnostic sweeps,
and deliberate exit-code observers (`cmd > f 2>&1; echo "exit=$?"`). Those
objections are inherited here as design constraints to MITIGATE — via scoping,
thresholds and an escape hatch — not ignored. The handler ships
`enabled: false` and never becomes a default.

Design space, false-positive management, and the tool-input-rewriting research
(whether the handler can INJECT the prelude rather than only warn/deny) live in
[BRAINSTORM.md](BRAINSTORM.md).

## Goals

- Ship a `bash_safe_mode` PreToolUse handler, disabled by default, with each
  flag independently requirable (`require: [errexit, pipefail, nounset]`).
- Support `mode: warn` (default when enabled) and `mode: block`; document
  `mode: inject` as a future option gated on daemon `updatedInput` support
  (see Technical Decision 1).
- Fire only where the prelude buys anything: multi-statement invocations
  (configurable `min_statements`), with the Plan 00268 false-positive shapes
  provably ALLOWed.
- Reuse the shared shell scanner (`split_unquoted`,
  `strip_quoted_heredoc_bodies`) and the existing `_ERREXIT_PATTERN` family —
  no private bash parser (Plan 00268 success-criteria precedent).
- Guidance text that teaches `set -e`'s blind spots (if-conditions, non-final
  `&&` operands, command-substitution assignments) so users do not over-trust
  the prelude.
- Note the composition with `verification_result_gate`: a present prelude
  already stands that handler down, so the two are complementary, never
  double-firing.

## Non-Goals

- Enabling this handler by default, ever — Plan 00268's cry-wolf analysis
  stands; the config-changes manifest ships `recommended: false`.
- Blanket `;` → `&&` enforcement (rejected in Plan 00268, still rejected).
- Implementing `mode: inject` in this plan unless Technical Decision 1's
  daemon-side gap is closed first; the config surface reserves the value.
- Rewriting or second-guessing commands that already set their own flags — a
  command carrying its own `set` prelude satisfies the requirement as-is.
- Detecting or fixing `set -e` blind spots in user commands; the handler
  documents them, it does not analyse for them.

## Context & Background

- Plan 00268 built `verification_result_gate`, whose `_ERREXIT_PATTERN`
  (`src/claude_code_hooks_daemon/handlers/pre_tool_use/verification_result_gate.py`)
  already recognises `set -e` / `set -euo pipefail` / `set -o errexit` and whose
  statement/span split passes are the exact analysis this handler needs — DRY
  demands extracting and sharing, not duplicating.
- `utils/shell_segmentation.py` (`split_unquoted`,
  `strip_quoted_heredoc_bodies`) is the single quote-aware scanner; both are
  mandatory here.
- The daemon's `MUST_..._BECAUSE` escape-hatch convention (`git_stash`,
  `root_recursion_guard`, `comment_size`) is the model for the in-command
  exemption.

## Tasks

### Phase 1: Design ratification and shared-code extraction

- [ ] ⬜ **Task 1.1**: Human review of [BRAINSTORM.md](BRAINSTORM.md); ratify
  the config surface, defaults, and the open questions' answers into this
  plan's Technical Decisions.
- [ ] ⬜ **Task 1.2**: Extract the prelude-detection and statement-splitting
  logic shared with `verification_result_gate` into a shared utility (e.g.
  `utils/bash_flags.py`), TDD'd, with `verification_result_gate` refactored to
  consume it and its full test suite still green.

### Phase 2: TDD the handler (warn mode)

- [ ] ⬜ **Task 2.1**: Write failing tests for `matches()` — Bash-only,
  respects `min_statements`, stands down when a satisfying `set` prelude is
  already present (including partial satisfaction per the `require` list).
- [ ] ⬜ **Task 2.2**: Write failing tests for the ALLOW suite: every Plan
  00268 §6 false-positive shape (`grep -q p f; echo done`, exit-code
  observers, diagnostic sweeps), single-statement commands, and the
  `MUST_SKIP_SAFE_MODE_BECAUSE=` escape hatch.
- [ ] ⬜ **Task 2.3**: Implement the handler to pass; `mode: warn` default,
  `mode: block` honoured; guidance text includes the blind-spot education and
  the escape hatch.
- [ ] ⬜ **Task 2.4**: `get_claude_md()` and `get_acceptance_tests()`; the
  resident guidance states the handler is opt-in and what each flag does.

### Phase 3: Integration and rollout

- [ ] ⬜ **Task 3.1**: Register handler ID/priority constants, wire into config
  schema with `enabled: false`, add to `.claude/hooks-daemon.yaml.example`;
  document in `docs/guides/HANDLER_REFERENCE.md`.
- [ ] ⬜ **Task 3.2**: Full QA, daemon restart RUNNING, dogfood by temporarily
  enabling in this repo's config and exercising warn mode live.
- [ ] ⬜ **Task 3.3**: Stage a `config-changes` manifest under
  `CLAUDE/UPGRADES/UNRELEASED/` with `recommended: false`, so upgrades
  disclose the option without promoting it.

## Dependencies

- Builds on: Plan 00268 (verifier→mutator gate; shared errexit detection) —
  its Phase 2 is delivered in the working tree.
- Related: Plan 00200/00222 (shared shell scanner consolidation).

## Technical Decisions

### Decision 1: warn/block now; inject reserved, not implemented

**Context**: If Claude Code lets a PreToolUse hook rewrite tool input, the
handler could auto-prepend `set -euo pipefail` instead of warning.
**Findings**: Claude Code's current hooks documentation
(https://code.claude.com/docs/en/hooks.md) supports
`hookSpecificOutput.updatedInput` on PreToolUse responses. However, this
daemon's PreToolUse response schema
(`src/claude_code_hooks_daemon/core/response_schemas.py`) does not model the
field and sets `additionalProperties: false`, and
`core/hook_result.py` never serialises it — only the PermissionRequest schema
carries `updatedInput` today.
**Decision**: Ship warn/deny-only. Reserve `mode: inject` in the config
enum, rejected at load time with a message naming the missing daemon
capability, so the surface is stable when the serialisation gap is closed in a
follow-up. Full sources and shapes in [BRAINSTORM.md](BRAINSTORM.md) §2.
**Date**: 2026-08-26

### Decision 2: off by default, per the feature's own framing

**Context**: The request is "an option at least"; Plan 00268 records why
blanket enforcement gets a handler disabled.
**Decision**: `enabled: false` shipped; `recommended: false` in the
config-changes manifest; warn-first even when enabled.
**Date**: 2026-08-26

## Success Criteria

- [ ] Handler ships `enabled: false` and, when enabled, defaults to
  `mode: warn`.
- [ ] Every Plan 00268 false-positive shape is ALLOWed by test.
- [ ] A command already carrying a satisfying `set` prelude is never flagged.
- [ ] Detection uses the shared scanner and the extracted shared flag
  detection; `verification_result_gate`'s suite stays green after the
  extraction.
- [ ] Guidance names the `set -e` blind spots verbatim.
- [ ] Full QA passes; daemon restarts RUNNING.

## Risks & Mitigations

| Risk                                                                         | Impact | Probability | Mitigation                                                                                        |
| ---------------------------------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------------------------------------------- |
| Forced errexit breaks legitimate diagnostic shell and the handler cries wolf | High   | High        | Opt-in, warn-first, `min_statements` threshold, escape hatch, ALLOW suite from Plan 00268's table |
| Extraction refactor regresses `verification_result_gate`                     | High   | Low         | Task 1.2 keeps that handler's full suite green before any new behaviour lands                     |
| Users over-trust `set -e` and drop real gating                               | Medium | Medium      | Blind-spot education in guidance and `get_claude_md()`; composition note with the verifier gate   |
| `inject` mode promised but daemon cannot deliver it                          | Medium | Medium      | Reserved-but-rejected config value with an explanatory load-time message (Decision 1)             |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00270-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Not yet started.
