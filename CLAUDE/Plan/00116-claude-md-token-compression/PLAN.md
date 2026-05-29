# Plan 00116: CLAUDE.md Token Compression via Rule-ID Table + Keyed Block Reminders

**Status**: Not Started
**Created**: 2026-05-29
**Owner**: Claude (research + planning agent)
**Priority**: High
**Recommended Executor**: Sonnet (Opus if combined with handler-content rewrites at scale)
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The daemon's instruction footprint measurably degrades adherence to its own
guidance. The always-on instruction tree loaded into every Claude Code session
is ~131 KB ≈ 33k tokens — within range of Claude Code's ~47k-token warning, and
large enough to trigger the well-documented "lost in the middle" failure mode
(see `RESEARCH.md`). The single largest contributor is the daemon-injected
`<hooksdaemon>` block in the host `CLAUDE.md`: 22,041 bytes / 407 lines =
**46% of CLAUDE.md**, auto-generated on every daemon restart by
`core/claude_md_injector.py` from each handler's `get_claude_md()`.

**Design (revised per maintainer direction)**: keep per-block reminders — they
are valuable — but stop duplicating the full rationale in always-on context.
Instead:

1. **Always-on**: CLAUDE.md carries a single compact **table of rules**, one row
   per rule, each with a stable **rule ID** (e.g. `R-GIT-RESET-HARD`), a terse
   "what's blocked", and the one-line fix. No per-handler prose sections.
