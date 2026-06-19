# Context — Plan 00132

Grounded background for the proposed PostToolUse progressive-disclosure reminder. This is
research and existing-mechanism notes only; the proposed design and open questions live in
`proposal.md`.

## Origin

Plan 00131 (shipped v3.23.0) lets a project **forbid untracked Claude memory** and have the
daemon enforce it by **blocking** memory writes, steering durable knowledge into tracked repo
docs (`allow_untracked_claude_memory: false` on `markdown_organization`). That is the *negative*
side — it stops the wrong thing.

This plan is the **positive** side the user asked for: after the agent writes a project-level
documentation markdown file, gently **remind** it of the progressive-disclosure rules and ask
whether the content is in the right place / is the single source of truth.

## User direction (2026-06-19) — verbatim intent

- *"a reminder on pre/post tool use after md file write might be helpful to rehint the rules about
  progressive disclosure and ask if the info is in the right place."* → PostToolUse advisory.
- *"skip for CLAUDE/Plan and CLAUDE/Journal folders as they are clear and explicit already."* →
  exclude those subtrees.
- *"its more about project level documentation eg other CLAUDE/ folders, CLAUDE.md files etc."* →
  target `CLAUDE.md` (anywhere) and the `CLAUDE/` doc tree (minus the excluded subtrees).
- *"we'd need to track how recently we last did the reminder and not spam it — it should have some
  kind of TTL before we remind again. I think this concept is already in use elsewhere?"* → yes;
  see the cooldown mechanism below.

## Existing mechanisms to reuse

### Cooldown / no-spam counter (the "TTL" the user remembered)

`handlers/user_prompt_submit/critical_thinking_advisory.py` already implements exactly this:

- keeps `self._last_fired_count` (initialised to a negative offset so the first event can fire),
- fires only when `current_count - self._last_fired_count >= _COOLDOWN_EVENTS`,
- on fire, sets `self._last_fired_count = current_count`,
- plus a length/random gate to further reduce flooding.

It is an **in-memory, per-daemon-process** counter — it resets on daemon restart. That is the
established convention in this codebase, so the new handler should mirror it rather than invent a
persistent store. (`core/data_layer.py` exists for persistent state if a future version wants a
cross-session TTL, but that is YAGNI for v1.)

### PostToolUse advisory shape

`bash_error_detector`, `lint_on_edit`, and `markdown_table_formatter` are PostToolUse,
non-terminal handlers that observe a completed tool call and either inject context or act, but
never block. The new handler slots in alongside them with the same shape.

### Path-scoping precedent

`handlers/pre_tool_use/markdown_organization.py` already classifies project-doc locations and has
helpers for the `CLAUDE/` tree and plan subdirectories (`_PLAN_SUBDIRECTORIES`, `normalize_path`,
`is_adhoc_instruction_file`). The new handler can reuse the same predicates where it reads cleanly
(DRY), or carry a small dedicated predicate set if coupling is awkward.

### Shared progressive-disclosure guidance (DRY with Plan 00131)

The belt-and-braces model is already written in `markdown_organization._deny_untracked_memory()`
and its policy-active `get_claude_md()` branch (lean resident `CLAUDE.md`; `.claude/rules/*.md`
with `paths:` glob frontmatter; thin intent-triggered skills; plain markdown links; single source
of truth; **no `@`-imports** — they re-inline eagerly rather than defer). The reminder should tell
the *same* story (factor the shared phrasing) but **omit the auto-memory framing**, since this
reminder is about where tracked docs go, not about blocking memory.

## Reference

- Progressive-disclosure reference gist:
  <https://gist.github.com/edmondscommerce/a5921ecb5b096439a6e505716e3a6a0d>
- Plan 00131 (shipped v3.23.0): the complementary *block* side.
