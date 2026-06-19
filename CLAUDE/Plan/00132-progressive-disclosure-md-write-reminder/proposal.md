# Proposal — Plan 00132: PostToolUse Progressive-Disclosure Reminder

**Status**: Draft — awaiting sign-off. See the **Open Questions** at the end.

Grounded background is in `context.md`. This document is the proposed design plus the questions
that must be answered before the bare `PLAN.md` is filled in and implementation begins.

## Summary

Add a **PostToolUse advisory handler** that, after the agent writes a **project-level
documentation** markdown file, injects a short reminder of the progressive-disclosure rules and
asks *"is this in the right place — and is it the single source of truth, or should it link to
one?"* It never blocks; it only injects context for the next turn. It is **rate-limited** so it
never floods the context window.

This is the *positive* complement to Plan 00131's *block* (shipped v3.23.0).

## Proposed behaviour

- **Event**: PostToolUse, on a completed `Write` or `Edit` of a `.md` file.
- **Trigger scope**: `CLAUDE.md` (anywhere) and any `.md` under the `CLAUDE/` documentation tree,
  **EXCLUDING `CLAUDE/Plan/` and `CLAUDE/Journal/`** (explicit, self-evident locations — the user
  asked to skip these). See Open Question 1 for whether `docs/` and root `README.md` are in scope.
- **Advisory only**: non-terminal, never denies — pure context injection.
- **Rate-limited**: an in-memory event-counter cooldown mirroring `critical_thinking_advisory`
  (`_last_fired_count` + `_COOLDOWN_EVENTS`); fires at most once per N qualifying writes. Per-daemon,
  resets on restart (the established convention). See Open Question 2 for the default N.
- **Message**: names the belt-and-braces model (lean resident `CLAUDE.md`; `.claude/rules/*.md`
  with `paths:` globs; thin skills; plain links; single source of truth; no `@`-imports) and asks
  the "right place / SSoT — link instead of duplicate?" question. Shares phrasing with the Plan
  00131 guidance (DRY) but **omits the auto-memory framing**.

## Proposed shape (subject to the bare PLAN.md being filled after approval)

- New `handlers/post_tool_use/progressive_disclosure_reminder.py` — advisory, non-terminal,
  advisory priority in the PostToolUse range.
- `matches()` → True only for `Write`/`Edit` of a qualifying project-doc `.md` path; False for
  `CLAUDE/Plan/`, `CLAUDE/Journal/`, non-`.md`, non-project-doc paths, and non-Write/Edit tools.
- Cooldown gate in `matches()`/`handle()` mirroring `critical_thinking_advisory`.
- `get_claude_md()` advisory guidance + `get_acceptance_tests()`.
- Config entry, HandlerID/Priority constants, docs regeneration.
- TDD throughout; full QA 13/13; daemon-load + H-1 gate; live verification (fires once then cools
  down; silent on `CLAUDE/Plan/` and `CLAUDE/Journal/`).

## Non-Goals

- Not a blocker (advisory only).
- Not for `CLAUDE/Plan/` or `CLAUDE/Journal/`.
- No persistent cross-session TTL store in v1 (in-memory counter matches the existing pattern;
  `core/data_layer.py` persistence is a possible future enhancement).
- Not a replacement for Plan 00131's block — this is the encouragement side.

## Risks

| Risk                                               | Impact | Probability | Mitigation                                                    |
| -------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------- |
| Reminder spams the context window                  | Med    | High        | Cooldown counter; tune default; live-verify cadence           |
| Fires on plan/journal writes (annoying, redundant) | Med    | Med         | Explicit `CLAUDE/Plan/`+`CLAUDE/Journal/` exclusion + tests   |
| Over-broad trigger (docs/, README) feels naggy     | Low    | Med         | v1 scoped to CLAUDE.md + CLAUDE/ tree; widen later via config |
| Duplicates Plan 00131 block messaging              | Low    | Med         | Share phrasing (DRY); reminder omits the auto-memory framing  |

## Open Questions (to resolve before filling in PLAN.md)

1. **Trigger scope** — Proposed: `CLAUDE.md` (anywhere) + the `CLAUDE/` doc tree, minus
   `CLAUDE/Plan/` and `CLAUDE/Journal/`. **Should `docs/` (human-facing) and root `README.md`
   also trigger, or stay out of scope for v1?** (Out-of-scope is the proposed default; easy to
   widen later via a config option.)

2. **Default cooldown size** — How many qualifying project-doc `.md` writes between reminders?
   Proposed default ~5–10 (suggest **8**). Should it be configurable via a handler option (proposed:
   yes)?

3. **Reminder placement** — Proposed: PostToolUse (fires *after* the write lands, so it reflects on
   what was just written). The user mentioned "pre/post tool use" — **confirm PostToolUse** (vs a
   PreToolUse nudge before the write) is the intended timing.

4. **Cooldown granularity** — Should the cooldown count *only qualifying project-doc writes*
   (proposed), or *all* tool events (coarser, like the UserPromptSubmit advisory)? Proposed:
   count only qualifying writes, so the cadence tracks documentation activity specifically.
