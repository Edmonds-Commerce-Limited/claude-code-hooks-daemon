# Plan 00209: field feedback daemon self observability

**Status**: In Progress
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Acts on a field feedback report from a long working session in a *documentation*
repo (filed here as `FEEDBACK.md`). Read it first — it is unusually careful, it
re-rates two of its own findings after push-back rather than quietly dropping
them, and it states what worked as well as what did not.

The headline item is not a bug. **The daemon makes hundreds of decisions per
session and persists none of them.** Every interesting question about the
tool — which handlers earn their keep, what the real false-positive rate is per
handler, whether a handler is in the wrong mode, whether adding one changed
anything measurable — is currently unanswerable, and answerable cheaply.

The remaining items are one real presentation defect and two small precision
refinements.

## Goals

- Give the daemon a **verdict log**, so its own effectiveness stops being
  anecdote
- Fix `pipe_blocker`'s remediation output, which quotes prose back as a shell
  command
- Reduce two sources of advisory noise, since noise is how advisories get
  ignored wholesale — including the ones that matter

## Non-Goals

- No change to `pipe_blocker`'s **detection**. Erring toward caution is correct
  for a safety handler, and properly separating heredoc bodies from executable
  text needs real shell parsing. The block is not the defect; the output is.
- No weakening of the `error`/`warning` output advisory. The report initially
  called it a false positive and then withdrew that: an advisory has no
  false-positive failure mode in the sense a blocker does.

## Context & Background

Findings, in the report's own ordering by cost:

| #   | Item                                             | Rating                            |
| --- | ------------------------------------------------ | --------------------------------- |
| 1   | `pipe_blocker` echoes heredoc prose as a command | Real defect, cosmetic impact      |
| 2   | `error`/`warning` output advisory                | **Working as intended**           |
| 3   | No verdict log                                   | Missing capability, highest value |
| 4   | `recovery_cron_advisor` repetition               | Minor noise                       |
| 5   | Formatter causes a stale-string `Edit` failure   | Minor, already documented         |

**§1 in detail**: appending a journal entry via a heredoc whose prose *described*
two earlier pipe blocks tripped the handler — so the document describing the
guardrail could not be written past the guardrail. The block is defensible. What
is not: the matched "command" was run through the remediation template, which
extracted `the` as the binary name (first word of a sentence) and emitted
`extra_whitelist: - "^the\\b"`, then offered `set -o pipefail` and suggested
redirecting the author's own narrative to `$TEMP_FILE`. A correct safety
decision was presented in a way that reads as broken, and it burned a large
amount of context re-quoting text just written.

**§3 in detail**: what exists today is `notifications.jsonl` and
`subagent_completions.jsonl`. Neither records which handler fired, on which tool
call, with what verdict. Decisions are emitted to the agent and discarded.

**Confirmed independently in this repo's own session**: §1 and §2 were both hit
repeatedly while working on v3.52.0, which is corroboration from a second
codebase of a different kind (code, not docs).

## Tasks

### Phase 1: `pipe_blocker` remediation output (TDD) — §1

- [x] ✅ **Task 1.1**: Failing test — a heredoc body of prose produces a block
  reason with NO remediation template and NO echoed prose
- [x] ✅ **Task 1.2**: Sanity-check before templating: if the matched "command"
  has no recognisable binary as its first token, or exceeds a sane length, emit
  the reason alone
- [x] ✅ **Task 1.3**: Cap the echoed command at N characters regardless. The
  full text is rarely what makes a block actionable
- [x] ✅ **Task 1.4**: Audit every other handler that echoes matched input into
  a remediation template — this defect class is not unique to `pipe_blocker`
  (DBF: fix the shared output path, not the one instance). An Explore agent
  audited every `pre_tool_use` handler; found and fixed one real instance
  (`npm_command.py`'s piped-command branch echoed the full raw command with
  no cap). All others either lack the naive-extraction-into-config-template
  step, or only echo already-bounded literal matches.

### Phase 2: Verdict log — §3, the valuable half

- [x] ✅ **Task 2.1**: Design decision — the write happens in
  `DaemonController.process_event()` (`daemon/controller.py`), reading
  `ChainExecutionResult.decisions` (new field on `core/chain.py`, populated
  once per matched handler inside `HandlerChain.execute()`), so every handler
  decision is captured without any handler opting in
- [x] ✅ **Task 2.2**: Append-only `verdicts.jsonl` via `daemon/verdict_log.py`,
  one line per decision: `{ts, session, event, tool, handler, verdict, rule, mode, overridden}`
