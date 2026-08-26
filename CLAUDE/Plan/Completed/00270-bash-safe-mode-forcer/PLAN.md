# Plan 00270: bash safe mode forcer

**Status**: Complete
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

- [x] ✅ **Task 1.1**: Ratified via the dispatch instruction from main (see
  JOURNAL 26-08-26): mode warn|block with inject reserved/load-rejected;
  require default [errexit, pipefail] (nounset off-default); min_statements 2;
  only_with_mutator (default false); MUST_SKIP_SAFE_MODE_BECAUSE hatch.
- [x] ✅ **Task 1.2**: Extracted `utils/bash_flags.py` (split_statements,
  detect_safe_mode_flags, has_errexit, shared separator constants), TDD'd;
  `verification_result_gate` refactored to consume it and exposes
  `statements_contain_mutator` for the shared mutator table; its full suite
  stays green.

### Phase 2: TDD the handler (warn mode)

- [x] ✅ **Task 2.1**: Failing tests for `matches()` written first —
  Bash-only, `min_statements`, prelude stand-down incl. partial satisfaction
  and prelude split across statements (`tests/unit/handlers/pre_tool_use/test_bash_safe_mode.py`).
- [x] ✅ **Task 2.2**: ALLOW suite covers every Plan 00268 §6 shape (warn-mode
  ALLOW decision; never flagged under `only_with_mutator: true`),
  single-statement commands, pure `&&` chains, and the escape hatch.
- [x] ✅ **Task 2.3**: Handler implemented; `mode: warn` default,
  `mode: block` denies; `inject` and unknown modes raise at option-set time
  (load-time rejection via the registry's instantiation guard); message
  carries the blind-spot block and the escape hatch.
- [x] ✅ **Task 2.4**: `get_claude_md()` (opt-in framing, flags, blind spots,
  hatch, composition note) and two advisory `get_acceptance_tests()` entries.

### Phase 3: Integration and rollout

- [x] ✅ **Task 3.1**: HandlerID/Priority constants, `__init__` export,
  `init_config.py` default (`enabled: false`), `.claude/hooks-daemon.yaml.example`
  entry (disabled), dogfood `.claude/hooks-daemon.yaml` entry (enabled, warn),
  `docs/guides/HANDLER_REFERENCE.md` section + summary row, four integration
  classification tables, generated docs regenerated offline.
- [x] ✅ **Task 3.2**: Full QA run in the worktree (19/23; 4 env-limited),
  then on merged main by the merge reviewer: QA 23/23 PASSED, daemon restart
  RUNNING, and live warn-mode dogfooding over the daemon socket — advisory
  fires on an ungated multi-statement mutator sequence, silent with a
  `set -euo pipefail` prelude and on mutator-free sequences
  (`only_with_mutator: true`).
- [x] ✅ **Task 3.3**: `config-changes` entry added to
  `CLAUDE/UPGRADES/UNRELEASED/config-changes/vUNRELEASED.yaml` with
  `recommended: false`, `dormant: true`.

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

- [x] Handler ships `enabled: false` and, when enabled, defaults to
  `mode: warn`.
- [x] Every Plan 00268 false-positive shape is ALLOWed by test.
- [x] A command already carrying a satisfying `set` prelude is never flagged.
- [x] Detection uses the shared scanner and the extracted shared flag
  detection; `verification_result_gate`'s suite stays green after the
  extraction.
- [x] Guidance names the `set -e` blind spots verbatim.
- [x] Full QA passes; daemon restarts RUNNING. (Confirmed on merged main:
  QA 23/23, restart RUNNING, live socket dogfood — see Task 3.2.)

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

- Phases 1-3 implemented on worktree branch `agent-a828d42fa31810843-e32d96f4`
  (shared extraction 4f1196f6; handler TDD 62a2c3d3; registration/classification
  42f7b654; docs + manifest 72bf63a5). Review fixes 6139ff43 (end-of-options
  guard; scoped dogfood).
- Merged to main at 0f96b7ea (`--no-ff`, code-reviewed MERGE verdict): QA
  23/23 on merged main, daemon restart RUNNING, live socket dogfood verified.
