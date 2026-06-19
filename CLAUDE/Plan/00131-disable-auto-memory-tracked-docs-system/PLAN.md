# Plan 00131: Disable Auto-Memory + Tracked-Docs Progressive Disclosure

**Status**: In Progress (Phase 0 — verification + design sign-off gate)
**Created**: 2026-06-19
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Claude Code's cross-session **auto-memory** writes unversioned, un-reviewed, per-checkout
knowledge into Claude meta files (e.g. `~/.claude/projects/<slug>/memory/MEMORY.md` and
individual fact files). For teams that want a single, reviewable, git-tracked source of
truth, this is a knowledge silo: it drifts from the repo, is invisible to teammates, and
bypasses code review. This plan adds a first-class way for a project to **declare that
auto-memory is disabled** and have the hooks daemon **enforce that policy**, while steering
all durable knowledge into **tracked repo docs** using Claude Code's progressive-disclosure
features (rules + skills + plain links), never untracked meta files.

The design is grounded in the reference guide
([gist a5921ecb](https://gist.github.com/edmondscommerce/a5921ecb5b096439a6e505716e3a6a0d)):
a "belt-and-braces" doc model — `.claude/rules/*.md` with `paths:` glob frontmatter
(deterministic, contextual loading) plus thin intent-triggered skills, each pointing at a
single-source-of-truth body; `@`-imports avoided (they re-inline rather than defer);
safety/orientation stays resident, everything else loads on demand. Phase F of that guide —
migrate memory into committed docs, then set the disable flag — is the concrete enforcement
this plan operationalises in the daemon.

This is deliberately **opt-in**: default behaviour is unchanged (auto-memory allowed). A
project activates enforcement via config. When enabled, the daemon (a) tries to disable
auto-memory at the Claude Code layer, (b) **blocks writes** to memory files (reading is
always allowed, so existing memory can be migrated), and (c) tells agents to put durable
knowledge in tracked docs.

## Goals

- Add a config switch by which a project declares **auto-memory disabled** (default: allowed).
- When disabled, the daemon **auto-remediates** the Claude Code memory setting (best effort)
  and reports what it changed — mirroring the existing settings-sync enforcement pattern.
- A PreToolUse **blocking** handler that denies `Write`/`Edit` (and bash redirects) to
  Claude memory files when the policy is active. **Reading memory files stays allowed.**
- Agent-facing guidance (`get_claude_md()`) that states memory is disabled and that durable
  knowledge belongs in tracked repo docs (`.claude/rules/`, `docs/`, `CLAUDE/`), with the
  migration requirement called out.
- Reconcile the existing `optimal_config_checker` auto-memory check so a project that has
  *chosen* to disable memory is not nagged that disabling it is "sub-optimal".
- (Deliverable B, scope TBD — see sign-off) Bake the progressive-disclosure doc-organisation
  workflow into the daemon as a skill so projects can migrate memory → tracked docs and build
  the belt-and-braces rule/skill structure repeatably.

## Non-Goals

- Removing or weakening auto-memory for projects that want it (default stays ON).
- Deleting anyone's existing memory files. The blocker prevents *new* writes; migration of
  existing content is a guided, human-confirmed step, not an automated deletion.
- Re-implementing Claude Code's settings system. We write the documented disable flag; we do
  not invent a parallel mechanism.
- Blocking *reads* of memory files (explicitly allowed, required for migration).

## Context & Background — verified mechanics (partial; completed in Phase 0)

- **`optimal_config_checker`** (`handlers/session_start/optimal_config_checker.py`) already
  has a `_check_memory()` that inspects the env var **`CLAUDE_CODE_DISABLE_MEMORY`** and today
  treats `=1` (memory disabled) as *sub-optimal*, advising `unset CLAUDE_CODE_DISABLE_MEMORY`.
  This handler's stance directly conflicts with the new policy and MUST be reconciled.
- **`markdown_organization`** already contains an explicit allow-rule for Claude Code memory
  writes (`~/.claude/projects/*/memory/*.md` and files outside the project root). The new
  blocker must take precedence when policy is active, and the two must not contradict.
- The harness's own memory instructions confirm auto-memory is written **via the `Write`
  tool** to `~/.claude/projects/<slug>/memory/` — i.e. memory writes ARE interceptable by a
  PreToolUse handler. (To be re-confirmed live in Phase 0.)
- **OPEN (Phase 0)**: the authoritative *disable* mechanism. Two candidates exist — the env
  var `CLAUDE_CODE_DISABLE_MEMORY=1` (daemon-referenced) and a settings key
  `autoMemoryEnabled: false` (per the gist). We must verify which one(s) Claude Code honours
  and which the daemon can durably set (e.g. an `env` block or top-level key in
  `.claude/settings.json`), per the gist's rule: *verify mechanics, do not assume*.

## Tasks

### Phase 0: Verification + Design Sign-Off (BLOCKING)

- [ ] ⬜ **Task 0.1**: Verify the authoritative auto-memory **disable** mechanism — env var
  vs `autoMemoryEnabled` settings key vs both — and exactly where it must be written
  (`~/.claude/settings.json` user-level vs project `.claude/settings.json`, `env` block vs
  top-level). Cite Claude Code docs AND a live test.
- [ ] ⬜ **Task 0.2**: Verify the exact **memory file path patterns** Claude Code writes
  (MEMORY.md + per-fact files; user-level `~/.claude/projects/*/memory/` and any ccy/project
  variants) and confirm those writes surface as interceptable `Write`/`Edit` tool calls.
- [ ] ⬜ **Task 0.3**: Inventory existing daemon touch-points (`optimal_config_checker`,
  `markdown_organization` allow-rule, `validate_instruction_content`) and decide the
  coordination/precedence model (DRY — one source of truth for "is memory policy active").
- [ ] ⬜ **Task 0.4**: Resolve the open scope decisions (see Technical Decisions) with the
  user: A-only vs A+B, dogfood-now vs later, config shape. **Gate: no handler code until
  signed off.**

### Phase 1: Config — memory policy (TDD)

- [ ] ⬜ **Task 1.1**: Add a `MemoryPolicyConfig` (mirroring `PlanWorkflowConfig`) with at
  least `disabled: bool = False` (default = auto-memory allowed). Wire it into `Config` and
  inject into policy-tagged handlers via the registry. Schema-validated.

### Phase 2: `memory_write_blocker` PreToolUse handler (TDD)

- [ ] ⬜ **Task 2.1**: RED/GREEN a blocking handler that, when policy is active, denies
  `Write`/`Edit` whose `file_path` is a Claude memory file, and denies bash redirects writing
  to those paths. Allow all reads. Precise path matching to avoid false positives on project
  files merely living under a `memory/` directory.
- [ ] ⬜ **Task 2.2**: `get_claude_md()` guidance — memory disabled; migrate durable
  knowledge into tracked docs; reads allowed. `get_acceptance_tests()` for block/allow cases.

### Phase 3: SessionStart enforcement + reconciliation (TDD)

- [ ] ⬜ **Task 3.1**: When policy is active, auto-remediate the verified disable mechanism
  (best-effort write) and emit a one-line advisory of what changed; silent when already
  disabled (matches the lean-SessionStart convention).
- [ ] ⬜ **Task 3.2**: Reconcile `optimal_config_checker._check_memory()` so a project with
  memory policy = disabled is NOT advised to re-enable memory (invert/suppress that check
  under the policy).

### Phase 4: Tracked-docs migration guidance (TDD)

- [ ] ⬜ **Task 4.1**: Document the migration requirement (memory → tracked docs) and the
  belt-and-braces target model in the daemon's guidance/skill surface; reference the gist
  principles (rules with `paths:`, thin skills, no `@`-imports, plain links, SSoT).

### Phase 5: Progressive-disclosure doc-organisation system (Deliverable B — scope TBD)

- [ ] ⬜ **Task 5.1**: (Pending sign-off) A skill that runs the gist workflow end-to-end:
  inventory docs + `@`-import audit, propose the rules/skills/links architecture, migrate
  memory into committed docs, set the disable flag, independent second-pass review. May be
  split into a dedicated follow-up plan if too large for this one.

### Phase 6: Dogfood (scope TBD — see sign-off)

- [ ] ⬜ **Task 6.1**: (Pending sign-off) Activate the policy in THIS repo and migrate the
  existing rich `MEMORY.md` content into tracked docs, then disable auto-memory here.

### Phase 7: Integration, QA, docs, release

- [ ] ⬜ **Task 7.1**: Register handlers in `.claude/hooks-daemon.yaml`, restart daemon
  (RUNNING), regenerate `.claude/HOOKS-DAEMON.md` + `<hooksdaemon>` block.
- [ ] ⬜ **Task 7.2**: Full QA 13/13, daemon-load verification, H-1 acceptance gate.
- [ ] ⬜ **Task 7.3**: Release (bundled with Plan 00130 mkplan work already on `main`).

## Technical Decisions (to confirm at Phase 0.4 sign-off)

### Decision 1: Scope — A-only vs A+B in this plan

**A** = memory disable + write-blocker + guidance (concrete, shippable). **B** = the full
progressive-disclosure doc-organisation skill (larger, gist Phases 0–5). Options: ship A in
this plan and spin B into a follow-up plan, OR carry both here. **Leaning**: A in this plan,
B as a referenced follow-up, to keep the release tight and the blocking feature shippable.

### Decision 2: Disable mechanism to write

Resolve in Phase 0.1. Whatever Claude Code actually honours (`CLAUDE_CODE_DISABLE_MEMORY=1`
via a settings `env` block, or `autoMemoryEnabled: false`). The daemon writes ONE verified
mechanism, into the tracked project `.claude/settings.json` so teammates inherit it.

### Decision 3: Dogfood now vs later

THIS repo uses auto-memory heavily. Migrating its `MEMORY.md` into tracked docs is a real
body of work. Options: dogfood in this plan (eat our own dog food, but larger), or ship the
feature first and migrate in a follow-up. **Leaning**: ship + migrate-later, unless the user
wants the repo converted now.

### Decision 4: Default + opt-in

Default `disabled: false` (auto-memory allowed) for backward compatibility. Enforcement only
activates when a project opts in. (Confirmed direction; listed for completeness.)

## Success Criteria

- [ ] A project can set one config value to declare auto-memory disabled.
- [ ] With the policy active: writing a memory file is **blocked**; reading one is **allowed**.
- [ ] SessionStart auto-remediates the verified disable flag and reports it; silent when
  already disabled; `optimal_config_checker` no longer nags under the policy.
- [ ] Guidance steers durable knowledge into tracked docs (rules/skills/links), per the gist.
- [ ] Default behaviour unchanged for projects that do not opt in.
- [ ] Full QA 13/13, daemon restart RUNNING, H-1 gate, acceptance tests pass.

## Risks & Mitigations

| Risk                                                             | Impact | Probability | Mitigation                                                           |
| ---------------------------------------------------------------- | ------ | ----------- | -------------------------------------------------------------------- |
| Wrong disable mechanism → feature is inert                       | High   | Med         | Phase 0.1 verifies via docs + live test before any code              |
| Memory writes not interceptable as tool calls                    | High   | Low         | Phase 0.2 confirms; harness docs say memory uses the Write tool      |
| Blocker false-positives on legitimate `memory/` project files    | Med    | Med         | Precise path scoping to Claude-meta locations only; acceptance tests |
| Conflict with `optimal_config_checker` / `markdown_organization` | Med    | High        | Phase 0.3 single-source "policy active" flag; explicit precedence    |
| Scope creep into a full docs-refactor tool                       | Med    | High        | Decision 1 fences B to a follow-up; Non-Goals                        |

## Notes & Updates

### 2026-06-19

- Plan scaffolded via the freshly-shipped `mkplan.bash` (Plan 00130 dogfood; counter 130→131).
- Grounded against the reference gist and a first pass over the daemon source: confirmed
  `optimal_config_checker._check_memory()` keys on `CLAUDE_CODE_DISABLE_MEMORY` (and currently
  treats disabling as sub-optimal — must reconcile), and `markdown_organization` already
  allows `~/.claude/projects/*/memory/*.md` writes (coordination/precedence point).
- Phase 0 verification + sign-off is the next gate; no handler code until the open scope
  decisions (Decisions 1–3) are confirmed.