- [x] ✅ **Task 2.3**: Synthetic `overridden: true` record when a
  `MUST_…_BECAUSE=`/`MUST_…_BECAUSE:` escape hatch marker is detected anywhere
  in the event payload — detects the SHARED convention shape once, since the
  bypassed handler's own `matches()` returns `False` and so contributes no
  entry of its own for that event
- [x] ✅ **Task 2.4**: Retention decision made EXPLICIT: `verdicts.jsonl` is a
  bounded ROLLING SAMPLE via the same `cap_log_file` primitive as every other
  daemon JSONL log (Plan 00181) — NOT a durable lifetime counter. Documented in
  the module docstring, `VerdictLogConfig`, and `docs/guides/VERDICT_LOG.md`;
  `hooks-daemon verdicts`' own output states this explicitly on every run so
  the numbers can never be read as lifetime totals (the Plan 00206 lesson)
- [x] ✅ **Task 2.5**: `hooks-daemon verdicts` CLI command
  (`daemon/verdict_report.py` + `cli.py`) — per-handler fire counts, per-handler
  verdict mix, overall verdict mix, override count/rate, and never-fired
  handlers (queried from a running daemon over the socket; reports
  "unavailable" rather than a misleading empty list when no daemon is running)
- [x] ✅ **Task 2.6**: Config gate (`daemon.verdict_log.enabled`, default
  `true`) + docs (`docs/guides/VERDICT_LOG.md`, linked from `CLAUDE.md`).
  Default-on because only handler/rule/verdict metadata is recorded, never
  tool payloads or file contents — no privacy reason to ship it dormant.
  Along the way, found and fixed a real wiring bug: `DaemonController`'s
  `config` constructor parameter is never populated by the real daemon
  startup path (`_build_initialised_controller` always constructs
  `DaemonController()` with no config), which would have made
  `verdict_log.enabled: false` permanently inert. Threaded `verdict_log` as
  its own narrow config-slice parameter through `initialise()`, the same DI
  idiom already used for `plan_workflow`/`pseudo_events_config`.

### Phase 3: Advisory noise — §2, §4, §5 (NOT STARTED — deliberately deferred)

Deprioritised per this plan's own Decision 1 (the verdict log is the
priority) and the report's own framing of these three as "minor noise" /
"optional, offered as such". Left for a follow-up session rather than rushed:

- [ ] ⬜ **Task 3.1**: §2 (optional, offered as such) — skip the output-keyword
  advisory when the trigger keyword also appears in the COMMAND string, e.g. a
  `grep` pattern or a repo name. Those fires cannot carry signal
- [ ] ⬜ **Task 3.2**: §4 — rate-limit `recovery_cron_advisor`'s creation and
  completion phases the way the progress phase already is, and/or suppress for
  the rest of a session after N ignored fires
- [ ] ⬜ **Task 3.3**: §5 — have `markdown_table_formatter`'s advisory NAME the
  transformations it applied (list renumbering, pipe alignment) so an `Edit`
  retry after a stale-string failure is targeted rather than a blind re-read

### Phase 4: Phase 1 regression — length is not evidence of prose

Found by dogfooding during the Plan 00218 merge, not by a test: an ordinary
82-character `git merge-tree` invocation crossed Phase 1's `>80 chars ⇒ prose`
trigger and was denied with the prose reason, which withholds the matched text
and the remediation and ends "no action needed beyond retrying" — false for a
real command. See `JOURNAL/00209-Journal-26-08-12.md` for the full analysis.

- [x] ✅ **Task 4.1**: RED — inverse-direction tests. Phase 1 only ever asserted
  that long prose IS prose; nothing asked whether a long string could be a real
  command, which in this repo is routine (32-char worktree branch names,
  absolute paths). Includes a positive control asserting the fixture actually
  exceeds the old bound, so it cannot pass vacuously
- [x] ✅ **Task 4.2**: GREEN — replace the length trigger with function-word
  density. Prose runs 30-50% closed-class words, a command runs 0%. A token
  OPENING with a quote vetoes the ratio, since that is where English
  legitimately lives inside a command (`echo "this is a test"` scores 60%)
- [x] ✅ **Task 4.3**: Correct the Phase 1 test that pinned the false premise.
  Its example is genuinely prose so its assertion stood, but it claimed length
  as the reason — the reason is what a future reader generalises from
- [x] ✅ **Task 4.4**: Update `get_claude_md()`, which shipped the same false
  rule to every project, and state explicitly that a long command is still a
  command
- [x] ✅ **Task 4.5**: Verify against the LIVE daemon through the production
  forwarder — real command gets remediation, field-report prose still gets the
  short reason, short unknown commands unchanged

### Phase 5: The report contradicted itself — found by dogfooding the feature

