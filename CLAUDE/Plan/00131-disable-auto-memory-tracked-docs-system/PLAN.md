# Plan 00131: Block Untracked Claude Memory + Tracked-Docs Progressive Disclosure

**Status**: In Progress (Phase 0 — verification, then implement)
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

### Phase 0: Verification (BLOCKING)

- [ ] ⬜ **Task 0.1**: Read `markdown_organization`'s current Claude-memory allow-rule and the
  exact path patterns it matches; confirm the precise insertion point for the new bool and the
  specialist-message branch.
- [ ] ⬜ **Task 0.2**: Confirm the full set of **memory file path patterns** to cover
  (user-level `~/.claude/projects/*/memory/*.md`, ccy variant `.claude/ccy/.../memory/*.md`,
  any project-level memory) and that they all surface as `.md` `Write`/`Edit` calls. Scope
  precisely to Claude-meta memory locations — no false positives on project files that merely
  live under some `memory/` directory.
- [ ] ⬜ **Task 0.3**: Decide the config home + "policy active" SSoT consumed by both
  `markdown_organization` (the block) and `optimal_config_checker` (the reconciliation), so the
  two never give contradictory advice.

### Phase 1: `allow_untracked_claude_memory` option + block (TDD)

- [ ] ⬜ **Task 1.1**: Add the `allow_untracked_claude_memory: bool = True` option to
  `markdown_organization` config (schema-validated; default preserves current behaviour).
- [ ] ⬜ **Task 1.2**: RED/GREEN — when the option is `false`, `Write`/`Edit` to a Claude-memory
  `.md` path is **denied**; when `true`, it is allowed exactly as today. Reads unaffected.
- [ ] ⬜ **Task 1.3**: RED/GREEN — bash redirects writing to those paths are also denied under
  the policy (close the `cat > .../memory/x.md` side door), consistent with the tool-write block.

### Phase 2: Specialist message + progressive-disclosure guidance (TDD)

- [ ] ⬜ **Task 2.1**: RED/GREEN — the Claude-memory block emits the **specialist message**
  (document in tracked project docs; here is the progressive-disclosure approach), distinct
  from the generic disallowed-location message.
- [ ] ⬜ **Task 2.2**: Update `markdown_organization.get_claude_md()` (and the generated
  `<hooksdaemon>` block) so that, under the policy, the guidance names the tracked-docs target
  model: belt-and-braces `.claude/rules/*.md` (`paths:` globs) + thin skills + plain links, SSoT,
  **no `@`-imports**, reads-allowed-for-migration.

### Phase 3: Reconcile optimal_config_checker (TDD)

- [ ] ⬜ **Task 3.1**: When the policy is active, `optimal_config_checker` must NOT advise
  re-enabling memory (suppress/invert `_check_memory()`), so the agent never sees contradictory
  guidance ("disable it" vs "you disabled it, re-enable").

### Phase 4: Progressive disclosure as a first-class thing (scope per Phase 0.3)

- [ ] ⬜ **Task 4.1**: Establish the progressive-disclosure target model as durable daemon
  guidance/docs (the belt-and-braces model + migration path), referenced by the specialist
  message. Whether this also ships a *scaffolding skill* (inventory docs, `@`-import audit, build
  rules/skills) in THIS plan or a focused follow-up is decided here based on size.

### Phase 5: Integration, QA, docs, release

- [ ] ⬜ **Task 5.1**: Register/confirm config in `.claude/hooks-daemon.yaml`, restart daemon
  (RUNNING), regenerate `.claude/HOOKS-DAEMON.md` + `<hooksdaemon>` block.
- [ ] ⬜ **Task 5.2**: Full QA 13/13, daemon-load verification, H-1 acceptance gate, acceptance
  tests (block vs allow, specialist vs generic message).
- [ ] ⬜ **Task 5.3**: Release (may bundle with the Plan 00130 mkplan work already on `main`).

### Phase 6: Dogfood (decide during the plan)

- [ ] ⬜ **Task 6.1**: Optionally activate `allow_untracked_claude_memory: false` in THIS repo
  and migrate the existing rich `MEMORY.md` content into tracked docs (rules/docs/CLAUDE). Larger
  body of work; may be a follow-up so the feature release stays tight.

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
