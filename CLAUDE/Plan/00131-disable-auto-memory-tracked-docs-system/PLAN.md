# Plan 00131: Block Untracked Claude Memory + Tracked-Docs Progressive Disclosure

**Status**: Dormant (Phases 1–5 shipped in v3.23.0; the deferred residue — Phase 4 scaffolding skill + Phase 6 dogfood migration — is now tracked by Plan 00284, the documentation-SSoT enforcement plan that absorbs the progressive-disclosure strand)
**Created**: 2026-06-19
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Claude Code's cross-session **auto-memory** writes unversioned, un-reviewed, per-checkout
knowledge into untracked Claude meta files (e.g. `~/.claude/projects/<slug>/memory/MEMORY.md`
and per-fact files). For teams that want a single, reviewable, git-tracked source of truth,
that is a knowledge silo: it drifts from the repo, is invisible to teammates, and bypasses
code review. This plan lets a project **forbid untracked Claude memory** and have the hooks
daemon **enforce it by blocking the writes**, steering all durable knowledge into **tracked
repo docs** via Claude Code's progressive-disclosure features.

**Key design decision (from the user): enforce by BLOCKING at the daemon layer, not by trying
to disable Claude's memory.** Attempting to disable Claude Code's memory (env var / settings
flag) is **not reliable** across versions and surfaces. The daemon, however, sees every
`Write`/`Edit` and can deny it deterministically — so *even if Claude memory stays enabled, we
simply block the memory writes.* The block is the enforcement; no dependence on a fragile
toggle.

**The mechanism is a new explicit bool, `allow_untracked_claude_memory`, on the existing
`markdown_organization` handler** (which already governs where markdown may be written and
today *allows* Claude memory paths). The user's words: *"markdown blocker is actually perfect,
but I'd like something more explicit — `allow_untracked_claude_memory`."* Default `true`
preserves today's behaviour. Set `false` and the handler stops allowing Claude-memory `.md`
writes and **blocks them with a specialist message** — not the generic "put markdown in an
allowed location" text, but *"this project does not keep knowledge in untracked Claude memory —
document it in tracked project docs"* — which leads directly into the **progressive-disclosure**
guidance. Reading memory is always allowed (so existing memory can be migrated out).

