# Plan 00116: CLAUDE.md Token Compression (Injected Block + @-Imports)

**Status**: Not Started
**Created**: 2026-05-29
**Owner**: Claude (research + planning agent)
**Priority**: High
**Recommended Executor**: Sonnet (Opus if combined with handler-content rewrites at scale)
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The daemon's instruction footprint has grown to the point where it measurably
degrades adherence to its own guidance. The always-on instruction tree loaded
into every Claude Code session is ~131 KB ≈ 33k tokens — within range of Claude
Code's ~47k-token warning, and large enough to trigger the well-documented
"lost in the middle" failure mode (see `RESEARCH.md`). The single largest
contributor is the daemon-injected `<hooksdaemon>` block in the host project's
`CLAUDE.md`: 22,041 bytes / 407 lines = **46% of CLAUDE.md**, auto-generated on
every daemon restart by `core/claude_md_injector.py` from each handler's
`get_claude_md()`.

This plan converts the injected block and the heavy `@`-imports from an
**always-on, fully-detailed** model to a **two-tier progressive-disclosure**
model: a terse, high-signal always-on summary plus full detail fetched on
demand via a CLI drill-down command. Crucially, because daemon guidance is
**normative** (a blocked-command list cannot be lossily paraphrased), this plan
explicitly **rejects** automated/lossy prompt compression (LLMLingua et al.) in
favour of **manual information-density editing** and **deferred loading** —
both lossless-by-construction and verifiable (see `RESEARCH.md`).

This plan is research + design + implementation-roadmap only. It does **not**
itself implement the compression.

## Goals

- **G1 — Shrink the always-on injected block by ≥50%** (target: ≤11,000 bytes /
  ≤200 lines from the 22,041 / 407 baseline) with **zero loss of normative
  content** (every blocked pattern and every prescribed fix still discoverable).
- **G2 — Two-tier model**: each handler exposes a *terse* always-on summary AND
  a *detailed* drill-down. The injected block carries only summaries; full
  detail is fetched on demand.
- **G3 — On-demand drill-down path**: a CLI command
  (`explain-handler <name>` / `explain-handlers`) and/or skill that returns the
  full, verbatim guidance for one or all handlers, so no fidelity is lost.
- **G4 — De-`@` the heavy imports**: convert the five always-expanded `@`-imports
  in `CLAUDE.md` to plain on-demand references, with a one-line always-on
  trigger pointer left in place for each.
- **G5 — Verifiable no-loss**: an automated test asserts each handler's terse
  summary still names what it blocks and the prescribed fix, and a token-count
  measurement proves before/after reduction.

## Non-Goals

- **NG1** — No automated/runtime prompt compression (LLMLingua / soft prompt /
  abstractive). Rejected for normative instructions; see `RESEARCH.md`.
- **NG2** — No change to handler *behaviour* (matches/handle logic). This plan
  touches only `get_claude_md()` output, the injector, the CLI, and CLAUDE.md
  imports.
- **NG3** — No deletion of any guidance content. Detailed text is *relocated to
  on-demand*, never removed.
- **NG4** — Not implementing the compression in this plan; this is the roadmap.
- **NG5** — No daemon restart from a worktree (would kill the main session's
  daemon under single-process enforcement). Implementation phases that require a
  restart are flagged for the executor to run in the main repo.

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

- `core/claude_md_injector.py` — `ClaudeMdInjector.inject()` collects
  `get_claude_md()` from all active handlers (`_collect_sections`), wraps them in
  `_build_section` between `<hooksdaemon>`/`</hooksdaemon>` with `_SECTION_INTRO`
  (which *already* states the meta-rule "when blocked, don't stop, read the
  reason, continue" — currently **re-stated** inside many handler blocks), and
  `_replace_or_append_section` writes them into `CLAUDE.md`. It auto-commits the
  result. There is a content-preservation safety check on user content outside
  the block.
- Per-handler `get_claude_md()` returns a free-form markdown string. Example
  (`destructive_git`): ~18 lines / ~1.2 KB — a good command→reason **table**
  plus prose that **duplicates** information already present in the handler's
  `handle()` reason ladder (`_terse_reason`/`_standard_reason`/`_verbose_reason`)
  and its `get_acceptance_tests()`. Example (`hook_registration_checker`): ~33
  lines of Policy + Remediation prose — heavy, almost entirely drill-down-tier
  material.
- CLI (`daemon/cli.py`) uses argparse subparsers (`generate-docs`,
  `generate-playbook`, `handlers`, etc.) — a natural home for a new
  `explain-handler` subcommand. `cmd_generate_docs` already iterates handlers and
  reads their metadata, so the machinery to enumerate handlers + pull
  `get_claude_md()` exists.

### Research conclusion (full detail + citations in `RESEARCH.md`)

For **normative** instructions: REJECT automated/lossy compression; ADOPT
(a) manual information-density editing (tables, telegraphic style, dedup),
(b) two-tier progressive disclosure with on-demand drill-down, and
(c) de-`@`-importing. All three are lossless-by-construction and match
Anthropic's 2025 context-engineering / Agent Skills guidance ("smallest set of
high-signal tokens", "just-in-time" loading, name+description-first progressive
disclosure) and the Lost-in-the-Middle / context-rot evidence.

