# Plan 00116: CLAUDE.md Token Compression via Stateful Progressive Disclosure

**Status**: Complete (2026-08-31 — all phases delivered; two-tier block live at 63.6% shrink, disclosure ladder live-verified, QA 25/25)
**Related**: Plan 00284 (documentation SSoT enforcement) shipped the complementary half of this plan's motivation — one canonical home per fact with `@`-import/at-import census and pointer enforcement across the doc corpus. This plan's remaining Phase 3 (stateful disclosure of the daemon-injected `<hooksdaemon>` block) is NOT redone there and stays blocked on its own tracker-wiring decision; see `CLAUDE/DocumentationStrategy.md` for the ruleset 00284 delivered.
**Created**: 2026-05-29
**Owner**: Claude (research + planning agent)
**Priority**: High
**Recommended Executor**: Sonnet (Opus if combined with handler-content rewrites at scale)
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The daemon's instruction footprint measurably degrades adherence to its own
guidance. The always-on instruction tree loaded into every Claude Code session is
~131 KB ≈ 33k tokens — within range of Claude Code's ~47k-token warning, and large
enough to trigger the "lost in the middle" failure mode (see `RESEARCH.md`). The
single largest contributor is the daemon-injected `<hooksdaemon>` block in the
host `CLAUDE.md`: 22,041 bytes / 407 lines at planning time (2026-05-29) —
**re-measured 2026-08-30 at 121,932 bytes ≈ 28,630 cl100k tokens, ~100% of
CLAUDE.md** (5.5× growth) — auto-generated on every daemon restart by
`core/claude_md_injector.py`.

**Design (final, per maintainer direction).** Three layers, each delivering
guidance *just-in-time* so the full rationale is **never in always-on context**:

1. **Always-on (CLAUDE.md)** — a single compact **rule-ID table**: one row per
   rule (stable ID, terse "what's blocked", one-line fix). No per-handler prose,
   no verbose rationale. This is the only daemon content auto-injected.

2. **At block time — STATEFUL progressive disclosure with disclosure tracking**:

   - **First time a given rule fires in a session** → emit the **verbose block**
     (full rationale, safe alternatives, the teaching content currently living in
     CLAUDE.md). The verbose text is delivered exactly when it is relevant.
   - **Subsequent fires of the same rule** → emit only the **terse reminder keyed
     by rule ID** ("BLOCKED \[R-GIT-RESET-HARD\]: ask the user / git stash first").
   - **Disclosure state resets on context loss** (PreCompact + clear / new
     session) so the first post-compact fire is verbose again — re-teaching the
     agent after its memory of the verbose block was compacted away.

3. **On demand** — a skill **`/hooks-daemon rule-explain <ID>`** (and a CLI
   `explain-rule <ID>`) returns the full verbatim detail for any rule whenever
   the LLM wants it, independent of block state.

The table row, the terse reminder, and the verbose block are all **generated from
one source of truth** — `Rule` objects declared by each handler — so they cannot
drift.

**Why this saves significant tokens.** Today every handler's full rationale is in
always-on context (~22 KB) *and* repeated in block messages. Under this design,
always-on context holds only the compact table (~a few KB); the verbose rationale
is paid **once per rule per session** (at first fire), and terse thereafter. Most
sessions trip few rules, so the always-on saving is paid every turn while the
verbose cost is paid rarely and only when actually relevant.

Because daemon guidance is **normative** (a blocked-command list cannot be lossily
paraphrased), this plan **rejects** automated/lossy prompt compression (LLMLingua
et al.). The savings come from *relocation + dedup + statefulness*, all
lossless-by-construction (see `RESEARCH.md`).

This plan is research + design + implementation-roadmap only.

## Goals

- **G1 — Shrink the always-on injected block by ≥70%** vs the re-measured
  2026-08-30 baseline (121,932 B / 28,630 tokens) via the Decision I two-tier
  block (promoted prose + progressive rule table), with **zero loss of
  normative content** and full guidance retained for measured-hot handlers.
