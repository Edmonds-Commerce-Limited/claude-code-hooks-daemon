# Plan 00231: Bounded-Read QA Rule

**Status**: Complete
**Created**: 2026-08-13
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

A latency defect surfaced while answering a question about why the Stop handler
reads the session transcript: `has_recent_stop_hook_block()` in
`src/claude_code_hooks_daemon/utils/stop_hook_helpers.py` wanted the last 20
lines of a file and obtained them with `deque(f, maxlen=20)` — an idiom that
iterates every line in the file to keep twenty. Measured on a live 74 MB
session transcript: **162 ms against 17 ms** for the equivalent bounded seek,
growing linearly and without limit because transcripts only ever append.

The path is called only when `stop_hook_active` is set — that is, only during a
deny/re-fire loop — so the code that runs repeatedly was the code paying the
whole-file cost.

Plan 00177 had already fixed exactly this defect in
`TranscriptReader.load_tail` by seeking to `max(0, size - max_bytes)`. It did
not fix the sibling helper, which kept the `deque` spelling and went unnoticed.
Per CLAUDE.md Standard 15 (DEFENCE BEFORE FIX) the bug worth fixing is
therefore the **missing guard**, not the single instance: a hand-fix cannot
generalise, and the next occurrence would again be found by accident.

## Goals

- Add a QA check that makes the defect class mechanically unrepeatable
- Wire it into both QA entry points so it gates every commit
- Fix the one instance the new guard reports, so the gate is green
- Record the rule's deliberate precision boundary so it is not "improved" into
  a false-positive generator

## Non-Goals

- A general dataflow/taint analysis (see Decision 2)
- Replacing the repo's bespoke-scanner approach with an off-the-shelf engine
  (see Decision 3 — a real option, but an architectural call for the owner)

## Context & Background

The signal that makes this class checkable is that the author has **already
written the bound down**. `maxlen=20` states the intent, sitting immediately
next to a read that ignores it. The contradiction is local and explicit, so no
guess about file size is needed — which keeps the rule inside the
mechanically-checkable enforcement boundary CLAUDE.md draws for NO MAGIC.

A whole-file read with no declared bound is deliberately NOT a violation:
loading a config or a plan document is correct.

## Tasks

### Phase 1: Build the guard

- [x] ✅ **Task 1.1**: Write failing tests for the checker
  - [x] ✅ `deque(<handle>, maxlen=N)` detected; `deque(<list>, maxlen=N)` not
  - [x] ✅ Sliced whole-file reads detected (`readlines()[-N:]`,
    `read_text().splitlines()[:N]`, `list(f)[-N:]`)
  - [x] ✅ Correct remedies stay silent (bounded seek, streaming iteration,
    `itertools.islice`)
  - [x] ✅ Inline `bounded-read-exempt:` escape hatch honoured
- [x] ✅ **Task 1.2**: Implement `scripts/qa/check_bounded_reads.py` (AST-based)
- [x] ✅ **Task 1.3**: Fix the silent `except ValueError` the repo's own
  error-hiding audit caught in the new checker

### Phase 2: Wire it in

- [x] ✅ **Task 2.1**: Register in `scripts/qa/run_all.sh` (check + summary map)
- [x] ✅ **Task 2.2**: Register in `scripts/qa/llm_qa.py` (ToolConfig + summarizer)

### Phase 3: Fix what the guard reported

- [x] ✅ **Task 3.1**: Replace the `deque` tail read with a bounded backward
  seek in `stop_hook_helpers.py`
- [x] ✅ **Task 3.2**: Add byte-accounting tests pinning the cost behaviourally
- [x] ✅ **Task 3.3**: Prove the byte-accounting guard is NOT vacuous by running
  it against a reconstruction of the original defect

### Phase 4: Record the boundary

- [x] ✅ **Task 4.1**: Document the variable-indirection blind spot and why
  widening it is refused (Decision 2)

## Technical Decisions

### Decision 1: Key the rule on the DECLARED bound, not on whole-file reads

**Context**: "Reads a whole file" is far too broad — most whole-file reads in
this repo are correct.

**Decision**: Fire only when a bound (`maxlen=`, a slice) is applied to a
whole-file read. The bound is the author's own statement of intent, which is
what makes the contradiction mechanically detectable without knowing file sizes.

**Date**: 2026-08-13

### Decision 2: Refuse to follow variables, and say why in the checker

**Context**: The rule requires the bound to be applied DIRECTLY to the read.
`background_process_tracker.py` reads a whole file on one line and slices it
two lines later through a variable, so the rule misses it.

**Options considered**:

1. Widen to follow variables — catches that shape.
2. Stay narrow and document the gap.

**Decision**: Option 2. That specific code is **not** a defect: it rewrites the
file truncated to `max_lines` on every write, so the log self-rotates and the
read is bounded by construction. Widening would make the rule's very first
extra finding a false positive, because deciding the case needs a fact no AST
can see. Precision beats recall for a gate that blocks commits — the same
conclusion Plan 00208 reached when it demoted four `comment_changelog` signals
to advisory. The blind spot is recorded in the checker's own docstring.

**Date**: 2026-08-13

### Decision 3: Bespoke AST checker rather than Semgrep / ast-grep

**Context**: Ruff (0.15.22, installed) has **no** plugin or custom-rule
mechanism — `--extend-select` selects from built-in codes only. Tools that DO
support user-defined rules are Semgrep, ast-grep, Pylint plugins and Flake8
plugins.

**Decision**: Follow the repo's established pattern — `scripts/qa/` already
holds 15 bespoke scanners. Introducing a 16th tool is an architectural change,
not a bug fix.

**Recorded caveat**: Semgrep would express THIS rule better (roughly 15 lines
of YAML using `pattern-inside` for the `with open(...) as $F` scope, versus a
Python module that itself needs a test suite). Most of this repo's other guards
— `check_doc_truth`, `check_git_history`, `check_handler_reference` — reason
about git refs, cross-file consistency and config, and are not expressible in
any code-pattern engine. A hybrid is the honest end state and is left to the
repository owner.

**Date**: 2026-08-13

## Success Criteria

- [x] ✅ Checker detects every tested spelling of the defect
- [x] ✅ Checker reports zero false positives across `src/`, `scripts/`,
  `.claude/project-handlers/`
- [x] ✅ Byte accounting proves the fix: 2,396,089 bytes read before, 65,536
  after, marker still found
- [x] ✅ Full QA green at 21/21 (was 20/20)
- [x] ✅ Daemon restarts and reports RUNNING

## Risks & Mitigations

| Risk                                                        | Impact | Probability | Mitigation                                                                       |
| ----------------------------------------------------------- | ------ | ----------- | -------------------------------------------------------------------------------- |
| Rule is registered but blind (the Plan 00230 failure shape) | High   | Medium      | Byte-accounting test run against a reconstruction of the original defect         |
| Future widening reintroduces false positives                | Medium | Medium      | Blind spot and its rationale recorded in the checker docstring                   |
| Guard's own code trips other guards                         | Low    | Realised    | The repo's error-hiding audit caught a silent `except ValueError`; fixed at root |

## Delivery & Milestones

- Guard, wiring, instance fix and tests delivered together in the closing commit
