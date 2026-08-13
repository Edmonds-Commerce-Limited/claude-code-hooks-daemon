# Plan 00203: Advisory Handler CLAUDE.md Guidance Coverage

**Status**: Not Started
**Created**: 2026-08-10
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The v3.52.0 release ran the RELEASING.md Step 11 CLAUDE.md guidance audit and
found six **PreToolUse advisory** handlers that return `None` from
`get_claude_md()`. Every PreToolUse **blocking** handler is covered, so the
gate's stated focus was satisfied and the release proceeded — but per the
"never drop a finding" rule in `CLAUDE/development/RELEASING.md`, the finding
is captured here rather than lost to scrollback.

This is a pre-existing gap, not a regression introduced by v3.52.0. Both
handlers added in that release (`sensitive_content`, `agent_isolation_advisor`)
ship with guidance.

The work is **not** mechanical. `get_claude_md()` output is inlined into every
client project's resident `CLAUDE.md`, which is loaded in full on every
session. Adding six sections is a permanent per-session context cost paid by
every user of the daemon. So the first question for each handler is whether it
belongs in the always-resident doc at all, or whether its fire-time advisory
text is already sufficient and self-explanatory.

## Goals

- Decide, per handler, whether resident guidance earns its context cost
- Add `get_claude_md()` to the handlers where the answer is yes
- Make the audit repeatable, so the next gap is found by a gate rather than by
  a human running an ad-hoc script during a release

## Non-Goals

- Adding guidance to `hello_world` test handlers, status-line handlers,
  loggers, or lifecycle handlers — these are correctly `None`
- Changing any handler's runtime behaviour
- Rewriting existing guidance that is already accurate

## Context & Background

Audit performed during the v3.52.0 release gate. 43 handlers returned guidance;
52 returned `None`, of which the great majority are legitimately exempt
(`hello_world` variants, `status_line/*`, `notification/*`, `session_end/*`,
loggers, and context-injection handlers whose injected text IS the guidance).

### Findings — PreToolUse advisory handlers returning None

| Handler                                            | Priority | Severity |
| -------------------------------------------------- | -------- | -------- |
| `handlers/pre_tool_use/british_english.py`         | 60       | Low      |
| `handlers/pre_tool_use/daemon_docs_guard.py`       | 57       | Low      |
| `handlers/pre_tool_use/global_npm_advisor.py`      | 42       | Low      |
| `handlers/pre_tool_use/plan_completion_advisor.py` | 48       | Medium   |
| `handlers/pre_tool_use/task_tdd_advisor.py`        | 36       | Medium   |
| `handlers/pre_tool_use/web_search_year.py`         | 55       | Low      |

The two Medium entries shape agent workflow (TDD delegation, plan closure) and
are the strongest candidates for resident guidance. The Low entries fire on
narrow, self-explanatory conditions where the advisory message alone is likely
enough.

### Findings — other event types returning None

Recorded for completeness; each needs the same earns-its-place judgement and
most will legitimately stay `None`: `post_tool_use/bash_error_detector`,
`post_tool_use/lint_on_edit`, `pre_compact/transcript_archiver`,
`pre_compact/compaction_signal`, `session_start/git_filemode_checker`,
`session_start/gitignore_safety_checker`, `session_start/optimal_config_checker`,
`session_start/suggest_statusline`, `session_start/version_check`,
`session_start/yolo_container_detection`, `stop/task_completion_checker`,
`stop/hedging_language_detector`, `nitpick/*`, `subagent_stop/*`,
`user_prompt_submit/*`, `worktree_remove/*`, `permission_request/hello_world`.

`post_tool_use/lint_on_edit` is worth singling out: v3.52.0 made it actually
run (it was silently inert whenever the linter lived only in the venv), so it
now DENIES edits that previously sailed through with an advisory. A handler
that newly blocks is exactly the kind that should explain itself in the
resident doc.

## Tasks

### Phase 1: Decide what belongs in the resident doc

- [ ] ⬜ **Task 1.1**: Write down the criterion for "earns resident guidance"
  - [ ] ⬜ Draft it against the handlers already covered, so it describes
    existing practice rather than inventing a new rule
  - [ ] ⬜ Record it in `CLAUDE/HANDLER_DEVELOPMENT.md` so new handlers get the
    question asked at write time
- [ ] ⬜ **Task 1.2**: Apply the criterion to the six PreToolUse advisories
- [ ] ⬜ **Task 1.3**: Apply it to `post_tool_use/lint_on_edit` (now blocking)
- [ ] ⬜ **Task 1.4**: Apply it to the remaining event types; record which are
  deliberately `None` and why

### Phase 2: Implement (TDD)

- [ ] ⬜ **Task 2.1**: For each handler that earns guidance, write the failing
  test first (assert `get_claude_md()` is non-empty and names the trigger)
