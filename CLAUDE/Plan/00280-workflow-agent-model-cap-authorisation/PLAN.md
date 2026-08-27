# Plan 00280: Workflow agent model cap in standing authorisation

**Status**: Not Started
**Created**: 2026-08-27
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plan 00223 (Complete, shipped v3.53.0) built the `standing_authorisations`
UserPromptSubmit handler
(`src/claude_code_hooks_daemon/handlers/user_prompt_submit/standing_authorisations.py`):
a project records a standing request as `{id, enabled}` entries under
`handlers.user_prompt_submit.standing_authorisations.options.authorisations`,
and the daemon replays the entry's text on every prompt (full text for the
first few deliveries, then a short form — decay, never skip).

This plan extends the built-in `workflow-orchestration` authorisation so that,
when enabled, it also declares a MODEL CAP for workflow/sub-agents. Default
policy wording: **Sonnet use is ENCOURAGED, Opus AS REQUIRED, Fable is BANNED
for workflow agents**. A project can reconfigure the family lists, but the
above is the default whenever the cap is on. The cap is injected advisory text
— the daemon cannot technically dictate which model the Agent tool selects —
with an optional advisory PreToolUse surface proposed as a later phase.

## Goals

- The `workflow-orchestration` authorisation text (full AND short forms)
  carries the model-cap policy when the cap is enabled.
- Cap policy is configurable per project (encouraged / as-required / banned
  model family lists) with the stated default of Sonnet-encouraged,
  Opus-as-required, Fable-banned.
- The cap ships consistent with Decision 3 of Plan 00223: nothing new is
  asserted unless the project has enabled `workflow-orchestration` itself.
- Docs (`docs/guides/HANDLER_REFERENCE.md`), config-changes manifest, and
  acceptance tests updated to match.

## Non-Goals

- No hard enforcement of model selection — the daemon has no mechanism to
  override the Agent tool's `model` parameter; any PreToolUse check is
  advisory only and is an optional phase, not the core deliverable.
- No change to the other built-in authorisation ids
  (`subagent-delegation`, `commit-push-cadence`).
- No change to the delivery cadence / decay mechanics from Plan 00223.
- No release — this plan ends at committed, QA-green code.

## Context & Background

- Handler source: `src/claude_code_hooks_daemon/handlers/user_prompt_submit/standing_authorisations.py`
  — built-in texts `_WORKFLOWS_TEXT` / `_WORKFLOWS_SHORT`, id constant
  `AUTHORISATION_WORKFLOWS = "workflow-orchestration"`; entries are plain
  `{id, enabled}` dicts today.
- Config: `.claude/hooks-daemon.yaml` under
  `handlers.user_prompt_submit.standing_authorisations.options.authorisations`
  (in this repo `workflow-orchestration` is currently `enabled: false`).
- Reference doc: `docs/guides/HANDLER_REFERENCE.md` (standing_authorisations
  section documents the `{id, enabled}` entry shape — must gain the new keys).
- Guardrails from Plan 00223 that MUST survive: entry text never contains
  ignore/disregard/override/overrule/bypass; every entry attributes the
  request to the project and names the config key (auditability test).

## Tasks

### Phase 1: Design & test scaffolding (RED)

- [ ] ⬜ **Task 1.1**: Write failing unit tests for the extended
  `workflow-orchestration` entry shape: `{id, enabled, model_cap: {...}}` —
  cap enabled/disabled, default family lists, per-project overrides.
- [ ] ⬜ **Task 1.2**: Write failing tests asserting the injected full and
  short texts include the cap sentence when the cap is on (default wording:
  Sonnet encouraged, Opus as required, Fable banned for workflow agents) and
  omit it when the cap is off or the entry is disabled.
- [ ] ⬜ **Task 1.3**: Write failing tests that malformed cap config (wrong
  types, unknown keys, empty lists) degrades silently to the default or to
  no cap — never takes the daemon down (advisory fail-soft, matching
  `_enabled_ids()` behaviour).
- [ ] ⬜ **Task 1.4**: Extend the Plan 00223 wording-guardrail tests to cover
  the cap text (no countermand verbs; names the config location).

### Phase 2: Implementation (GREEN)

- [ ] ⬜ **Task 2.1**: Implement cap config parsing on the
  `workflow-orchestration` entry (named constants for keys and default
  family lists — NO MAGIC).
- [ ] ⬜ **Task 2.2**: Compose the cap sentence into `_WORKFLOWS_TEXT` and
  `_WORKFLOWS_SHORT` at resolve time (template + configured lists), keeping
  the base text unchanged when no cap is configured.
- [ ] ⬜ **Task 2.3**: Refactor for clarity; run
  `./scripts/qa/llm_qa.py all` to green; restart daemon
  (`./bin/hooks-daemon restart`) and verify RUNNING.

### Phase 3: Docs, config, dogfooding

