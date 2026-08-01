# Plan 00193: Extend the `$PYTHON` guidance sweep to living docs

**Status**: In Progress
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

### Inventory

The plan opened with "223 occurrences across 23 files", counted by grepping for
the literal string `PYTHON`. That figure was wrong **in kind**, not merely in
count: it measured one spelling of the defect. The defect is "documentation
hands the reader a command that cannot run", and it has **four** spellings —
the fourth being not a document at all, but a script printing to the operator:

| Variant                                   | What it is                                                                                                                    | Found  |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ------ |
| 1. `$PYTHON` / `$VENV_PYTHON`             | Never exported to a reader's shell; line expands to `-m …` → `command not found`                                              | 297    |
| 2. `<python> -m …daemon.cli`              | A PATH `python3` cannot import the package (`include-system-site-packages = false`)                                           | (in 1) |
| 3. `untracked/venv/bin/python` \| `…/pip` | The **retired pre-v3.7.0 venv layout**. Venvs are fingerprint-keyed since v3.7.0, so this directory exists on no live install | 65     |
| 4. The same, PRINTED at runtime by `.sh`  | Installer / upgrader / worktree scripts echo commands to the operator; `.sh` was outside the scanned suffixes entirely        | 9      |

Each variant was invisible to the search that found the previous one. Variant 3
names a real-looking path rather than an unset variable, so it *looks* runnable
and greps clean for `PYTHON` — it was the single largest group. Variant 4 is not
in a document at all: it is emitted at runtime, and was found only by
provisioning the client fixture and reading what the installer actually printed.

`CLAUDE/development/RELEASING.md` and `CLAUDE/development/CLIENT-MODE-TESTING.md`
are the deliberate explanatory references listed under Non-Goals — verified and
marked exempt in place, not rewritten.

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

- [x] ✅ **Task 1.1**: For every occurrence, classify as (a) instructs the
  reader to run an undefined `$PYTHON` — DEFECT, (b) defines `PYTHON` locally
  in the same snippet — KEEP, (c) explains the trap — KEEP.
- [x] ✅ **Task 1.2**: Record the counts per class so the QA gate's exemption
  list can be written from evidence rather than guessed.

### Phase 2: Remediate

- [x] ✅ **Task 2.1**: Fix the three MANDATORY CodeLifecycle docs first — they
  gate every code change in the project.
- [x] ✅ **Task 2.2**: Fix the recovery-path docs (`LLM-INSTALL.md`,
  `LLM-UPDATE.md`, `SELF_INSTALL.md`), which are read when things are already
  broken.
- [x] ✅ **Task 2.3**: Fix the remaining `CLAUDE/**` docs.
- [x] ✅ **Task 2.4**: Fix `docs/**` and `examples/**` (user-facing).
- [x] ✅ **Task 2.5**: Where a doc genuinely needs a raw interpreter (pytest,
  ad-hoc scripts), use the canonical resolver pattern rather than inventing a
  path — see `CLAUDE/development/RELEASING.md` Step 12.0 for the worked form.
- [x] ✅ **Task 2.6**: Replace hand-rolled venv/install recipes with their SSoT
  scripts — `setup_worktree.sh`, `install_version.sh`, `upgrade_version.sh`,
  and the `handlers` / `health` / `repair` / `list-venvs` CLI subcommands.
  Several docs also told the reader to `cd .claude/hooks-daemon`, which
  `daemon_location_guard` blocks.

### Phase 3: Lock it in

- [x] ✅ **Task 3.1**: Extend `scripts/qa/check_python_var_guidance.py` to cover
  `CLAUDE/**`, `docs/**` and `examples/**`, with explicit exemptions for the
  history paths in Non-Goals and the class-(b)/(c) occurrences found in Phase 1.
- [x] ✅ **Task 3.2**: Confirm the gate FAILS on a reintroduced occurrence — the
  widened gate was observed RED at 297, then 61, then 2 before reaching 0, and
  the new variant-3 rule was written test-first (3 failing tests → pass).
- [x] ✅ **Task 3.3**: Full QA green (14/14); daemon restarts RUNNING.
- [x] ✅ **Task 3.4**: Give the gate a test file — it shipped with none, which is
  why its `src/`-only scope went unchallenged. `tests/unit/qa/test_check_python_var_guidance.py`
  covers all three variants, the exemption semantics, and locks the real trees
  clean via `TestRepositoryIsClean`.
- [x] ✅ **Task 3.5**: Cover `scripts/**` and `.sh` files. Provisioning the client
  fixture showed the installer PRINTS variant 2 at completion, and
  `setup_worktree.sh` printed the literal `$PYTHON -m …` variant-1 form — runtime
  guidance reaches the operator exactly like a doc, but `.sh` was outside the
  scanned suffixes. The `.sh` rule fires only on an output statement that shows a
  COMMAND (`-m …daemon.cli`, or an escaped `\$PYTHON`); a diagnostic reporting an
  already-resolved interpreter is legitimate and must not be flagged.

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

### Decision 2: A gate's SCOPE is part of its contract and must be tested

**Context**: Plan 00192 shipped `python_var_guidance` scoped to `src/` only,
with no test file. It passed every release gate while 297 occurrences of the
exact defect it exists to prevent sat in `CLAUDE/`, `docs/` and `examples/`.
That is the direct answer to "how did this get through QA": **a gate only ever
checks what you point it at**, and nothing asserted where this one pointed.

**Decision**: Widening the scope is necessary but not sufficient. The gate now
has a test file whose `TestRepositoryIsClean` case runs it against its real
default roots — so a future narrowing of `_DEFAULT_SCAN_ROOTS` is a *test
failure*, not a silent loss of coverage. Exemptions are same-line and must state
their reason inline, so silencing a finding is visible in the diff.
**Date**: 2026-08-01

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
- Phases 1–3 delivered: 297 variant-1/2 occurrences and 65 variant-3 occurrences
  corrected across 30 files; gate widened to `CLAUDE/`, `docs/`, `examples/` and
  given its first test file; QA 14/14; daemon RUNNING. Phase 4 (client-fixture
  verification) outstanding.
