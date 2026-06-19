# Plan 00132: PostToolUse Progressive-Disclosure Reminder on Project-Doc Markdown Writes

**Status**: Not Started (awaiting user sign-off)
**Created**: 2026-06-19
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plan 00131 (shipped v3.23.0) gave projects a way to *forbid* untracked Claude memory and steer
durable knowledge into tracked project docs. This plan adds the **positive nudge** for the docs
that knowledge lands in: after the agent writes a **project-level documentation** markdown file,
a **PostToolUse advisory** re-hints the progressive-disclosure rules and asks *"is this in the
right place — and is it the single source of truth, or should it link to one?"*

This is advisory (never blocks). It fires **after** a `.md` write/edit to a project-doc location,
and is **rate-limited by a cooldown** so it never spams (the same event-counter pattern
`critical_thinking_advisory` already uses).

**User direction (2026-06-19), verbatim intent:**

- *"a reminder on pre/post tool use after md file write might be helpful to rehint the rules about
  progressive disclosure and ask if the info is in the right place."* → PostToolUse advisory.
- *"skip for CLAUDE/Plan and CLAUDE/Journal folders as they are clear and explicit already."* →
  exclude those subtrees.
- *"its more about project level documentation eg other CLAUDE/ folders, CLAUDE.md files etc."* →
  target CLAUDE.md (anywhere) and the `CLAUDE/` doc tree (minus the excluded subtrees).
- *"we'd need to track how recently we last did the reminder and not spam it — it should have some
  kind of TTL before we remind again. I think this concept is already in use elsewhere?"* → yes:
  `critical_thinking_advisory` uses `_last_fired_count` + `_COOLDOWN_EVENTS` (an in-memory
  per-daemon event counter). Reuse that pattern.

## Goals

- A new **PostToolUse advisory handler** (non-terminal, never blocks) that, after a `Write`/`Edit`
  of a **project-doc** markdown file, injects a short progressive-disclosure reminder + a
  "right place / single source of truth?" prompt.
- **Scope precisely**: triggers on `CLAUDE.md` (anywhere) and markdown under `CLAUDE/`, but
  **EXCLUDES** `CLAUDE/Plan/` and `CLAUDE/Journal/` (explicit, self-evident locations).
- **Rate-limited**: a cooldown (event counter) so it fires at most once per N qualifying writes —
  no flooding the context window. Reuse the `critical_thinking_advisory` cooldown pattern.
- Advisory content names the belt-and-braces model (lean resident `CLAUDE.md`,
  `.claude/rules/*.md` `paths:` globs, thin skills, plain links, SSoT, no `@`-imports) — coupled
  to the same progressive-disclosure story as Plan 00131's block message (shared guidance, DRY).

## Non-Goals

- **Not a blocker.** It never denies a write; it only injects context for the next turn.
- Not for `CLAUDE/Plan/` or `CLAUDE/Journal/` writes (explicitly excluded).
- Not a replacement for Plan 00131's block — this is the complementary *encouragement* side.
- No persistent cross-session TTL store in v1 (in-memory per-daemon counter matches the existing
  pattern; persistence via `core/data_layer.py` is a possible future enhancement, YAGNI for now).

## Context & Background — grounded mechanics

- **Cooldown pattern already exists**: `handlers/user_prompt_submit/critical_thinking_advisory.py`
  keeps `self._last_fired_count` and only fires when
  `current_count - self._last_fired_count >= _COOLDOWN_EVENTS` (plus a length/random gate). It is
  an **in-memory per-daemon-process** counter (resets on restart — acceptable, that is the
  established convention). This plan mirrors it: count qualifying project-doc md writes, fire only
  once per cooldown window.
- **PostToolUse advisory precedent**: `bash_error_detector`, `lint_on_edit`, `markdown_table_formatter`
  are PostToolUse non-terminal handlers — same shape (observe a completed tool call, inject context
  or act, never block). The new handler slots in alongside them.
- **Path scoping precedent**: `markdown_organization` already classifies project-doc locations and
  has helpers for `CLAUDE/` and plan subdirectories — reuse the same path predicates where sensible
  (DRY), or a small dedicated predicate set if coupling is awkward.
- **Shared guidance (DRY with Plan 00131)**: the progressive-disclosure model is already written in
  `markdown_organization._deny_untracked_memory()` and its policy-active `get_claude_md()`. Factor
  the shared phrasing so the reminder and the block tell one consistent story.

## Tasks

### Phase 0: Verification (BLOCKING)

- [ ] ⬜ **Task 0.1**: Confirm the PostToolUse hook_input shape for a completed `Write`/`Edit`
  (`tool_name`, `tool_input.file_path`) via `scripts/debug_hooks.sh` or a live socket probe — so the
  handler reads the right fields.
- [ ] ⬜ **Task 0.2**: Confirm the cooldown counter source available to a PostToolUse handler
  (what `critical_thinking_advisory` increments — a per-event counter on the handler base or a
  shared source). Decide the exact counter the new handler keys on.
