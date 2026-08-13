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

- Migrating the repo's OTHER bespoke scanners to semgrep. `check_doc_truth`,
  `check_git_history` and `check_handler_reference` reason about git refs,
  cross-file consistency and config — none of that is expressible in a
  code-pattern engine, so the end state is a hybrid, not a replacement.

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
- [x] ✅ **Task 1.2**: Implement an AST-based checker (later removed — Phase 6)
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

### Phase 5: Close the class a shape rule cannot reach

- [x] ✅ **Task 5.1**: Audit the new checker for false negatives
- [x] ✅ **Task 5.2**: Verify the audit's findings independently before acting
- [x] ✅ **Task 5.3**: Add a NAME-keyed rule banning `TranscriptReader.load()`
  outside its defining module (Decision 4)
- [x] ✅ **Task 5.4**: Switch `idle_housekeeping_advisor` to `load_tail()`

### Phase 6: Replace the bespoke checker with semgrep

- [x] ✅ **Task 6.1**: Verify semgrep would not reach client projects — read
  `scripts/install/venv.sh:674` and confirm the installer runs
  `uv pip install -e <dir>` with **no** `[dev]` extra
- [x] ✅ **Task 6.2**: Benchmark both engines on the SAME 11-shape probe
- [x] ✅ **Task 6.3**: Express the rules as `scripts/qa/semgrep/bounded-reads.yaml`
- [x] ✅ **Task 6.4**: Add `run_semgrep_check.sh` that FAILS LOUD when semgrep is
  absent, rather than reporting green over an unexamined tree
- [x] ✅ **Task 6.5**: Delete `check_bounded_reads.py` and its 19 tests; re-point
  QA check #20 at semgrep in both entry points
- [x] ✅ **Task 6.6**: Diagnose the 2 remaining misses rather than hedging (see
  Decision 5)

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

### Decision 3: Semgrep, not a bespoke AST checker

**Context**: Ruff (0.15.22, installed) has **no** plugin or custom-rule
mechanism — `--extend-select` selects from built-in codes only. Tools that DO
support user-defined rules are Semgrep, ast-grep, Pylint plugins and Flake8
plugins. DBF (Standard 15) makes "add a guard" a routine act, so the cost of
authoring one guard is a structural cost, not a one-off.

**Options considered**:

1. A bespoke AST scanner, following the pattern of the 15 already in
   `scripts/qa/` — a few hundred lines of Python plus its own test suite.
2. Semgrep rules — declarative YAML, no test suite of their own.

**Decision**: Option 2. Settled by measurement rather than by argument: run
against the same 11-shape probe of this defect class, the hand-written checker
caught **1**, the semgrep rules caught **9**.

**This reverses the decision originally recorded here**, which chose Option 1 to
avoid "a new runtime dependency in a daemon that clones into client projects".
That objection was simply false, and one file settled it: `scripts/install/venv.sh:674`
provisions a client venv with `uv pip install -e <dir>` and no `[dev]` extra,
so ruff, mypy, black and bandit have never reached a client either. Semgrep is a
dev dependency in exactly the same sense. The lesson worth keeping is that the
objection was stated as a fact about the installer without reading the installer.

**Consequence**: adding the next rule now means dropping a `.yaml` into
`scripts/qa/semgrep/` — it is picked up automatically, with no wiring, no new
script and no tests. That is the property DBF needs.

**Date**: 2026-08-13

### Decision 4: A NAME-keyed rule for the class shape rules cannot reach

**Context**: A false-negative audit found a second live instance —
`idle_housekeeping_advisor.py:148` calling `TranscriptReader.load()` to feed a
consumer that returns at the first boundary of a `reversed()` walk. No AST pair
rule can see it: there is no `.read()` in the expression, and the declared
bound lives in a different function.

**Decision**: Add a second rule keyed on the API NAME rather than a code shape,
bound to names proven to hold a reader so unrelated `Config.load()` calls are
untouched. The defining module is exempt.

**Why a name rule is still needed after Decision 3**: semgrep raised shape
coverage from 1/11 to 9/11, but this instance is not a shape miss at all. There
is no read expression to match — the cost is inside a method on a helper object.
A shape rule and a name rule cover genuinely different classes; choosing the
wrong handle yields a guard that is registered, runs, and is blind.

**Date**: 2026-08-13

### Decision 5: Accept 9/11 as the ceiling, having diagnosed the other 2

**Context**: The semgrep rules miss `a_deferred_slice` and
`b_deferred_slice_plain` — a whole-file read bound to a name, sliced later.

**Diagnosis, not a hedge**: a minimal three-rule probe isolated the cause.
`pattern-inside` with a `...` sequence fails to bind the read to the later
slice, and taint mode does not propagate into a subscript sink. The only
pattern form that DOES match is a bare `$X[-$N:]`, which would flag every
negative slice of every list in the repository.

**Decision**: Stop at 9/11. The two misses are the same deferred class the
hand-written checker also missed, and the one live instance of it
(`background_process_tracker.py`) is provably benign under Decision 2. Buying
those two shapes costs a false-positive generator on a gate that blocks
commits — the trade Decision 2 already refused once.

**Date**: 2026-08-13

## Success Criteria

- [x] ✅ The guard catches 9 of the 11 probed spellings, with the other 2
  diagnosed rather than left as an unknown (Decision 5)
- [x] ✅ Zero false positives across 417 files in `src/`, `scripts/`,
  `.claude/project-handlers/`
- [x] ✅ Runs fully offline — local `--config`, metrics off, no registry fetch
- [x] ✅ Byte accounting proves the fix: 2,396,089 bytes read before, 65,536
  after, marker still found
- [x] ✅ Full QA green at 21/21 (was 20/20)
- [x] ✅ Daemon restarts and reports RUNNING

## Risks & Mitigations

| Risk                                                        | Impact | Probability | Mitigation                                                                       |
| ----------------------------------------------------------- | ------ | ----------- | -------------------------------------------------------------------------------- |
| Rule is registered but blind (the Plan 00230 failure shape) | High   | Medium      | Byte-accounting test run against a reconstruction of the original defect         |
| Future widening reintroduces false positives                | Medium | Medium      | Blind spot and its rationale recorded in the rule file's own header              |
| Guard's own code trips other guards                         | Low    | Realised    | The repo's error-hiding audit caught a silent `except ValueError`; fixed at root |
| Guard passes green because semgrep is not installed         | High   | Low         | `run_semgrep_check.sh` exits 1 when the binary is absent — never a silent pass   |

## Delivery & Milestones

- Guard, wiring, instance fix and tests delivered together in `a7c799f1`
- Name-keyed rule and the `load_tail()` switch in `06b873c4`
- Plan and journal record of Phase 5 in `24e8d0be`
- Bespoke checker replaced by semgrep in `d868a087` (Phase 6, Decisions 3 and 5)