The first run of `hooks-daemon verdicts` against a genuinely LIVE daemon (this
plan's own outstanding criterion, discharged 26-08-21) exposed a defect in the
reader, not the writer. The report's standing caveat says status handlers "are
omitted from the roster below" and then listed thirteen of them at the top of
that roster — 19,750 of 26,676 retained records (74%), all from one 30-minute
window on 26-08-13, before Plan 00234's exclusion landed. The log is a rolling
window, so pre-change records stay until trimmed.

Two enumeration surfaces disagreed: `cli.py`'s `_behavioural_handler_names`
drops Status renderers from the REGISTERED side, while `aggregate_verdicts`
kept them on the FIRED side — the class Plan 00237 closed in the registry,
reappearing in the report. It also inflated the override denominator with
records that cannot carry an override, understating the rate ~4x (0.1% vs the
true 0.3%) — the one number this plan calls "the strongest available signal
that a rule is mis-tuned".

- [x] ✅ **Task 5.1**: RED — six failing tests, including `assert 0.2 == 0.5`
  catching the inflated denominator directly rather than arguing for it
- [x] ✅ **Task 5.2**: GREEN — partition Status renders out of the roster, the
  verdict mix and the override denominator; report them in an explicit block
  naming the count, the share and the date range. Partitioned, never dropped:
  discarding three quarters of a window in silence would present the rest as
  freshly collected
- [x] ✅ **Task 5.3**: DBF — nothing pinned the caveat's wording, which is how
  it drifted into being false. The guard added is a PROPERTY (no roster line
  may name a handler the report says it omitted), not a regression case
- [x] ✅ **Task 5.4**: Verified against the same live log that exposed it — the
  roster now leads with `lint-on-edit`, carries no `status-*` entry, and the
  override rate reads 0.3% of 6,947 behavioural decisions

## Dependencies

- Related: Plan 00206 — its retention finding (a capped log cannot back a
  cumulative counter) directly constrains Task 2.4

## Technical Decisions

### Decision 1: The verdict log is the priority, not the bug fixes

**Context**: §1 is a real defect but cosmetic. §3 is not a bug at all.

**Decision**: §3 first. Without it, every judgement about this daemon — including
which of §1/§2/§4 actually matter — rests on anecdote, which is precisely what
the daemon exists to replace elsewhere. It also makes the tuning questions the
other findings raise answerable with a query rather than a discussion.

**Date**: 2026-08-12

## Success Criteria

- [x] ✅ A heredoc of prose produces a short, accurate block reason and no
  fabricated shell scaffolding
- [x] ✅ `verdicts.jsonl` records every handler decision — proven end-to-end via
  `TestControllerVerdictLog` (real `process_event()` → real
  `HandlerChain.execute()` → real file on disk, reading the content back and
  asserting on it). **Confirmed against a genuinely LIVE daemon** on 26-08-21
  from the main checkout: `untracked/logs/hooks/verdicts.jsonl` is appended to
  in real time (6.3 MB, written inside the observing session). The worktree
  isolation that blocked this for nine days is gone — and the first live run
  is what exposed the Phase 5 reporting defect
- [x] ✅ `hooks-daemon verdicts` answers "which handlers have never fired" and
  "what is the override rate per handler" over that data
- [x] ✅ The retention decision for `verdicts.jsonl` is explicit and documented,
  and does not silently corrupt cumulative statistics (the report is explicit
  that its numbers describe the retained window, not lifetime totals)
- [ ] ⬜ Full QA passes; daemon restarts RUNNING — QA is 18/20 in-worktree (see
  JOURNAL); the 2 gaps are a daemon restart / live-socket smoke test this
  worktree cannot run, and a confirmed pre-existing test-order flake
  unrelated to this plan's changes. **Daemon restart verification is
  OUTSTANDING** for the same worktree-isolation reason

## Risks & Mitigations

| Risk                                                  | Impact | Probability | Mitigation                                                                                     |
| ----------------------------------------------------- | ------ | ----------- | ---------------------------------------------------------------------------------------------- |
| Verdict log becomes a per-event write hot path        | Medium | Medium      | Written once in the front controller, append-only, no read-modify-write; measure dispatch cost |
| The log records something privacy-sensitive           | High   | Low         | Record handler/rule/verdict metadata only — never tool payloads or file contents               |
| Capped retention silently corrupts derived statistics | Medium | Medium      | Task 2.4 makes the choice explicit; Plan 00206 hit exactly this with a 5 MB cap                |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00209-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Phases 1 and 2 delivered on branch `agent-ac1ec50c70f9ed8b8-2fdf9107`
  (isolated worktree). See JOURNAL for the full commit list. Phase 3 not
  started — see Tasks above.