- [ ] ⬜ **Task 0.3**: Decide the exact trigger path-set and exclusions (see Decision 1).

### Phase 1: Handler skeleton + scoping (TDD)

- [ ] ⬜ **Task 1.1**: New `handlers/post_tool_use/progressive_disclosure_reminder.py` — advisory,
  non-terminal, advisory priority (PostToolUse range). `matches()` returns True only for
  `Write`/`Edit` of a qualifying project-doc `.md` path; False for `CLAUDE/Plan/`, `CLAUDE/Journal/`,
  non-`.md`, non-project-doc paths, and non-Write/Edit tools. RED→GREEN with full path matrix.
- [ ] ⬜ **Task 1.2**: Register in config (`.claude/hooks-daemon.yaml`), HandlerID/Priority
  constants, docs generation.

### Phase 2: Cooldown / no-spam (TDD)

- [ ] ⬜ **Task 2.1**: RED→GREEN — fires at most once per `_COOLDOWN_EVENTS` qualifying writes
  (mirror `critical_thinking_advisory`); does not fire on every write. First write may fire
  (initial-offset like the existing handler). In-memory per-daemon counter.

### Phase 3: Reminder content (TDD)

- [ ] ⬜ **Task 3.1**: RED→GREEN — the injected context names the progressive-disclosure model and
  asks the "right place / single source of truth — link instead of duplicate?" question, EXCLUDING
  the auto-memory framing (that is Plan 00131's block). Share phrasing with the Plan 00131 guidance
  (DRY) where it reads cleanly.

### Phase 4: Integration, QA, docs, release

- [ ] ⬜ **Task 4.1**: `get_claude_md()` (advisory handler guidance), `get_acceptance_tests()`,
  restart daemon RUNNING, regenerate `.claude/HOOKS-DAEMON.md` + `<hooksdaemon>` block.
- [ ] ⬜ **Task 4.2**: Full QA 13/13, daemon-load, H-1 gate, live verification (fires once then
  cools down; silent on `CLAUDE/Plan/`/`CLAUDE/Journal/`), release.

## Technical Decisions

### Decision 1: Trigger path-set (PROPOSED — needs sign-off)

**Context**: user said "other CLAUDE/ folders, CLAUDE.md files etc." **Proposed**: trigger on
(a) any `CLAUDE.md` and (b) any `.md` under `CLAUDE/`, **EXCLUDING** `CLAUDE/Plan/` and
`CLAUDE/Journal/`. **Open**: should `docs/` (human-facing) and root `README.md` also trigger, or
stay out of scope for v1? Proposed: **out of scope for v1** (focus on the LLM-doc tree the user
named); easy to widen later via config.

### Decision 2: Advisory-only, PostToolUse (USER-DIRECTED)

PostToolUse, non-terminal, never blocks — pure context injection for the next turn.

### Decision 3: In-memory event-counter cooldown (USER-DIRECTED — "concept already in use")

Mirror `critical_thinking_advisory`'s `_last_fired_count` + `_COOLDOWN_EVENTS`. Per-daemon,
resets on restart. Cooldown size configurable via handler option (default TBD, e.g. 5–10 writes).

## Success Criteria

- [ ] After a project-doc `.md` write, an advisory reminder is injected — at most once per cooldown.
- [ ] No reminder for `CLAUDE/Plan/` or `CLAUDE/Journal/` writes, non-`.md`, or non-Write/Edit tools.
- [ ] Never blocks (advisory only).
- [ ] Reminder names the progressive-disclosure model + the "right place / SSoT" question.
- [ ] Full QA 13/13, daemon RUNNING, H-1 gate, live verification pass.

## Risks & Mitigations

| Risk                                               | Impact | Probability | Mitigation                                                       |
| -------------------------------------------------- | ------ | ----------- | ---------------------------------------------------------------- |
| Reminder spams the context window                  | Med    | High        | Cooldown counter (Decision 3); tune default; live-verify cadence |
| Fires on plan/journal writes (annoying, redundant) | Med    | Med         | Explicit `CLAUDE/Plan/`+`CLAUDE/Journal/` exclusion + tests      |
| Over-broad trigger (docs/, README) feels naggy     | Low    | Med         | v1 scoped to CLAUDE.md + CLAUDE/ tree; widen later via config    |
| Duplicates Plan 00131 block messaging              | Low    | Med         | Share phrasing (DRY); reminder omits the auto-memory framing     |

## Notes & Updates

### 2026-06-19

- Scaffolded via `mkplan.bash` (counter 131→132) immediately after shipping v3.23.0.
- Captures the user's three design messages. Grounded the cooldown in
  `critical_thinking_advisory` (`_last_fired_count` + `_COOLDOWN_EVENTS`) and the PostToolUse
  advisory shape in `bash_error_detector` / `lint_on_edit` / `markdown_table_formatter`.
- **Awaiting sign-off** on Decision 1 (exact trigger path-set; `docs/`+`README` in or out) and the
  default cooldown size, then ready to TDD.