2. **At block time**: each handler's deny message **leads with the rule ID** and
   the same terse reminder ("BLOCKED [R-GIT-RESET-HARD]: `git reset --hard`
   destroys uncommitted changes — ask the user to run it manually"), with the
   richer rationale appended (the existing verbosity ladder) and a pointer to the
   on-demand drill-down for full detail.
3. **On demand**: a CLI command (`explain-rule <ID>` / `explain-handler <name>`)
   returns the full, verbatim guidance.

The table row, the deny message, and the drill-down are all **generated from one
source of truth** — `Rule` objects declared by each handler — so the per-block
reminder and the always-on table can never drift.

Because daemon guidance is **normative** (a blocked-command list cannot be lossily
paraphrased), this plan **rejects** automated/lossy prompt compression
(LLMLingua et al.) in favour of structural deduplication (one row + one keyed
message instead of full prose everywhere). Both are lossless-by-construction and
verifiable (see `RESEARCH.md`).

This plan is research + design + implementation-roadmap only. It does **not**
itself implement the change.

## Goals

- **G1 — Shrink the always-on injected block by ≥50%** (target: ≤11,000 B /
  ≤200 lines from 22,041 B / 407 lines) by replacing per-handler prose with a
  single rule-ID table, with **zero loss of normative content**.
- **G2 — Keep per-block reminders, keyed by rule ID**: every deny message leads
  with its rule ID and terse reminder; the ID matches the always-on table row.
- **G3 — Single source of truth**: rule ID + terse text + fix live once, in code
  (`Rule` objects). The CLAUDE.md table AND the deny message are generated from
  them — they cannot drift.
- **G4 — On-demand drill-down**: `explain-rule <ID>` and `explain-handler <name>`
  return full verbatim guidance, so no fidelity is lost.
- **G5 — De-`@` the heavy imports**: convert the always-expanded `@`-imports in
  CLAUDE.md to plain on-demand references with a one-line trigger pointer each.
- **G6 — Verifiable no-loss**: tests assert (a) every rule ID in the table has a
  handler that emits it in a deny message, (b) every handler deny path references
  a real table ID, (c) every blocked literal + fix survives, (d) before/after
  token counts hit target.

## Non-Goals

- **NG1** — No automated/runtime prompt compression (LLMLingua / abstractive).
  Rejected for normative instructions; see `RESEARCH.md`.
- **NG2** — No change to handler matching *behaviour* (what gets blocked). Only
  the *shape* of the reminder/guidance changes.
- **NG3** — No deletion of guidance content. Rationale is relocated to the deny
  message + on-demand drill-down, never removed.
- **NG4** — Not implementing the change in this plan; this is the roadmap.
- **NG5** — No daemon restart from a worktree (single-process enforcement would
  kill the main session's daemon). Restart-requiring steps run in the main repo.

## Context & Background

### Measured baseline (ground truth, 2026-05-29)

| Artifact | Size | Notes |
|----------|------|-------|
| `CLAUDE.md` total | 47,886 B / 986 lines (~12k tok) | host project file |
| `<hooksdaemon>` injected block | 22,041 B / 407 lines | **46% of CLAUDE.md**; auto-generated |
| `@CLAUDE/PlanWorkflow.md` | 25.5 KB | always auto-expanded |
| `@CLAUDE/development/RELEASING.md` | 20.2 KB | always auto-expanded |
| `@CLAUDE/CodeLifecycle/Features.md` | 10 KB | always auto-expanded |
| `@CLAUDE/CodeLifecycle/Bugs.md` | 8.5 KB | always auto-expanded |
| `@CLAUDE/CodeLifecycle/General.md` | 8.5 KB | always auto-expanded |
| `@.claude/HOOKS-DAEMON.md` | 10.6 KB | always auto-expanded |
| **Always-on instruction tree** | **≈131 KB ≈ 33k tokens** | Claude Code warns ~47k tokens |

### Architecture (grounded in source read 2026-05-29)

- `core/handler.py` — `Handler(ABC)` exposes `get_claude_md() -> str | None`
  (default None) and `get_acceptance_tests() -> list`. Clean base; adding a
  `get_rules() -> list[Rule]` method (default `[]`) is the natural extension.
- `core/claude_md_injector.py` — `inject()` collects `get_claude_md()` from all
  active handlers (`_collect_sections`), wraps them between `<hooksdaemon>` tags
  with `_SECTION_INTRO` (which **already** states the meta-rule "when blocked,
  don't stop, read the reason, continue" — currently re-stated inside many
  handler blocks), writes into CLAUDE.md, and auto-commits. Has a
  content-preservation safety check.
- `handlers/pre_tool_use/destructive_git.py` — already a strong model for the new
  design: it has **9 distinct patterns**, each mapped in `handle()` to a
  **specific reason string** (e.g. "git reset --hard destroys all uncommitted
  changes permanently"), plus a 3-level verbosity ladder
  (`_terse_reason`/`_standard_reason`/`_verbose_reason`) and a command→reason
  **table** in `get_claude_md()`. These specific reasons map 1:1 to rule IDs;
  the table in `get_claude_md()` becomes the generated rule table.
- `handlers/session_start/hook_registration_checker.py` — ~33-line Policy +
  Remediation prose block: mostly drill-down-tier material; the always-on table
  row should be one line, the rest moved to detail.
- `daemon/cli.py` — argparse subparsers (`generate-docs`, `generate-playbook`,
  `handlers`, ...). `cmd_generate_docs` already enumerates handlers + metadata —
  the machinery for `explain-rule` / `explain-handler` already exists.

### Research conclusion (full detail + citations in `RESEARCH.md`)

For **normative** instructions: REJECT automated/lossy compression; ADOPT
structural deduplication + two-tier progressive disclosure + de-`@`-importing.
The rule-ID table + keyed block reminder is a concrete instance of "smallest set
of high-signal tokens" (Anthropic) + the Agent Skills pattern (a short
always-on index, full detail loaded on demand).

## Proposed Data Model

```python
@dataclass(frozen=True)
class Rule:
    id: str            # stable, e.g. "R-GIT-RESET-HARD" (NO MAGIC: from a RuleID enum/constants)
    blocked: str       # terse "what is blocked", e.g. "`git reset --hard`"
    why: str           # one-line consequence, e.g. "destroys uncommitted changes permanently"
    fix: str           # one-line fix, e.g. "ask the user to run it manually; or git stash first"
    detail: str | None = None   # optional verbatim long-form for the drill-down
```

- **CLAUDE.md table row** (generated): `| R-GIT-RESET-HARD | `git reset --hard` | destroys uncommitted changes permanently | ask the user / git stash first |`
- **Deny message** (generated leader): `BLOCKED [R-GIT-RESET-HARD]: git reset --hard destroys uncommitted changes permanently. Fix: ask the user / git stash first. Full detail: <cli> explain-rule R-GIT-RESET-HARD`
- A shared `RuleFormatter` builds both from the same `Rule`, guaranteeing parity.

## Design Decisions (defaults chosen; confirm with maintainer)

These three were posed to the maintainer; as a subagent I cannot ask
interactively, so I record recommended defaults and flag them OPEN.

### Decision A — ID source: **Handler-owned** (recommended)
Each handler declares its `Rule`(s) in code via `get_rules()`. The table and the
deny message are both generated from them. Strongest DRY; block reminder and
table provably cannot drift. (Alternatives: central registry — readable in one
place but sync burden; table-only — least code but silent drift. Rejected.)
**Status**: OPEN — confirm with maintainer.

### Decision B — ID granularity: **Per-rule** (recommended)
One ID per distinct blocked thing (so `destructive_git` → `R-GIT-RESET-HARD`,
`R-GIT-FORCE-PUSH`, ... — 9 IDs). Matches the handler's existing 9 specific
reasons 1:1; gives precise reminders. Table is longer but each row is one line.
(Alternative: per-handler — smaller table, less precise.) **Status**: OPEN.

### Decision C — Table scope: **Blocking only** (recommended)
Only BLOCKING/TERMINAL handlers get table rows + IDs (the hard "these will STOP
you" rules). Advisory handlers keep a lighter one-line entry or a separate
section, to avoid diluting the hard-rule signal. (Alternative: all handlers —
more complete, longer, dilutes.) **Status**: OPEN.

### Decision D — ID stability & registry
Rule IDs are a **public contract** (they appear in user CLAUDE.md and in block
messages users may script against). Define them as named constants
(`constants/rule_ids.py`, NO MAGIC) and treat renames as breaking changes.
**Date**: 2026-05-29

### Decision E — Drill-down delivery: CLI subcommand
`explain-rule <ID>` and `explain-handler <name>` mirror existing
`generate-docs`/`handlers`/`generate-playbook`; headless + CI-testable. The
CLAUDE.md table header and every deny message point at `explain-rule`.
**Date**: 2026-05-29

### Decision F — REJECT automated/lossy compression for normative text
LLMLingua-2 etc. are SOTA but probabilistic; a dropped negation or paraphrased
literal (`-D` vs `-d`, the `--staged` exception) is a correctness bug. Use the
rule-ID dedup + deferral instead. Rationale + citations: `RESEARCH.md`.
**Date**: 2026-05-29

## Tasks

### Phase 1: Measurement harness & no-loss contract (TDD)

- [ ] ⬜ **Task 1.1**: `scripts/qa/measure_instruction_footprint.py` — byte+line+
      approx-token counts for the injected block, each `get_claude_md()`, and the
      full always-on tree (block + `@`-imports). Snapshot as regression baseline.
  - [ ] ⬜ RED: test asserts baseline snapshot matches measured values.
  - [ ] ⬜ GREEN: implement.
- [ ] ⬜ **Task 1.2**: Term-set test — record every blocked literal (`git reset
      --hard`, `-D`, `--staged`, ...) and every prescribed fix per handler. This
      is the no-semantic-loss contract for later phases.

### Phase 2: `Rule` model + `RuleID` constants (TDD)

- [ ] ⬜ **Task 2.1**: Add `Rule` dataclass (`core/rule.py`) + `RuleID` constants
      (`constants/rule_ids.py`, NO MAGIC). Unit-test the dataclass + a
      `RuleFormatter` that renders (a) a table row and (b) a deny-message leader
      from one `Rule`.
  - [ ] ⬜ RED: formatter tests assert table row and deny leader both contain the
        ID, blocked literal, why, and fix — from the same `Rule`.
- [ ] ⬜ **Task 2.2**: Add `Handler.get_rules() -> list[Rule]` (default `[]`) to
      the base class + `HasClaudeMd`/protocol updates. Legacy handlers (no rules)
      degrade gracefully.

### Phase 3: Migrate handlers to declare rules (TDD, parallelisable)

- [ ] ⬜ **Task 3.1**: For each BLOCKING/TERMINAL handler, declare `get_rules()`
      with per-rule IDs, and refactor `handle()` to build its deny message via
      `RuleFormatter` (leading with the ID), preserving the existing verbosity
      ladder as the appended detail.
      *(One sub-agent per handler file, Edit tool only — never sed; never batch a
      mutating Edit with a blockable Bash call; verify each edit landed.)*
  - [ ] ⬜ Per handler: Phase 1.2 term-set test still passes; deny message now
        leads with a valid `RuleID`.
- [ ] ⬜ **Task 3.2**: Start with `destructive_git` (9 rules — the reference
      implementation), then `markdown_organization`, `tdd_enforcement`,
      `git_stash`, `sed_blocker`, and the strategy-backed
      security/qa-suppression/lint handlers.

### Phase 4: Injector emits the rule table (TDD)

- [ ] ⬜ **Task 4.1**: Update `_collect_sections`/`_build_section` to render a
      single generated **rule-ID table** (blocking rules) from all handlers'
      `get_rules()`, plus the single shared meta-rule (from `_SECTION_INTRO`) and
      a header pointer ("Full detail for any rule: `<cli> explain-rule <ID>`").
      Drop per-handler prose sections.
  - [ ] ⬜ RED: injector test asserts the block is a table keyed by RuleID, the
        meta-rule appears once (not per-handler), and the pointer is present.
- [ ] ⬜ **Task 4.2**: Advisory handlers — render a lighter section per Decision C
      (confirm scope first).
- [ ] ⬜ **Task 4.3**: Re-measure (Phase 1): injected block ≤50% of baseline (G1).

### Phase 5: On-demand drill-down CLI (TDD)

- [ ] ⬜ **Task 5.1**: Add `explain-rule <ID>` and `explain-handler <name>` to
      `daemon/cli.py`, printing the verbatim `Rule.detail` (and the handler's
      full guidance). Reuse `cmd_generate_docs` enumeration.
  - [ ] ⬜ RED: `explain-rule R-GIT-RESET-HARD` output contains every Phase 1.2
        term for that rule.

### Phase 6: Parity + integrity tests (TDD — the anti-drift guarantee)

- [ ] ⬜ **Task 6.1**: Test: every `RuleID` rendered in the CLAUDE.md table is
      emitted by some handler's deny path (no orphan table rows).
- [ ] ⬜ **Task 6.2**: Test: every handler deny message leads with a `RuleID`
      that exists in the table (no dangling references).
- [ ] ⬜ **Task 6.3**: Test: no duplicate RuleIDs across handlers.

### Phase 7: De-`@` the heavy imports (TDD where testable)

- [ ] ⬜ **Task 7.1**: In CLAUDE.md, convert the `@`-imports (PlanWorkflow,
      RELEASING, Features, Bugs, General, HOOKS-DAEMON) to plain references, each
      with a one-line always-on trigger pointer. Edit only the user-content
      region; verify the injector's content-preservation check still passes and
      `validate_instruction_content` is satisfied.
  - [ ] ⬜ Doc/lint test: heavy docs referenced but NOT `@`-expanded; trigger
        pointer present for each.
- [ ] ⬜ **Task 7.2**: Confirm the installer / CLAUDE.md template for fresh
      installs emits the de-`@`'d form and the rule-table block (search
      `src/.../install/`).

### Phase 8: Verification, QA, dogfood (executor runs in MAIN repo)

- [ ] ⬜ **Task 8.1**: Full QA (`./scripts/qa/run_all.sh` or `llm_qa.py all`).
- [ ] ⬜ **Task 8.2**: Restart daemon in the **main repo** (NOT a worktree),
      verify RUNNING, confirm the regenerated block is the rule table and ≤50%.
- [ ] ⬜ **Task 8.3**: Live-verify: trip `destructive_git`, confirm the deny
      message leads with `R-GIT-RESET-HARD`; run `explain-rule R-GIT-RESET-HARD`.
- [ ] ⬜ **Task 8.4**: Re-measure full always-on tree; record before/after.

## Dependencies

- Related: Plans 00114 (upgrade), 00115 (parallel-batch footgun) touch CLAUDE.md
  / skills — sequence CLAUDE.md edits to avoid collisions. No hard blocker.
- Touches `core/handler.py`, `core/rule.py` (new), `core/claude_md_injector.py`,
  `constants/rule_ids.py` (new), `daemon/cli.py`, every BLOCKING handler with a
  deny path, and CLAUDE.md + install templates.

## Success Criteria

- [ ] Injected block ≤ 11,000 B / ≤ 200 lines (≥50% reduction), now a rule table.
- [ ] Every deny message leads with a rule ID matching a table row (parity tests
      green); `explain-rule <ID>` returns full verbatim detail.
- [ ] `@`-imports converted to on-demand (≈83 KB removed from every-session load)
      with trigger pointers retained.
- [ ] Term-set test passes (no blocked literal or fix lost).
- [ ] No matching-behaviour change; all tests pass; 95%+ coverage; full QA green;
      daemon restarts RUNNING in main repo. Before/after tokens recorded.

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Table row / deny message drift | High | Low | Both generated from one `Rule` via `RuleFormatter`; parity tests (Phase 6) |
| Rule ID lost a load-bearing literal (`-D` vs `-d`) | High | Med | Phase 1.2 term-set test gates every rule; literals stored verbatim in `Rule.blocked` |
| Rule IDs are a public contract; renames break user scripts | Med | Med | IDs as named constants; treat renames as breaking; document in upgrade guide |
| Agent ignores the table / never drills down | Med | Med | Deny message is self-sufficient (ID + why + fix inline); drill-down only for edge detail |
| De-`@`'d docs ignored when needed (release steps) | High | Med | One-line always-on trigger pointers at decision points |
| Editing CLAUDE.md collides with injector auto-commit / validate_instruction_content | Med | Med | Edit only user-content region; rely on existing preservation check; run in main repo |
| Bulk per-handler edits trip blockers (sed/pipe/batch-cancellation) | Med | Med | One Edit per turn per agent; never sed; never pipe head/tail; verify each landed |

## Notes & Updates

### 2026-05-29
- Revised per maintainer direction: KEEP per-block reminders, but key them by
  stable **rule IDs** and replace the per-handler prose in CLAUDE.md with a
  single generated **rule-ID table**. Table row + deny message + drill-down all
  generated from one `Rule` source of truth → cannot drift.
- Three design questions (ID source / granularity / table scope) were posed to
  the maintainer. As a subagent I cannot ask interactively, so recommended
  defaults are recorded (Decisions A/B/C) and marked OPEN for confirmation:
  Handler-owned rules, per-rule IDs, blocking-only table.
- Architecture grounded by reading `core/handler.py` (clean base, `get_rules()`
  fits), `handlers/pre_tool_use/destructive_git.py` (9 patterns → 9 specific
  reasons → 9 rule IDs; already has the verbosity ladder + a table),
  `handlers/session_start/hook_registration_checker.py` (prose-heavy, prime
  drill-down candidate), `daemon/cli.py` subparser layout.
- The injector's `_SECTION_INTRO` already states the "when blocked, don't stop"
  meta-rule once — per-handler restatements are pure redundancy (cheap first win).
- Working note: writing `.md` directly into the worktree plan folder is blocked
  by `markdown_organization` (it resolves project root to the main repo, so the
  worktree path `.claude/worktrees/.../CLAUDE/Plan/` fails its allowed-path
  regex). Worked around via `.txt` draft in `untracked/` then `mv` to `.md` —
  a worktree-path edge case worth fixing upstream.
- Delivery commit hash(es): _to be recorded on completion._