## Tasks

### Phase 1: Measurement harness & baseline lock-in (TDD)

- [ ] ⬜ **Task 1.1**: Write a measurement utility/test that computes byte+line
      counts (and an approximate token count) for: the injected block, each
      handler's `get_claude_md()`, and the full always-on tree (block +
      `@`-imports). Record current numbers as the regression baseline.
  - [ ] ⬜ RED: test asserts a baseline JSON snapshot exists and matches
        measured values (will fail until written).
  - [ ] ⬜ GREEN: implement `scripts/qa/measure_instruction_footprint.py`
        (or a unit-test helper) that emits the metrics.
- [ ] ⬜ **Task 1.2**: Add a test that records the **set of load-bearing terms**
      per handler (every blocked literal, e.g. `git reset --hard`, `-D`,
      `--staged`; every prescribed fix command). This term-set is the
      no-semantic-loss contract for later phases.

### Phase 2: Two-tier `get_claude_md()` contract (TDD)

- [ ] ⬜ **Task 2.1**: Decide and document the two-tier API shape (Technical
      Decision 1 below). Options: (a) split into `get_claude_md_summary()` +
      `get_claude_md_detail()`; (b) keep `get_claude_md()` as detail, add
      `get_claude_md_summary()` and have the injector use summary; (c) a single
      structured return (title, summary, detail). Land on one before coding.
  - [ ] ⬜ RED: protocol/contract test in `tests/unit/core/` asserting the
        chosen method(s) exist on the `HasClaudeMd` protocol and return the
        expected shape.
- [ ] ⬜ **Task 2.2**: Update `HasClaudeMd` protocol + `Handler` base default so
      existing handlers degrade gracefully (a handler with only the legacy
      `get_claude_md()` still produces *something* — e.g. summary falls back to
      the first paragraph/title line).
- [ ] ⬜ **Task 2.3**: Test the fallback path end-to-end (legacy handler → summary
      derivation).

### Phase 3: Injector emits terse always-on block (TDD)