- [ ] ⬜ **Task 2.2**: Implement `get_claude_md()` bodies
- [ ] ⬜ **Task 2.3**: Regenerate `.claude/HOOKS-DAEMON.md` and the daemon's
  `CLAUDE.md` section; review the resident-doc size delta
- [ ] ⬜ **Task 2.4**: Full QA + daemon restart verification

### Phase 3: Make it a gate (DBF)

- [ ] ⬜ **Task 3.1**: Replace the ad-hoc release-time script with a QA check
  that enumerates handlers and asserts each is either covered or on an
  explicit, reasoned exemption list
  - [ ] ⬜ Model it on `test_blocking_handler_evasion.py`: discovery-based, so
    a new handler cannot silently escape triage
  - [ ] ⬜ Exemptions carry a reason string, not a bare name
- [ ] ⬜ **Task 3.2**: Wire it into `scripts/qa/run_all.sh` and `llm_qa.py`
- [ ] ⬜ **Task 3.3**: Remove the manual audit step from RELEASING.md Step 11,
  or reduce it to running the gate

## Dependencies

- Related: Plan 00200 (QA gate integrity) — same DBF pattern, different surface

## Technical Decisions

### Decision 1: Capture rather than fix during the v3.52.0 release

**Context**: The audit runs as a BLOCKING release gate, and it found six
uncovered handlers.

**Options Considered**:

1. Fix all six inside the release — closes the finding immediately, but each
   addition permanently enlarges every client's resident `CLAUDE.md`, and that
   is a design judgement being made under release pressure. It would also force
   a full FAIL-FAST restart of the QA and acceptance gates.
2. Capture as a tracked follow-up — the documented remedy in RELEASING.md's
   "Review Early, Never Drop Findings" section.

**Decision**: Option 2. The gate's stated focus — PreToolUse **blocking**
handlers — is fully satisfied, no finding is a regression from this release,
and the remaining work needs deliberate per-handler judgement about resident
context cost rather than a mechanical sweep.

**Date**: 2026-08-10

## Success Criteria

- [ ] Every handler is either covered by `get_claude_md()` or on an explicit
  exemption list carrying a reason
- [ ] A QA check enforces that, so the next gap is found automatically
- [ ] Resident `CLAUDE.md` growth from this work is measured and justified
- [ ] All QA checks passing; daemon restart verified

## Risks & Mitigations

| Risk                                                     | Impact | Probability | Mitigation                                                                  |
| -------------------------------------------------------- | ------ | ----------- | --------------------------------------------------------------------------- |
| Six new sections bloat every client's resident CLAUDE.md | Medium | High        | Task 1.1 sets an explicit criterion; Task 2.3 measures the size delta       |
| Exemption list becomes a dumping ground                  | Medium | Medium      | Entries require a reason string; mirrors the evasion suite's classification |
| Guidance drifts from handler logic                       | Medium | Medium      | Existing `handler_reference` truth check covers the reference doc; extend   |

## Related: the three halves of guidance/handler correspondence

This plan is one of three checks on the same correspondence, recorded here
because two of them arrived after it was filed and this is the doc a future
session on guidance coverage will actually read.

| case                               | question                        | state                                     |
| ---------------------------------- | ------------------------------- | ----------------------------------------- |
| handler exists, guidance MISSING   | which handlers say nothing?     | **this plan**                             |
| guidance exists, handler MISSING   | which guidance has no producer? | **shipped** — `orphaned-handler-guidance` |
| guidance exists, and is never READ | which guidance is dead weight?  | unplanned — F19, see below                |

**Orphaned guidance (shipped, commit `f0724656`).** `claude_md_injector` now
emits a `<!-- handler: <name> -->` provenance marker per section, and
`check_repo_hygiene`'s `orphaned-handler-guidance` rule asserts every marker
resolves to a live handler. Relevant to this plan for two reasons: adding
guidance for the six uncovered handlers will emit markers that the rule then
polices, and the marker infrastructure is the enabler for the third case.

**F19 "Dead-guidance audit"** (`Completed/00169-.../FEATURE-BACKLOG.md`, sized
M) proposes finding never-loaded `CLAUDE.md`/`.claude/rules/*` sections so the
resident surface can be pruned. It is NOT the same as the orphan check — F19 is
about guidance nobody reads, the orphan rule about guidance nothing produces —
but it now has a foothold it lacked when filed, since sections are individually
identifiable. It bears directly on this plan's own risk row "six new sections
bloat every client's resident CLAUDE.md": F19 is how that would be measured
rather than estimated. Still unplanned; noted here so it is not left in a
completed plan's backlog where nothing looks.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes (git is the SSoT for "when"). -->

- Finding raised during the v3.52.0 release gate
