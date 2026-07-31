# Plan 00193: Extend the `$PYTHON` guidance sweep to living docs

**Status**: Not Started
**Created**: 2026-07-31
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plan 00192 eliminated the unrunnable `$PYTHON -m claude_code_hooks_daemon.daemon.cli …`
instruction from `src/` — 77 occurrences across 29 files — and installed the
`python_var_guidance` QA gate so it cannot return. That gate is scoped to
`src/` only.

**223 occurrences across 23 living documentation files remain outside that
scope.** They are the same defect: an agent that follows them runs a command
that expands to `-m: command not found`, concludes the package is not
installed, and starts "fixing" a working install (`pip install` into the wrong
environment, editing the Dockerfile, rebuilding a venv that was never broken).
Plan 00192's field report documents exactly that recovery path being started.

These are **pre-existing, not a regression** — they shipped in v3.49.1 and
every prior version. They were found during the v3.50.0 release code review and
are tracked here rather than dropped, per RELEASING.md "Review Early, Never
Drop Findings".

## Goals

- No living documentation file instructs the reader to invoke a raw interpreter
  or a `$PYTHON` variable that is never exported in their shell.
- The `python_var_guidance` QA gate covers these paths, so the class cannot
  silently return.
- Docs that legitimately define `PYTHON` as their own local shell variable
  inside a self-contained snippet keep working, and are distinguished from docs
  that hand the reader an undefined variable.

## Non-Goals

- Rewriting immutable history: `RELEASES/`, `CHANGELOG.md`, completed and
  cancelled plans, `CLAUDE/UPGRADES/v2/**` and `v3/**` (shipped upgrade guides
  describe what was true at the time), and
  `CLAUDE/AcceptanceTests/PLAYBOOK-v1-manual-archived.md`.