This couples tightly to **progressive disclosure as a first-class concept**: the block is only
half the story; the other half is telling the agent *where* durable knowledge goes and *how*
to structure it for token-efficient on-demand loading. Grounded in the reference guide
([gist a5921ecb](https://gist.github.com/edmondscommerce/a5921ecb5b096439a6e505716e3a6a0d)):
a "belt-and-braces" model — `.claude/rules/*.md` with `paths:` glob frontmatter (deterministic,
contextual loading) plus thin intent-triggered skills, each pointing at a single-source-of-truth
body; `@`-imports avoided (they re-inline rather than defer); safety/orientation stays resident,
everything else loads on demand.

## Goals

- New explicit bool **`allow_untracked_claude_memory`** on `markdown_organization`
  (default `true` = unchanged behaviour). When `false`, Claude-memory `.md` writes are
  **blocked at the daemon layer** regardless of whether Claude's own memory is enabled.
- A **specialist block message** for that case — distinct from the generic markdown-location
  message — that says *document in tracked project docs* and points into the progressive-
  disclosure guidance. This is the tight coupling point between the block and the docs system.
- **Reads always allowed** — only `Write`/`Edit` (and bash redirects) to Claude-memory paths
  are denied — so a project can read and migrate its existing memory.
- **Progressive disclosure as a first-class thing**: establish the tracked-docs target model
  (belt-and-braces rules + thin skills + plain links, SSoT, no `@`-imports) as daemon guidance,
  and the migration path memory → tracked docs.
- Reconcile `optimal_config_checker`'s auto-memory check so a project that has *chosen* this
  policy is not also nagged that memory being off is "sub-optimal" (no contradictory advice).
- Do **not** depend on toggling Claude's memory setting. (Optionally, best-effort *advise* the
  user to disable it too — but the block stands alone and is the real enforcement.)

## Non-Goals

- Reliably disabling Claude Code's own memory engine — explicitly rejected as unreliable; the
  daemon-layer block is the enforcement instead.
- Removing/weakening memory for projects that do not opt in (default `true` = today's behaviour).
- Deleting anyone's existing memory files. The block prevents *new* writes; migrating existing
  content into tracked docs is a guided step, never an automated deletion.
- Blocking *reads* of memory files (explicitly allowed — required for migration).

## Context & Background — grounded mechanics (verified further in Phase 0)

- **`markdown_organization`** already has the exact hook: an explicit allow-rule for Claude
  Code memory writes (`~/.claude/projects/*/memory/*.md`, and files outside the project root).
  The new bool inverts that allow for Claude-memory paths specifically — this is why "the
  markdown blocker is perfect" and the new option lives there (config SSoT for the policy).
- Auto-memory is written **via the `Write` tool** (the harness memory instructions say so) to
  `~/.claude/projects/<slug>/memory/` as `.md` files (MEMORY.md index + per-fact files). So the
  writes ARE interceptable by `markdown_organization` (a PreToolUse Write/Edit handler on `.md`).
- **`optimal_config_checker._check_memory()`** keys on `CLAUDE_CODE_DISABLE_MEMORY` and today
  treats memory-disabled as *sub-optimal*. Under this policy that advice is contradictory and
  must be suppressed/inverted (coordination, DRY — one "policy active" source of truth).
- The block message must be a **specialist branch**, so `markdown_organization` needs to detect
  "blocked because Claude-memory path + policy active" vs "blocked because disallowed location"
  and emit different guidance.

## Tasks

### Phase 0: Verification (BLOCKING) — ✅ COMPLETE

- [x] ✅ **Task 0.1**: Found the exact inversion point. `markdown_organization.matches()`
  (line ~617) currently does `if "/.claude/projects/" in file_path and "/memory/" in file_path: return False` (allow). Under the policy this becomes `return True` (intercept). `handle()`
  (line ~824) is where the specialist-message branch is added, keyed on the same predicate.
- [x] ✅ **Task 0.2**: The SSoT path predicate is the **raw-path** match
  `"/.claude/projects/" in file_path and "/memory/" in file_path`, checked BEFORE `resolve()`
  (a comment at the call site notes resolve() maps ccy-symlinked paths back into the project and
  would mis-handle them). The real write path Claude uses — `~/.claude/projects/<slug>/memory/*.md`
  (e.g. `/root/.claude/projects/-workspace/memory/MEMORY.md`) — matches it; writes are `.md`
  `Write`/`Edit` calls (already interceptable). Precise to Claude-meta memory; no false positives
  on arbitrary project `memory/` dirs.
- [x] ✅ **Task 0.3**: Config home = a new `allow_untracked_claude_memory: bool = True` option on
  `markdown_organization` (registry sets handler instance attributes from options after
  instantiation, exactly like `_extra_allowed_markdown_paths`). That single attribute is the
  "policy active" SSoT; `optimal_config_checker` reads the same policy to suppress its
  re-enable-memory advice (Phase 3). No new handler, no parallel config.

### Phase 1: `allow_untracked_claude_memory` option + block (TDD) — ✅ COMPLETE

- [x] ✅ **Task 1.1**: Added `allow_untracked_claude_memory: bool = True` instance attribute on
  `MarkdownOrganizationHandler` (option key constant `ALLOW_UNTRACKED_CLAUDE_MEMORY_OPTION`);
  registry injects it generically via `setattr(instance, f"_{option_key}", ...)`. Default
  preserves current behaviour.
- [x] ✅ **Task 1.2**: RED→GREEN — when `false`, `Write`/`Edit` to a Claude-memory `.md` path
  is **denied** (matches() inverts the allow-rule via `_is_claude_memory_path`); when `true`,
  allowed exactly as today. Reads unaffected (handler only matches Write/Edit/bash-write).
- [x] ✅ **Task 1.3**: RED→GREEN — bash redirects (`>`/`>>`) and `tee` into memory paths are
  denied under the policy (`_bash_memory_write_target`); reads (`cat`/`grep` path) are NOT
  matched. Non-memory redirects unaffected.

### Phase 2: Specialist message + progressive-disclosure guidance (TDD) — ✅ COMPLETE

- [x] ✅ **Task 2.1**: RED→GREEN — `_deny_untracked_memory()` emits the **specialist message**
  (UNTRACKED CLAUDE MEMORY IS DISABLED … document in tracked project docs; progressive
  disclosure), distinct from the generic wrong-location message. Used by both the Write/Edit
  and bash side-door paths via the shared `_claude_memory_block_target()` SSoT.
- [x] ✅ **Task 2.2**: `get_claude_md()` now branches on the policy — under the policy it names
  the tracked-docs target model: belt-and-braces `.claude/rules/*.md` (`paths:` globs) + thin
  skills + plain links, SSoT, **no `@`-imports**, reads-allowed-for-migration. (Default repo
  keeps the original guidance, so the `<hooksdaemon>` block is unchanged here.)

### Phase 3: Reconcile optimal_config_checker (TDD) — ✅ COMPLETE

- [x] ✅ **Task 3.1**: RED→GREEN — `_untracked_memory_forbidden()` reads the policy from the
  daemon config (SSoT, fail-safe). When active, `_check_auto_memory()` always passes and frames
  disabling memory as optional best-effort — no contradictory "re-enable memory" nag.

### Phase 4: Progressive disclosure as a first-class thing (scope per Phase 0.3) — ✅ COMPLETE (guidance)

- [x] ✅ **Task 4.1**: The progressive-disclosure target model (belt-and-braces rules + thin
  skills + plain links, SSoT, no `@`-imports, reads-allowed-for-migration) is established as
  durable daemon guidance in BOTH the specialist block message and the policy-active
  `get_claude_md()`. **Decision**: the *scaffolding skill* (inventory docs, `@`-import audit,
  auto-build rules/skills) is a focused FOLLOW-UP plan, not this one — the block + guidance ship
  first so the feature release stays tight (Risk-row mitigation honoured).

### Phase 5: Integration, QA, docs, release — ✅ COMPLETE

- [x] ✅ **Task 5.1**: Config left at default (`allow_untracked_claude_memory` absent ⇒ `true`) so
  this repo's behaviour is unchanged; daemon restarted RUNNING with new code; docs regenerated.
- [x] ✅ **Task 5.2**: Full QA 13/13 (8657 tests, 95.1%); daemon-load verified; H-1 acceptance gate
  23/23; live verification — temporarily enabled the policy in config, restarted, probed the live
  socket (memory Write→DENY specialist, bash redirect→DENY, bash read→ALLOW), then reverted config
  - restart (default ALLOW restored). Opus doc review APPROVE; code-reviewer APPROVE (0 blocking).
- [x] ✅ **Task 5.3**: Released as **v3.23.0** bundled with the Plan 00130 `mkplan.bash` work
  (release commit 9285093, tag 9ed4a5f). truth-changes/v3.23.0.yaml records the mkplan change.

### Phase 6: Dogfood (decide during the plan) — DEFERRED (follow-up)

- [ ] ⬜ **Task 6.1**: **Decision**: do NOT activate `allow_untracked_claude_memory: false` in
  THIS repo in this plan. Activating it requires migrating the existing rich `MEMORY.md` content
  into tracked docs (rules/docs/CLAUDE) — a larger body of work that would bloat the feature
  release. Deferred to a focused follow-up so the feature ships tight (default `true` here keeps
  current behaviour and an unchanged `<hooksdaemon>` block).

## Technical Decisions

### Decision 1: Enforce by blocking, not by disabling memory (USER-DIRECTED)

**Context**: disabling Claude Code's memory (env var / settings flag) is not reliable across
versions/surfaces. **Decision**: the daemon **blocks the memory writes** at the PreToolUse layer;
this is deterministic and version-independent. Actively toggling Claude's memory setting is
dropped as the enforcement mechanism (at most a best-effort advisory). The block stands alone.

### Decision 2: Reuse `markdown_organization` + one explicit bool (USER-DIRECTED)

**Context**: `markdown_organization` already governs markdown write locations and currently
allows Claude-memory paths. **Decision**: add `allow_untracked_claude_memory: bool = True`
there (the policy SSoT). `false` inverts the Claude-memory allow into a block. No brand-new
handler — the existing blocker "is perfect"; we make its memory stance explicit and configurable.

### Decision 3: Specialist message couples the block to progressive disclosure (USER-DIRECTED)

**Context**: a generic "wrong location" block teaches the agent nothing about the *right* home.
**Decision**: the Claude-memory block emits a dedicated message pointing at tracked project docs
and the progressive-disclosure model — making the block the on-ramp to the docs system.

### Decision 4: Default + opt-in

Default `allow_untracked_claude_memory: true` (today's behaviour). Enforcement activates only
when a project opts in by setting it `false`.

## Success Criteria

- [ ] One explicit config bool (`allow_untracked_claude_memory`) toggles the policy; default
  `true` leaves all current behaviour unchanged.
- [ ] With the policy active: `Write`/`Edit`/redirect to a Claude-memory `.md` path is **blocked**;
  reading is **allowed**.
- [ ] The block uses the **specialist** tracked-docs / progressive-disclosure message, not the
  generic markdown-location one.
- [ ] `optimal_config_checker` gives no contradictory "re-enable memory" advice under the policy.
- [ ] Guidance names the belt-and-braces tracked-docs model (rules + skills + links, SSoT,
  no `@`-imports).
- [ ] Full QA 13/13, daemon restart RUNNING, H-1 gate, acceptance tests pass.

## Risks & Mitigations

| Risk                                                               | Impact | Probability | Mitigation                                                                                      |
| ------------------------------------------------------------------ | ------ | ----------- | ----------------------------------------------------------------------------------------------- |
| Block false-positives on legit project files under a `memory/` dir | High   | Med         | Scope precisely to Claude-meta memory locations; acceptance tests for allow cases               |
| Memory writes bypass the Write tool (some internal path)           | High   | Low         | Phase 0.2 confirms; harness docs say memory uses the Write tool; redirect side-door also closed |
| Contradictory advice vs `optimal_config_checker`                   | Med    | High        | Phase 3 single "policy active" SSoT; suppress the re-enable nag                                 |
| Specialist message / generic message branch confusion              | Med    | Med         | Distinct, tested branches keyed on path-match + policy flag                                     |
| Progressive-disclosure scope balloons                              | Med    | High        | Phase 4 keeps the scaffolding skill optional / follow-up; block + guidance ship first           |

## Delivery & Milestones

- Phases 1–5 delivered at `dbcac37` (implementation), released at `9285093`
- Tag `v3.23.0` = `9ed4a5f`

## Notes & Updates

### 2026-06-19

- Plan scaffolded via the freshly-shipped `mkplan.bash` (Plan 00130 dogfood; counter 130→131).
- **Revised per user direction**: enforce by **blocking at the daemon layer** (reliable), not by
  trying to disable Claude memory (unreliable). Mechanism = new explicit
  `allow_untracked_claude_memory` bool on `markdown_organization` (default `true`); `false`
  blocks Claude-memory `.md` writes with a **specialist** message pointing to tracked project
  docs and **progressive disclosure as a first-class concept**. Reads stay allowed.
- Grounded: `markdown_organization` already allows Claude-memory paths (the inversion point);
  `optimal_config_checker` keys on `CLAUDE_CODE_DISABLE_MEMORY` and must be reconciled.
- Next: Phase 0 verification (read the allow-rule + memory path patterns), then TDD the option +
  block + specialist message.

### 2026-06-19 — Phases 1–4 implemented (TDD)

- **markdown_organization**: added `_allow_untracked_claude_memory` (default True), option-key
  constant `ALLOW_UNTRACKED_CLAUDE_MEMORY_OPTION`, helpers `_is_claude_memory_path`,
  `_bash_memory_write_target` (redirect/`tee` only — reads pass), `_claude_memory_block_target`
  (shared by matches()+handle()), and specialist `_deny_untracked_memory()`. `matches()` inverts
  the memory allow-rule + closes the bash side-door; `get_claude_md()` branches on the policy.
- **optimal_config_checker**: `_untracked_memory_forbidden()` reads the policy from the daemon
  config (fail-safe); `_check_auto_memory()` no longer nags to re-enable memory under the policy.
- Tests: +15 markdown policy tests, +4 optimal-config policy tests (all RED→GREEN). Full
  markdown+optimal suites: 220 passed. Daemon restart: RUNNING with new code.
- **Decisions**: Phase 4 scaffolding skill → follow-up plan (guidance ships now). Phase 6 dogfood
  (activate in THIS repo + migrate MEMORY.md) → deferred follow-up; this repo stays default `true`.
- Ships bundled with the Plan 00130 `mkplan.bash` work already on `main`.