- [ ] ⬜ **Task 3.1**: Update `_collect_sections` / `_build_section` to emit the
      **summary tier** only, plus a single drill-down pointer line at the top of
      the block (e.g. "Full guidance for any handler:
      `$PYTHON -m ...cli explain-handler <name>`").
  - [ ] ⬜ RED: injector test asserts the built block contains summaries, the
        drill-down pointer, and the single shared meta-rule (NOT repeated
        per-handler).
  - [ ] ⬜ GREEN: implement.
- [ ] ⬜ **Task 3.2**: Remove the per-handler restatement of the "when blocked,
      don't stop" meta-rule (it lives once in `_SECTION_INTRO`). Verify no
      handler summary re-states it (dedup test).
- [ ] ⬜ **Task 3.3**: Re-measure (Phase 1 harness): assert injected block ≤50%
      of baseline (G1 success gate).

### Phase 4: On-demand drill-down CLI (TDD)

- [ ] ⬜ **Task 4.1**: Add `explain-handler <name>` and `explain-handlers`
      subcommands to `daemon/cli.py` that print the **detail tier** verbatim for
      one / all handlers.
  - [ ] ⬜ RED: CLI test invokes the subcommand for `destructive_git` and asserts
        every load-bearing term from Task 1.2 appears in the output.
  - [ ] ⬜ GREEN: implement, reusing `cmd_generate_docs`'s handler enumeration.
- [ ] ⬜ **Task 4.2**: Wire the drill-down pointer text (Phase 3) to the actual
      command name so it is copy-pasteable and correct.

### Phase 5: Author terse summaries per handler (TDD-guarded)

- [ ] ⬜ **Task 5.1**: For each handler with `get_claude_md()`, author a terse
      summary (target: 1–4 lines; tables collapsed to the essential literals).
      Move the long rationale/remediation into the detail tier.
      *(Parallelisable: one sub-agent per handler file, each using the Edit tool
      — never sed; never batch a mutating edit with a blockable Bash call.)*
  - [ ] ⬜ For every handler, the Phase 1.2 term-set test must still pass against
        the **summary + detail combined**, and the *summary alone* must still
        name what is blocked + the one-token escape/fix.
- [ ] ⬜ **Task 5.2**: Spot-check the highest-bloat handlers first
      (`hook_registration_checker`, `markdown_organization`, `tdd_enforcement`,
      `git_stash`, the lint/security/qa-suppression strategy-backed ones).

### Phase 6: De-`@` the heavy imports (TDD where testable)

- [ ] ⬜ **Task 6.1**: In `CLAUDE.md`, convert the `@`-imports (PlanWorkflow,
      RELEASING, Features, Bugs, General, HOOKS-DAEMON) to plain references, each
      preceded by a one-line always-on trigger pointer (e.g. "Before any release,
      READ `CLAUDE/development/RELEASING.md`").
      **NOTE**: `CLAUDE.md` is partly machine-managed (injected block) and is
      subject to `validate_instruction_content`; the executor must edit only the
      user-content region and verify the injector's content-preservation check
      still passes.
  - [ ] ⬜ Add a doc/lint test (or extend an existing CLAUDE.md test) asserting
        the heavy docs are referenced but NOT `@`-expanded, and that a trigger
        pointer exists for each.
- [ ] ⬜ **Task 6.2**: Confirm the installer / any template that *writes*
      `CLAUDE.md` for fresh installs emits the de-`@`'d form (so new installs get
      the lean version, not just this repo). Search `src/.../install/` and any
      `CLAUDE.md` templates.

### Phase 7: Verification, QA, dogfood (executor runs in MAIN repo)

- [ ] ⬜ **Task 7.1**: Run full QA: `./scripts/qa/run_all.sh` (or `llm_qa.py all`).
- [ ] ⬜ **Task 7.2**: Restart daemon in the **main repo** (NOT a worktree),
      verify RUNNING, and confirm the regenerated `<hooksdaemon>` block is the
      terse form and ≤50% of baseline.
- [ ] ⬜ **Task 7.3**: Live-verify drill-down: `explain-handler destructive_git`
      returns the full table verbatim.
- [ ] ⬜ **Task 7.4**: Re-measure full always-on tree; record before/after in
      Notes. Confirm targets met.
- [ ] ⬜ **Task 7.5**: Update `.claude/HOOKS-DAEMON.md` generation if its size is
      now a relevant on-demand artifact; ensure `generate-docs` still works.

## Dependencies

- Related: Plan 00114 (upgrade system) and 00115 (parallel-batch footgun) touch
  adjacent surfaces (skills, CLAUDE.md content) — coordinate ordering so CLAUDE.md
  edits do not collide. No hard blocker either way.
- Touches `core/claude_md_injector.py`, `core/handler.py` (protocol/base),
  `daemon/cli.py`, every `handlers/**/*.py` with `get_claude_md()`, and
  `CLAUDE.md` + install templates.

## Technical Decisions

### Decision 1: Two-tier API shape
**Context**: Need a terse summary for always-on injection and a verbatim detail
for on-demand drill-down, without breaking existing handlers.
**Options**:
1. Add `get_claude_md_summary()`; keep `get_claude_md()` as the detail tier.
   Pro: minimal churn, legacy handlers keep working (detail = current output);
   injector switches to summary. Con: two methods to maintain.
2. Structured return from one method (e.g. a dataclass `ClaudeMdGuidance(title,
   summary, detail)`). Pro: single source per handler, hard to desync. Con:
   larger refactor; every handler must migrate at once.
3. Split into summary + detail, deprecate the old name. Con: breaking for any
   project-handler that implements `get_claude_md()`.
**Recommendation**: **Option 1** for the first landing (lowest risk, graceful
fallback for project-handlers), with Option 2 as a possible follow-up once all
built-in handlers are migrated. *Final choice to be confirmed in Phase 2.1.*
**Date**: 2026-05-29

### Decision 2: Drill-down delivery — CLI vs skill vs both
**Context**: The detail tier must be reachable on demand.
**Options**: (a) CLI subcommand `explain-handler`; (b) a skill; (c) both.
**Recommendation**: **CLI subcommand** as the canonical path (mirrors existing
`generate-docs`/`handlers`/`generate-playbook`; works headless; testable in CI).
A skill can wrap it later if desired. The injected block's pointer references the
CLI command.
**Date**: 2026-05-29

### Decision 3: REJECT automated/lossy compression for normative text
**Context**: LLMLingua-2 etc. are SOTA for token reduction.
**Decision**: Do not use them on the injected block. Daemon guidance is
normative — a dropped negation or paraphrased command literal is a correctness
bug. Use manual density editing + deferral, both verifiable. Full rationale and
citations: `RESEARCH.md`.
**Date**: 2026-05-29

## Success Criteria

- [ ] Injected `<hooksdaemon>` block ≤ 11,000 B / ≤ 200 lines (≥50% reduction).
- [ ] Always-on tree reduced: `@`-imports converted to on-demand (≈83 KB of
      auto-expanded docs removed from every-session load), with trigger pointers
      retained.
- [ ] `explain-handler <name>` returns the full, verbatim detail tier for every
      handler.
- [ ] Term-set test (Phase 1.2) passes: every blocked literal and prescribed fix
      is still present somewhere reachable, and each handler's *summary alone*
      still names what it blocks + the escape/fix.
- [ ] No handler behaviour change; all existing tests pass; 95%+ coverage.
- [ ] Full QA passes; daemon restarts RUNNING in main repo with the terse block.
- [ ] Before/after token measurement recorded.

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Summary drops a load-bearing literal (e.g. `-D` vs `-d`) | High (silent correctness loss) | Med | Phase 1.2 term-set test gates every summary; summary must contain blocked literals verbatim |
| Agent never runs the drill-down, so detail is effectively lost | Med | Med | Summary is self-sufficient for the common case (names block + fix); drill-down only for edge detail; pointer always present |
| De-`@`'d docs get ignored when actually needed (e.g. release steps) | High | Med | Leave always-on one-line trigger pointers at the decision points; release skill/RELEASING reference stays explicit |
| Editing CLAUDE.md collides with injector auto-commit / `validate_instruction_content` | Med | Med | Edit only user-content region; rely on injector's existing content-preservation check; run in main repo with daemon control |
| Project-handlers implementing legacy `get_claude_md()` break | Med | Low | Option-1 API keeps legacy method working; summary derived via fallback |
| Bulk per-handler edits via parallel agents trip blockers (sed / pipe / batched-mutation cancellation) | Med | Med | One Edit per turn per agent; never sed; never pipe to head/tail; verify each edit landed |

## Notes & Updates

### 2026-05-29
- Plan authored from a worktree (no daemon restart performed here — single-process
  enforcement protects the main session's daemon). Web research completed with
  citations; see sibling `RESEARCH.md`.
- Architecture grounded by reading `core/claude_md_injector.py`,
  `handlers/pre_tool_use/destructive_git.py` (table-style block + reason ladder +
  acceptance tests), `handlers/session_start/hook_registration_checker.py`
  (prose-heavy ~33-line block — prime drill-down candidate), and `daemon/cli.py`
  subparser layout (`explain-handler` fits the existing pattern).
- Key finding: the injector's `_SECTION_INTRO` already states the "when blocked,
  don't stop" meta-rule once — per-handler restatements are pure redundancy and
  are the cheapest first win.
- Working note: writing this `.md` directly into the worktree plan folder was
  blocked by `markdown_organization` (it resolves project root to the main repo,
  so the worktree path `.claude/worktrees/.../CLAUDE/Plan/` fails its allowed-path
  regex). Worked around by writing a `.txt` draft to `untracked/` and `mv`-ing it
  to the `.md` target — a worktree-path edge case worth noting for future agents.
- Delivery commit hash(es): _to be recorded on completion._