- [ ] ⬜ **Task 3.1**: Update `docs/guides/HANDLER_REFERENCE.md`
  standing_authorisations section: new entry keys, defaults, YAML example.
- [ ] ⬜ **Task 3.2**: Stage a `CLAUDE/UPGRADES/UNRELEASED/config-changes/`
  manifest entry for the new option (recommended where the project already
  enables `workflow-orchestration`).
- [ ] ⬜ **Task 3.3**: Update `get_acceptance_tests()` /
  `get_claude_md()` output as needed; regenerate docs
  (`./bin/hooks-daemon generate-docs`).
- [ ] ⬜ **Task 3.4**: Dogfood: enable the cap in this repo's
  `.claude/hooks-daemon.yaml` (with `workflow-orchestration` enabled),
  restart the daemon, and observe the injected text in a real prompt.

### Phase 4 (optional): Advisory enforcement surface

- [ ] ⬜ **Task 4.1**: Evaluate an advisory (never-deny) PreToolUse check on
  `Agent` tool calls whose `model` parameter names a banned family while the
  cap authorisation is enabled; if pursued, TDD it as a separate handler or
  an extension of an existing advisor, rate-limited per session.
- [ ] ⬜ **Task 4.2**: Document the decision either way in Technical
  Decisions (implementing or explicitly deferring).

## Dependencies

- Depends on: Plan 00223 (Complete — standing authorisations mechanism)
- Blocks: none
- Related: Plan 00278 (model/effort coupling), `model_fallback_detector`

## Technical Decisions

### Decision 1: Extend `workflow-orchestration` vs a new sibling authorisation id

**Context**: The cap could live inside the existing entry or as a new id
(e.g. `workflow-model-cap`).
**Options**:

1. Extend `workflow-orchestration` — the cap is a constraint ON workflow
   runs; it is meaningless without the workflow opt-in, and one id keeps the
   Plan 00223 rule "one id per distinct restriction" honest (this is not a
   new restriction being relaxed, it is scoping an existing relaxation).
2. New sibling id — independently toggleable, but it could be enabled
   without `workflow-orchestration`, producing a cap on runs the project has
   not authorised, and it doubles the injected text.

**Decision**: Option 1 — extend the built-in `workflow-orchestration` entry
with an optional `model_cap` sub-config. The cap only ever appears alongside
the workflow authorisation it qualifies.

### Decision 2: Configurability shape

**Context**: Per-project configurability with a fixed default policy.
**Decision**: The `workflow-orchestration` entry accepts an optional
`model_cap` mapping, e.g.:

```yaml
- id: workflow-orchestration
  enabled: true
  model_cap:
    enabled: true            # default true when the mapping is present
    encouraged: [sonnet]     # defaults shown
    as_required: [opus]
    banned: [fable]
```

Absent mapping ⇒ today's text, unchanged. Present mapping with defaults ⇒ the
stated policy wording. Lists are model-family strings rendered into the text;
unknown values are rendered verbatim (the daemon does not maintain a model
registry). Validation is fail-soft per the handler's advisory contract.

### Decision 3: Advisory text, not enforcement

**Context**: The daemon cannot control which model the Agent tool actually
uses; hooks can only observe and advise/deny tool calls.
**Decision**: The cap is injected advisory text in the authorisation. The
only possible enforcement surface is a PreToolUse check on `Agent` calls
whose `model` parameter names a banned family — and even that is advisory
(the parent may also spawn with no `model` at all, inheriting its own model,
which the daemon cannot see). That check is proposed as optional Phase 4,
never a DENY: model choice is a cost/capability judgement, and a hard block
on a `model` string would fight legitimate overrides.

## Success Criteria

- [ ] All new tests pass; full suite ≥95% coverage; `./scripts/qa/llm_qa.py all` green
- [ ] Daemon restarts RUNNING with the change
- [ ] Cap text appears in full AND short forms only when configured, with the
  default wording (Sonnet encouraged / Opus as required / Fable banned)
- [ ] Plan 00223 wording-guardrail tests still pass over the new text
- [ ] `HANDLER_REFERENCE.md` and UNRELEASED config-changes manifest updated
- [ ] Dogfooded in this repo's config

## Risks & Mitigations

| Risk                                                         | Impact | Probability | Mitigation                                                           |
| ------------------------------------------------------------ | ------ | ----------- | -------------------------------------------------------------------- |
| Cap wording reads as a countermand and trips guardrail tests | Medium | Low         | Draft wording against the guardrail test first (Task 1.4)            |
| Config shape churn if a model registry is later wanted       | Low    | Medium      | Keep lists as free strings; no enum of model families                |
| Phase 4 advisor false-positives on legitimate model choices  | Low    | Medium      | Advisory-only, rate-limited; explicit defer is an acceptable outcome |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00280-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan created (this commit)