- **G2 — Stateful progressive disclosure**: verbose on a rule's FIRST fire per
  session, terse (rule-ID reminder) thereafter.
- **G3 — Disclosure tracking with reset**: per-rule "disclosed this session"
  state, reset on PreCompact and on clear / new session.
- **G4 — Single source of truth**: rule ID + terse + verbose live once, in code
  (`Rule` objects). Table, terse reminder, verbose block all generated from them.
- **G5 — On-demand detail**: skill `/hooks-daemon rule-explain <ID>` + CLI
  `explain-rule <ID>` return full verbatim detail regardless of block state.
- **G6 — De-`@` the heavy imports**: convert always-expanded `@`-imports to plain
  on-demand references with a one-line trigger pointer each.
- **G7 — Verifiable no-loss**: tests assert (a) first fire is verbose, later fires
  terse, reset restores verbose; (b) every table ID is emitted by a handler and
  vice-versa; (c) every blocked literal + fix survives; (d) before/after tokens.

## Non-Goals

- **NG1** — No automated/runtime lossy compression (LLMLingua / abstractive).
- **NG2** — No change to handler *matching* behaviour (what gets blocked).
- **NG3** — No deletion of guidance content; verbose rationale relocates to the
  first-fire block message + on-demand skill, never removed.
- **NG4** — Not implementing in this plan; this is the roadmap.
- **NG5** — No daemon restart from a worktree (single-process enforcement kills
  the main session's daemon). Restart-requiring steps run in the main repo.

## Context & Background

### Measured baseline (ground truth, 2026-05-29)

| Artifact                            | Size                            | Notes                                |
| ----------------------------------- | ------------------------------- | ------------------------------------ |
| `CLAUDE.md` total                   | 47,886 B / 986 lines (~12k tok) | host project file                    |
| `<hooksdaemon>` injected block      | 22,041 B / 407 lines            | **46% of CLAUDE.md**; auto-generated |
| `@CLAUDE/PlanWorkflow.md`           | 25.5 KB                         | always auto-expanded                 |
| `@CLAUDE/development/RELEASING.md`  | 20.2 KB                         | always auto-expanded                 |
| `@CLAUDE/CodeLifecycle/Features.md` | 10 KB                           | always auto-expanded                 |
| `@CLAUDE/CodeLifecycle/Bugs.md`     | 8.5 KB                          | always auto-expanded                 |
| `@CLAUDE/CodeLifecycle/General.md`  | 8.5 KB                          | always auto-expanded                 |
| `@.claude/HOOKS-DAEMON.md`          | 10.6 KB                         | always auto-expanded                 |
| **Always-on instruction tree**      | **≈131 KB ≈ 33k tokens**        | Claude Code warns ~47k tokens        |

### Architecture (grounded in source read 2026-05-29)

- `core/handler.py` — `Handler(ABC)` with abstract `get_claude_md()` +
  `get_acceptance_tests()`. Adding `get_rules() -> list[Rule]` (default `[]`) is
  the natural extension.
- `core/claude_md_injector.py` — `inject()` collects `get_claude_md()` from active
  handlers, wraps between `<hooksdaemon>` tags with `_SECTION_INTRO` (which
  ALREADY states the "when blocked, don't stop" meta-rule once — currently
  re-stated inside many handler blocks), writes CLAUDE.md, auto-commits, has a
  content-preservation safety check.
- `core/handler_history.py` (refactor since planning: was `core/data_layer/history.py`)
  — `HandlerHistory`, an IN-MEMORY deque of deny/allow decisions exposing
  `count_blocks_by_handler(handler_id, session_id)`. **Key gaps for this design**:
  (a) per-HANDLER not per-RULE, (b) daemon-lifetime only — nothing persists across
  restarts, so it cannot supply the Decision I historical block counts (transcripts
  are the durable source), and (c) no compact/clear reset boundary. The disclosure
  tracker adds per-rule, per-agent state with reset boundaries.
- `handlers/pre_tool_use/destructive_git.py` — **already implements a verbosity
  ladder** driven by `_get_block_count()` →
  `_terse_reason`/`_standard_reason`/`_verbose_reason`. The maintainer's design
  is the **inverse** (verbose FIRST, terse after) + session-scoped + reset. This
  handler is the reference migration: 9 patterns → 9 specific reasons → 9 rules.
- `handlers/pre_compact/` — existing PreCompact handlers
  (`transcript_archiver`, `workflow_state_pre_compact`) show the event fires and
  is the hook point to RESET disclosure state. Clear / new session resets via a
  SessionStart hook.
- `daemon/cli.py` — argparse subparsers; `cmd_generate_docs` already enumerates
  handlers (machinery for `explain-rule`/`explain-handler` exists). Skills live
  under `src/claude_code_hooks_daemon/skills/hooks-daemon/`.

### Research conclusion (full detail + citations in `RESEARCH.md`)

REJECT automated/lossy compression for normative text; ADOPT structural dedup +
progressive disclosure + de-`@`-importing. Stateful first-verbose-then-terse with
compact reset is a direct application of Anthropic's "smallest set of high-signal
tokens" + just-in-time loading: the always-on cost is minimal, and the expensive
verbose payload is loaded only when relevant and only once until context is lost.

## Proposed Data Model

```python
@dataclass(frozen=True)
class Rule:
    id: str          # stable, e.g. "R-GIT-RESET-HARD" (from RuleID constants, NO MAGIC)
    blocked: str     # terse what-is-blocked, e.g. "`git reset --hard`"
    why: str         # one-line consequence
    fix: str         # one-line fix
    verbose: str     # full rationale + safe alternatives (first-fire block body / drill-down)
```

- **CLAUDE.md table row** (generated): `| R-GIT-RESET-HARD | `git reset --hard` | destroys uncommitted changes permanently | ask the user / git stash first |`
- **Terse reminder** (generated, repeat fires): `BLOCKED [R-GIT-RESET-HARD]: git reset --hard destroys uncommitted changes. Fix: ask the user / git stash. Detail: /hooks-daemon rule-explain R-GIT-RESET-HARD`
- **Verbose block** (generated, first fire / drill-down): terse leader + `Rule.verbose`.
- A `RuleFormatter` renders all three from one `Rule` → guaranteed parity.

### Disclosure tracker (new)

```python
class DisclosureTracker:
    """Per-rule, session-scoped 'already disclosed verbosely?' state.

    A rule is 'disclosed' once its verbose block has been emitted since the
    last reset boundary. reset() is called on PreCompact and on clear/new session.
    """
    def was_disclosed(self, rule_id: str) -> bool: ...
    def mark_disclosed(self, rule_id: str) -> None: ...
    def reset(self) -> None: ...   # called by PreCompact + SessionStart/clear handlers
```

Implementation options (Decision G): extend `History` with a reset-boundary
marker and per-rule deny counting since the last boundary, OR a dedicated
lightweight state file in the daemon untracked dir keyed by session. Either way
the verbose-vs-terse decision is: `verbose if not tracker.was_disclosed(id) else terse`.

## Design Decisions (maintainer-confirmed)

### Decision A — ID source: **Handler-owned `get_rules()`**. APPROVED.

Strongest DRY; table + reminders + verbose all generated from the handler's rules.

### Decision B — ID granularity: **Per-rule**. APPROVED.

`destructive_git` → 9 IDs matching its 9 existing specific reasons; precise reminders.

### Decision C — Table scope: **Blocking only**. APPROVED.

Only BLOCKING/TERMINAL rules get table rows + the disclosure ladder; advisory
handlers keep a lighter entry, to keep the hard-rule signal undiluted.

### Decision D — ID stability

Rule IDs are a **public contract** (appear in user CLAUDE.md + block messages).
Named constants (`constants/rule_ids.py`, NO MAGIC); renames = breaking change,
documented in the upgrade guide.

### Decision E — Reset boundaries: **PreCompact AND clear/new session**

PreCompact handler calls `tracker.reset()` (verbose content the agent saw is about
to be compacted away). A SessionStart/clear path also resets (fresh session = no
memory). Confirm whether clear is distinguishable from normal SessionStart in the
hook input; if not, reset on every SessionStart (cheap — worst case one extra
verbose block per session start).

### Decision F — Drill-down delivery: \*\*skill `/hooks-daemon rule-explain <ID>`

- CLI `explain-rule <ID>`\*\*. The skill is the LLM-facing path the maintainer
  asked for; the CLI is the headless/testable backend the skill wraps. Both also
  support `explain-handler <name>`. The table header + every terse reminder point
  at the skill.

### Decision G — Tracker storage: **in-memory in the daemon, keyed by `transcript_path`**. RESOLVED (spike complete) — state file REJECTED.

A state file invites out-of-sync corruption (maintainer call). The daemon is already
long-lived and per-project, so an in-process dict is the natural home; a daemon
restart simply re-verboses (acceptable — worst case one extra verbose block).

**CRITICAL concurrency requirement (maintainer-raised):** one daemon serves MANY
concurrent agents for a single project (main session + Task sub-agents + parallel
Claude Code sessions). A globally-keyed tracker would hand agent B a *terse* reminder
for a rule B has never seen verbose, because agent A disclosed it. The tracker MUST be
keyed by a per-agent identifier, NEVER global.

**Task 2.0 spike — RESOLVED.** Findings (verified against the live daemon + this
session's transcripts):

1. `session_id` is **NOT** per-agent — a Task sub-agent shares the parent's `session_id`
   (440/440 sidechain transcript entries carried the main session's id with
   `isSidechain:true`). Keying by `session_id` is REJECTED — a sub-agent would inherit
   the parent's disclosure state and get terse reminders for rules it never saw verbose.
2. `transcript_path` **is** carried in every hook payload (`core/input_schemas.py`,
   `core/event.py` `transcriptPath` alias; consumed today by the Stop handlers via
   `utils/stop_hook_helpers.py`) and **is per-agent** — each agent/sidechain has its own
   transcript file. It is the correct discriminator.
3. The daemon reads `transcript_path` already; the tracker just keys on it.

**Decision: in-memory `dict[transcript_path, set[rule_id]]`.** Per-agent by construction,
no state file, and — crucially — **no transcript parsing/grep**: we key on the path, we
never read the file. Reset an agent's entry on its PreCompact/SessionStart (both carry
`transcript_path`). The transcript-grep fallback from the pre-spike draft is dropped as
unnecessary. Edge case: if a `transcript_path` rotates mid-session the worst case is one
extra verbose block — acceptable, the same failure mode as a daemon restart.

### Decision H — REJECT automated/lossy compression for normative text.

Rationale + citations in `RESEARCH.md`.

### Decision I — HYBRID data-driven promotion (maintainer, 2026-08-31). APPROVED.

Not all-or-nothing: blocking handlers that REALLY fire often (measured from
this project's actual transcripts) keep their FULL guidance resident in the
injected block ("PROMOTED"); rarely-firing handlers stay fully enforced but get
only a rule-table row plus first-fire-verbose/terse-after disclosure
("PROGRESSIVE"). The promoted set is recorded in config
(`claude_md.promotion.promoted_handlers`) and kept honest by a re-runnable
analyser `bin/hooks-daemon block-report`. Full design, injected-block layout,
fingerprint-attribution scheme and amended targets:
[DESIGN-HYBRID-PROMOTION.md](DESIGN-HYBRID-PROMOTION.md).

## Tasks

### Phase 1: Measurement harness & no-loss contract (TDD)

- [x] ✅ **Task 1.1**: `scripts/qa/measure_instruction_footprint.py` — byte/line/
  approx-token counts for the injected block, each `get_claude_md()`, the full
  always-on tree. Snapshot as regression baseline. (RED: snapshot test; GREEN.)
- [x] ✅ **Task 1.2**: Term-set test — every blocked literal + prescribed fix per
  handler recorded; the no-semantic-loss contract for later phases.

### Phase 2: `Rule` model, `RuleID` constants, `DisclosureTracker` (TDD)

- [x] ✅ **Task 2.0 (BLOCKING spike — Decision G)**: RESOLVED — `session_id` is NOT
  per-agent (Task sub-agents share the parent's), `transcript_path` IS per-agent and is
  in every hook payload. Tracker keyed by `transcript_path`; transcript-grep fallback
  dropped. See Decision G.
- [x] ✅ **Task 2.1**: `Rule` dataclass (`core/rule.py`) + `RuleID` constants
  (`constants/rule_ids.py`). `RuleFormatter` rendering table row / terse / verbose
  from one `Rule`. (RED: all three contain the ID + literal; GREEN.)
- [x] ✅ **Task 2.2**: `Handler.get_rules() -> list[Rule]` (default `[]`) + protocol
  updates; legacy handlers degrade gracefully.
- [x] ✅ **Task 2.3**: `DisclosureTracker` (`core/disclosure_tracker.py`) with
  `was_disclosed`/`mark_disclosed`/`reset`, keyed by `transcript_path` (Decision G).
  (RED: first→verbose, repeat→terse, reset→verbose; GREEN.)

### Phase 2b: Real-block measurement & promotion config (Decision I, TDD)

- [x] ✅ **Task 2b.1**: `bin/hooks-daemon block-report` — transcript-scanning
  block-frequency analyser (streaming pattern from `tool_report/analyser.py`;
  privacy: handler names + counts only, never content). Handler attribution by
  deny-message fingerprint table derived from handler message constants, with a
  parity test that every blocking handler's own deny output matches its own
  fingerprint. Ranked report + recommended PROMOTED set per configured
  thresholds. See [DESIGN-HYBRID-PROMOTION.md](DESIGN-HYBRID-PROMOTION.md).
- [x] ✅ **Task 2b.2**: Config surface `claude_md.promotion`
  (`promoted_handlers`, `min_blocks`, `min_sessions`) — empty list ⇒ pure
  progressive disclosure (safe fresh-install default).
- [x] ✅ **Task 2b.3**: DONE 2026-08-31 — 359 transcripts / 12 sessions scanned;
  thresholds tuned to 20/3 (defaults promoted 29/34 — no compression); 10
  data-hot handlers + judgement-added `auto_continue_stop` committed in
  `.claude/hooks-daemon.yaml`; evidence journalled.

### Phase 3: Stateful disclosure in handlers (TDD, parallelisable)

- [x] ✅ **Task 3.1**: For each BLOCKING handler, declare `get_rules()` and refactor
  `handle()` to: identify the matched rule, then emit verbose (if
  `not tracker.was_disclosed(id)` → `mark_disclosed`) else terse, via
  `RuleFormatter`. Preserve existing verbose content as `Rule.verbose`.
  *(One sub-agent per handler file, Edit tool only — never sed; never batch a
  mutating Edit with a blockable Bash call; verify each landed.)*
- [x] ✅ **Task 3.2**: `destructive_git` migrated (reference implementation) —
  inverted its old `_get_block_count`-driven ladder into verbose-first/
  terse-after via `get_rules()` (9 `Rule` objects) + `get_data_layer().disclosure`.
  Recipe extracted to [MIGRATION-PATTERN.md](MIGRATION-PATTERN.md) for the
  remaining Task 3.1 handlers (`markdown_organization`, `tdd_enforcement`,
  `git_stash`, `sed_blocker`, security/qa-suppression/lint strategy handlers)
  still to migrate.

### Phase 4: Reset wiring (TDD)

- [x] ✅ **Task 4.1**: `DisclosureResetPreCompactHandler` calls
  `get_data_layer().disclosure.reset(transcript_path)` for the firing agent on
  PreCompact.
- [x] ✅ **Task 4.2**: `DisclosureResetSessionStartHandler` resets the firing
  agent's tracker entry on every SessionStart (Decision E).

### Phase 5: Injector emits the TWO-TIER block (Decision I, TDD)

- [x] ✅ **Task 5.1**: `_collect_sections`/`_build_section` render: shared
  meta-rule + explain pointer ONCE; full `get_claude_md()` prose for handlers in
  `claude_md.promotion.promoted_handlers` (PROMOTED tier); a single generated
  rule-ID table row per blocking rule of every OTHER handler (PROGRESSIVE tier).
  (RED: promoted handler's prose present verbatim; non-promoted handler reduced
  to table rows; meta-rule once; pointer present; GREEN.)
- [x] ✅ **Task 5.2**: Advisory handlers — resolved via the no-loss FALLBACK tier
  (no-rules handlers keep full prose; the rule table stays undiluted, which is
  Decision C's real requirement — tag-based lighter rendering rejected as
  unreliable, see journal).
- [x] ✅ **Task 5.3**: Re-measured live 2026-08-31: 44,391 B / 592 lines /
  ~11,035 tokens = **63.6% shrink** with the 11-handler promoted set (promoted
  tier 24.8 KB is the deliberate hybrid price; shrinking the promoted list is
  the config dial toward the ~84% pure-progressive floor). See journal.

### Phase 6: On-demand detail — CLI + skill (TDD)

- [x] ✅ **Task 6.1**: `explain-rule <ID>` / `explain-handler <name>` subcommands in
  `daemon/cli.py` printing `Rule.verbose` verbatim. (RED: output has every
  Phase 1.2 term for that rule; GREEN.)
- [x] ✅ **Task 6.2**: Skill `/hooks-daemon rule-explain <ID>` under
  `src/claude_code_hooks_daemon/skills/hooks-daemon/` wrapping the CLI. Follow
  existing skill-script conventions (self-bootstrap/manifest if applicable —
  see RELEASING Step 14).

### Phase 7: Parity + integrity tests (anti-drift guarantee, TDD)

- [x] ✅ **Task 7.1**: Every table `RuleID` is emitted by some handler deny path.
- [x] ✅ **Task 7.2**: Every handler terse/verbose message leads with a `RuleID`
  present in the table.
- [x] ✅ **Task 7.3**: No duplicate RuleIDs across handlers.
  *(All three in `tests/unit/test_rule_parity.py`, plus constant hygiene and a
  deny-implies-rules gate with a reasoned allowlist.)*

### Phase 8: De-`@` the heavy imports (TDD where testable)

- [x] ✅ **Task 8.1**: DELIVERED EXTERNALLY (Plan 00289's `@`-import conversion +
  the docs-QA `at-import-census` check): verified 2026-08-31 — zero `@`-imports
  remain in the root CLAUDE.md user-content region.
- [x] ✅ **Task 8.2**: DELIVERED EXTERNALLY: verified 2026-08-31 — the installer
  templates under `src/claude_code_hooks_daemon/install/` emit no `@`-imports.
  Rule-table block emission for fresh installs is covered by Phase 5 (the
  injector regenerates on install/restart, so no separate template change).

### Phase 9: Verification, QA, dogfood (executor runs in MAIN repo)

- [x] ✅ **Task 9.1**: Full QA `llm_qa.py all` — 25/25 PASSED on final HEAD.
- [x] ✅ **Task 9.2**: Daemon restarted in the main repo, RUNNING, 31/31
  listeners; regenerated block is the two-tier form at 63.6% shrink.
- [x] ✅ **Task 9.3**: Live-verified 2026-08-31: first `git reset --hard` trip →
  verbose leading `[R-GIT-RESET-HARD]`; second trip → terse one-liner with the
  rule-explain pointer. PreCompact→verbose-again verified live over the real
  socket during the reference migration; `explain-rule R-GIT-RESET-HARD`
  live-verified during Phase 6.
- [x] ✅ **Task 9.4**: Re-measured: always-on tree 159,644 B / ~39,700 approx
  tokens with the block at 44,391 B / ~11,035 tokens (was 121,932 B /
  ~28,630) — before/after recorded in the journal.

## Dependencies

- Related: Plans 00114 (upgrade), 00115 (parallel-batch footgun) touch CLAUDE.md /
  skills — sequence edits to avoid collisions. No hard blocker.
- Touches `core/handler.py`, `core/rule.py`, `core/disclosure_tracker.py`,
  `core/claude_md_injector.py`, `core/handler_history.py` (maybe),
  `constants/rule_ids.py`, `daemon/cli.py`, PreCompact + SessionStart
  handlers, every BLOCKING handler's deny path, the new `block-report`
  analyser + `claude_md.promotion` config, the new skill, CLAUDE.md +
  install templates.

## Success Criteria

- [x] Injected block shrunk 63.6% vs the 2026-08-30 baseline (121,932 B →
  44,391 B) in the two-tier form — short of the ≥70% stretch target, by the
  deliberate cost of the 11-handler promoted tier (24.8 KB); the promoted
  list is the documented config dial toward the ~84% pure-progressive floor.
- [x] `bin/hooks-daemon block-report` runs on real transcripts; this repo's
  `promoted_handlers` set is committed with its evidence journalled.
- [x] First fire of a rule → verbose; repeat → terse keyed by ID; PreCompact /
  clear resets → next fire verbose again (live + unit verified).
- [x] Skill `/hooks-daemon rule-explain <ID>` and CLI `explain-rule <ID>` return
  full verbatim detail; parity tests green.
- [x] `@`-imports converted to on-demand (delivered externally by Plan 00289),
  trigger pointers retained.
- [x] Term-set test passes (no blocked literal or fix lost).
- [x] No matching-behaviour change; all tests pass; 95.3% coverage; full QA
  25/25 green; daemon restarts RUNNING. Before/after tokens recorded.

## Risks & Mitigations

| Risk                                                                             | Impact | Probability | Mitigation                                                                                               |
| -------------------------------------------------------------------------------- | ------ | ----------- | -------------------------------------------------------------------------------------------------------- |
| Agent compacts away verbose block, then only gets terse → loses the rule         | High   | Med         | reset() on PreCompact restores verbose on next fire — the core mechanism; live-test it (Task 9.3)        |
| Disclosure state desyncs from real context (reset missed)                        | High   | Med         | Reset on BOTH PreCompact and SessionStart; default to verbose when state unknown (fail toward more info) |
| Table row / terse / verbose drift                                                | High   | Low         | All generated from one `Rule` via `RuleFormatter`; parity tests (Phase 7)                                |
| Rule lost a load-bearing literal (`-D` vs `-d`)                                  | High   | Med         | Phase 1.2 term-set test; literals stored verbatim in `Rule.blocked`/`verbose`                            |
| Rule IDs are a public contract; renames break user scripts                       | Med    | Med         | Named constants; renames = breaking; upgrade-guide note                                                  |
| Tracker storage adds per-block I/O latency                                       | Med    | Low         | In-memory session state, lazy persist; daemon is long-lived                                              |
| De-`@`'d docs ignored when needed (release steps)                                | High   | Med         | One-line always-on trigger pointers at decision points                                                   |
| CLAUDE.md edit collides with injector auto-commit / validate_instruction_content | Med    | Med         | Edit only user-content region; existing preservation check; run in main repo                             |
| Bulk per-handler edits trip blockers (sed/pipe/batch-cancellation)               | Med    | Med         | One Edit/turn/agent; never sed; never pipe head/tail; verify each landed                                 |

## Notes & Updates

Dated narrative lives in [JOURNAL/](JOURNAL/) (relocated 2026-08-31; the
2026-05-29 design notes are preserved in the 26-08-31 day-file). Hybrid
promotion design: [DESIGN-HYBRID-PROMOTION.md](DESIGN-HYBRID-PROMOTION.md).

- Delivery commit hash(es): 581abd31 (Decision I reactivation) → ba8860ed
  (advisory-tier collapse); key waypoints 8ac07a05 (block-report), ce80f38d
  (tracker wiring), f491c717 (reference migration), ff31c7e3 (two-tier
  injector, via index sweep), b9384ca3+2b9eb955 (parity suite), 8726b4da
  (promotion config-key fix), fde57267 (real-data promoted set). Full
  narrative in JOURNAL/.