- Changing any CLI behaviour. This is a documentation-accuracy plan.
- The deliberate references that EXPLAIN the trap rather than instruct it —
  `CLAUDE.md` ("do not expect `$PYTHON` to be set — it never is in your
  shell"), `CLAUDE/development/RELEASING.md` and
  `CLAUDE/development/CLIENT-MODE-TESTING.md`. These must survive the sweep.

## Context & Background

### Inventory (measured at plan creation, `rg -c 'PYTHON'`)

| File                                        | Count |
| ------------------------------------------- | ----- |
| `CLAUDE/Worktree.md`                        | 37    |
| `CLAUDE/LLM-UPDATE.md`                      | 36    |
| `CLAUDE/AgentTeam.md`                       | 27    |
| `CLAUDE/SELF_INSTALL.md`                    | 23    |
| `CLAUDE/PROJECT_HANDLERS.md`                | 16    |
| `CLAUDE/LLM-INSTALL.md`                     | 14    |
| `docs/guides/GETTING_STARTED.md`            | 11    |
| `docs/guides/CONFIGURATION.md`              | 8     |
| `CLAUDE/CodeLifecycle/General.md`           | 7     |
| `CLAUDE/CodeLifecycle/Bugs.md`              | 7     |
| `CLAUDE/QA.md`                              | 6     |
| `CLAUDE/CodeLifecycle/Features.md`          | 6     |
| `CLAUDE/HANDLER_DEVELOPMENT.md`             | 4     |
| `examples/project-handlers/README.md`       | 3     |
| `docs/guides/HANDLER_REFERENCE.md`          | 3     |
| `CLAUDE/PlanWorkflow.md`                    | 3     |
| `CLAUDE/Architecture/StatusLine.md`         | 3     |
| `CLAUDE/AcceptanceTests/GENERATING.md`      | 3     |
| `CLAUDE/CodeLifecycle/README.md`            | 2     |
| `CLAUDE/Performance/README.md`              | 1     |
| `CLAUDE/DEBUGGING_HOOKS.md`                 | 1     |
| `CLAUDE/development/RELEASING.md`           | 1     |
| `CLAUDE/development/CLIENT-MODE-TESTING.md` | 1     |

The last two rows are the deliberate explanatory references listed under
Non-Goals — verify, do not rewrite.

### Severity is not uniform

Three of these carry more weight than their counts suggest:

- `CLAUDE/CodeLifecycle/{General,Bugs,Features}.md` are marked **MANDATORY** in
  `CLAUDE.md` and are read before every code change. Their daemon-restart
  verification step — the single most important check in the project — is
  currently written as an uncopyable command.
- `CLAUDE/LLM-INSTALL.md` and `CLAUDE/LLM-UPDATE.md` are what an agent reads
  when a project is *already* in a broken or half-installed state. That is the
  worst possible moment to hand it a command that fails.
- `docs/guides/GETTING_STARTED.md` is a new user's first contact.

### Not every occurrence is a defect

Some snippets define `PYTHON` locally before using it, which is correct and
self-contained:

```bash
PYTHON="$(resolve_venv_python /workspace)"
"$PYTHON" -m pytest …
```

The sweep must distinguish "the doc defines it" from "the doc assumes the
reader has it". Only the latter is broken. A blind find-and-replace would
damage the former.

## Tasks

### Phase 1: Classify

- [ ] ⬜ **Task 1.1**: For every occurrence, classify as (a) instructs the
  reader to run an undefined `$PYTHON` — DEFECT, (b) defines `PYTHON` locally
  in the same snippet — KEEP, (c) explains the trap — KEEP.
- [ ] ⬜ **Task 1.2**: Record the counts per class so the QA gate's exemption
  list can be written from evidence rather than guessed.

### Phase 2: Remediate

- [ ] ⬜ **Task 2.1**: Fix the three MANDATORY CodeLifecycle docs first — they
  gate every code change in the project.
- [ ] ⬜ **Task 2.2**: Fix the recovery-path docs (`LLM-INSTALL.md`,
  `LLM-UPDATE.md`, `SELF_INSTALL.md`), which are read when things are already
  broken.
- [ ] ⬜ **Task 2.3**: Fix the remaining `CLAUDE/**` docs.
- [ ] ⬜ **Task 2.4**: Fix `docs/**` and `examples/**` (user-facing).
- [ ] ⬜ **Task 2.5**: Where a doc genuinely needs a raw interpreter (pytest,
  ad-hoc scripts), use the canonical resolver pattern rather than inventing a
  path — see `CLAUDE/development/RELEASING.md` Step 12.0 for the worked form.

### Phase 3: Lock it in

- [ ] ⬜ **Task 3.1**: Extend `scripts/qa/check_python_var_guidance.py` to cover
  `CLAUDE/**`, `docs/**` and `examples/**`, with explicit exemptions for the
  history paths in Non-Goals and the class-(b)/(c) occurrences found in Phase 1.
- [ ] ⬜ **Task 3.2**: Confirm the gate FAILS on a reintroduced occurrence
  (deliberately add one, watch it fail, remove it) — a gate never seen red is
  not known to work.
- [ ] ⬜ **Task 3.3**: Full QA green; daemon restarts RUNNING.

### Phase 4: Verify where it matters

- [ ] ⬜ **Task 4.1**: Rebuild the client fixture
  (`scripts/dummy-client-repo.sh create`) and confirm the client-visible copies
  of these docs contain no undefined-variable instructions.
- [ ] ⬜ **Task 4.2**: Execute a sample of the corrected commands verbatim from
  the client tree — the Plan 00192 standard: a command is fixed when it RUNS,
  not when it looks right.

## Dependencies

- Depends on: Plan 00192 (Complete) — provides `bin/hooks-daemon`,
  `utils/cli_command.py` and the `python_var_guidance` gate this plan extends.

## Technical Decisions

### Decision 1: Extend the existing gate rather than add a second one

**Context**: Phase 3 could add a separate docs-only checker.

**Options Considered**:

1. New checker for docs — a second regex and exemption list to keep in sync
   with the first; they will drift.
2. Widen `check_python_var_guidance.py`'s path scope and exemption list.

**Decision**: Option 2. One gate, one pattern, one exemption list. The gate
already distinguishes exempt paths; this is a scope change, not new logic.
**Date**: 2026-07-31

## Success Criteria

- [ ] Every class-(a) occurrence is corrected; class-(b)/(c) are intact.
- [ ] `python_var_guidance` covers `CLAUDE/**`, `docs/**`, `examples/**` and has
  been observed failing on a reintroduction.
- [ ] Client fixture shows no undefined-variable instructions in shipped docs.
- [ ] Full QA passes; daemon restarts RUNNING.

## Risks & Mitigations

| Risk                                                   | Impact | Probability | Mitigation                                                                              |
| ------------------------------------------------------ | ------ | ----------- | --------------------------------------------------------------------------------------- |
| Blind find-and-replace breaks self-contained snippets  | Medium | High        | Phase 1 classifies before Phase 2 edits; class-(b) snippets are explicitly preserved    |
| Sweep silently rewrites the docs that EXPLAIN the trap | Medium | Medium      | Named in Non-Goals and asserted in Task 3.1's exemption list                            |
| Gate exemptions become a dumping ground                | Low    | Medium      | Exemptions must cite the class from Phase 1 evidence, not be added to silence a failure |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when"). Activity log lives in JOURNAL/. -->

- Plan created from the v3.50.0 release code-review finding; inventory measured
  at 223 occurrences across 23 files.
