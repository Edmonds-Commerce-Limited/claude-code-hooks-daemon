# Plan 00232: Stream the Transcript Archive

**Status**: Complete
**Created**: 2026-08-13
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

The PreCompact `transcript_archiver` handler reads an entire session transcript
into one Python string and embeds it verbatim in a single JSON field. Measured
on this project's own transcripts (72–74 MB JSONL), the handler produces an RSS
spike of roughly **660 MB** — around 9x the file size.

The amplification is not mysterious, and it is worth writing down because it is
what makes "just stream it" the fix rather than a micro-optimisation:

1. `source.read_text()` materialises the file as one `str`. CPython stores a
   string in the widest code unit any character needs, so a **single** non-BMP
   character anywhere in a 72 MB transcript — one emoji, and this project's
   transcripts are full of them — promotes the entire string to 4 bytes per
   character. 72 MB becomes ~288 MB.
2. `redact_text()` returns a new string, so the peak holds two copies.
3. `json.dump()` escapes that string into an encoder buffer, holding a third.

This fires precisely when memory is least available: PreCompact, which is
Claude Code's response to a context window that is already full.

JSONL is line-oriented and the archive is a verbatim copy, so the whole-file
read buys nothing. Streaming line by line makes peak memory a function of the
longest single entry rather than of the transcript.

## Goals

- Make archive memory O(longest line), not O(file)
- Keep the archive a faithful, complete record — no sampling, no truncation
- Preserve the Plan 00201 redaction guarantee exactly
- Add a guard for the class, per Standard 15 (see Decision 3)

## Non-Goals

- Compressing archives, or changing the Plan 00181 retention budget
- Touching `TranscriptReader` — Plan 00177 already bounded the read path;
  this is the write path
- Stripping emoji from the archive. It was considered and rejected in
  Decision 2 — it corrupts a record, and does not even solve the problem

## Context & Background

Plan 00231 built a semgrep guard for the bounded-intent/unbounded-read class
and deliberately scoped it to reads that contradict a **declared** bound. This
defect declares no bound, so that guard cannot see it and was never expected
to. It is the adjacent class: a read that is unbounded because its *source* is
unbounded by construction. Transcripts only ever append.

A false-negative audit during Plan 00231 confirmed the string is never parsed,
split, indexed or sliced — it is copied verbatim into one JSON field — and
found no programmatic consumer of these archives anywhere in `src/` or
`scripts/`. Independently re-verified before filing this plan: the only readers
are `skills/hooks-daemon/report.md` (which instructs an agent to *read* archive
files) and `daemon/cli.py`'s disk-usage row (directory-level, format-blind).
The envelope is therefore free to change.

## Tasks

### Phase 1: Prove the premise before changing anything

- [x] ✅ **Task 1.1**: Confirm line-by-line redaction is EQUIVALENT, not merely
  similar — `redact_text` applies per-term `re.escape`d substitutions with no
  cross-line state, and `load_secret_terms` strips each line, so a term can
  never contain a newline
- [x] ✅ **Task 1.2**: Write a failing peak-memory accounting test that fails
  against the current whole-file implementation — measured 51.6 MB peak on an
  8.5 MB fixture (6x), corroborating the field ratio

### Phase 2: Stream the archive

- [x] ✅ **Task 2.1**: Rewrite the archive write path to stream line by line
- [x] ✅ **Task 2.2**: Redact per line, preserving the Plan 00201 guarantee
- [x] ✅ **Task 2.3**: Decode with `errors="replace"` so a malformed transcript
  degrades instead of raising `UnicodeDecodeError`, which the handler's
  `except OSError` never caught
- [x] ✅ **Task 2.4**: Redact the archive HEADER too — see Decision 4, a leak
  found while writing this code rather than anticipated by the plan

### Phase 3: Format change and its consequences

- [x] ✅ **Task 3.1**: Emit `.jsonl` — a metadata header line, then the
  transcript lines (Decision 1)
- [x] ✅ **Task 3.2**: Ensure retention still prunes pre-existing `.json`
  archives, so the format change cannot strand them unbounded
- [x] ✅ **Task 3.3**: Update `report.md`, which points a reader at these files
  — it now says how to SAMPLE an archive rather than read one whole

### Phase 4: Guard the class (DBF)

- [x] ✅ **Task 4.1**: Add a semgrep rule for whole-file reads of a transcript
  path (Decision 3)
- [x] ✅ **Task 4.2**: Prove the rule is NOT vacuous by running it against the
  pre-fix code — the first draft caught ZERO of four planted defects
- [x] ✅ **Task 4.3**: Make that proof permanent and automatic rather than a
  one-off manual check (Decision 5)

### Phase 5: Verify

- [x] ✅ **Task 5.1**: Full QA green (21/21, 12,678 tests, 95.3% coverage);
  daemon restarts RUNNING
- [x] ✅ **Task 5.2**: Exercise the real PreCompact path end to end against a
  large transcript, not just unit tests — 74.9 MB through the production hook
  wrapper and the live daemon

## Technical Decisions

### Decision 1: A JSONL archive, not a JSON envelope

**Context**: Streaming needs the transcript out of a single JSON string field.

**Options considered**:

1. Keep `.json`, stream the field as a JSON array of lines.
2. Emit `.jsonl`: a metadata header line, then the transcript lines verbatim.

**Decision**: Option 2. Both fix the memory cost, but Option 2 also removes the
JSON escaping entirely, and the result is greppable. That matters concretely:
`report.md` tells an agent to open these files during bug triage, and today it
is handed one enormous escaped blob. The source is JSONL; the archive being
JSONL is the honest representation.

**Date**: 2026-08-13

### Decision 2: Do not strip emoji

**Context**: Emoji are what trigger CPython's 4-bytes-per-character promotion,
so removing them was raised as a cheaper fix.

**Decision**: Rejected on three independent grounds, any one sufficient. It
**corrupts the record** — an archive exists to be faithful, and emoji carry
meaning in this project's own conversations. It **does not avoid the cost**:
finding the emoji means materialising the string first, which IS the spike. And
it only reduces 660 MB to roughly 220 MB — still O(file), so the defect
survives at a smaller constant while the archive is now wrong.

**Date**: 2026-08-13

### Decision 3: Guard the source, since there is no declared bound

**Context**: Plan 00231's rule keys on a bound contradicting a read. This
defect declares no bound, so that rule is silent by design, not by accident.

**Decision**: Add a rule keyed on the SOURCE being known-unbounded — a
whole-file read of a transcript path. This mirrors Plan 00231 Decision 4, which
reached for a name-keyed rule when the shape rule provably could not see the
instance. It stays narrow: a transcript path is unbounded by construction
because transcripts only append, which is a fact about the data rather than a
guess about file size.

**Date**: 2026-08-13

### Decision 4: Redact the archive HEADER, not only the body

**Context**: Found while rewriting the write path, not anticipated when this
plan was filed. The handler redacted the transcript CONTENT and wrote the
source path beside it verbatim.

**Why that is a real leak, not a theoretical one**: a transcript lives at
`~/.claude/projects/<slug-of-project-path>/<uuid>.jsonl`. The slug is derived
from the project path, so a path-shaped secret term appears there in exactly
the spelling `secret_redaction._slug_variant` was written to catch — that
helper exists because this repository's own history proved the spelling real.
`secret_redaction`'s module docstring names "a transcript archive" as a surface
a term must never reach, so this was a gap in a guarantee already claimed.

**Decision**: Redact the header through `redact_structure` before writing.
Fixed here rather than filed, per the dogfooding rule: it is a live leak in the
exact code being rewritten, and deferring it would ship another archive with
the path in the clear.

**Date**: 2026-08-13

### Decision 5: Automate the non-vacuity proof, do not just perform it once

**Context**: Task 4.2 required proving the new rule actually fires. The first
draft of the rule fired on **zero of four** planted defects: a `pattern-either`
nested inside a `patterns` block does not bind its metavariables. The rule
still loaded, still ran, and still reported a clean tree.

**Decision**: Keep the probe as a permanent fixture plus a test, rather than
deleting it after a one-off manual check. A semgrep rule has no compiler and no
type checker — a typo degrades it to silence, and silence is indistinguishable
from success. Expectations live as `# EXPECT-HIT` / `# EXPECT-CLEAN` markers in
the fixture rather than duplicated in the test, because a duplicated list
drifts and a drifted list is how the guard goes quiet again.

**Consequence recorded in the rule file itself**: its branch structure is
load-bearing, with a comment saying so and why, so a future tidy-up that
"simplifies" the branches gets a warning at the point of temptation.

**Date**: 2026-08-13

## Success Criteria

Measured on this project's own 74.9 MB session transcript:

| stage                  | peak allocation | ratio to file |
| ---------------------- | --------------- | ------------- |
| before (`read_text()`) | 673.5 MB        | 8.99x         |
| after (streaming)      | 0.7 MB          | 0.0097x       |

- [x] ✅ Peak memory bounded by the longest line (0.1 MB), not the file — a
  **922x** reduction, and the 8.99x independently confirms the ~660 MB field
  figure this plan was filed on
- [x] ✅ The archive is faithful — verified against the live transcript as an
  exact prefix, with all 264 differing lines explained by redaction and ZERO
  unexplained
- [x] ✅ Redaction preserved: per-line output identical to whole-text redaction
- [x] ✅ Legacy `.json` archives still pruned, sharing one budget
- [x] ✅ New semgrep rule fires on all four planted defects, is silent on the
  two correct ones, and is silent on the fixed tree
- [x] ✅ Full QA green (21/21); daemon RUNNING

## Risks & Mitigations

| Risk                                                   | Impact | Probability | Mitigation                                                                       |
| ------------------------------------------------------ | ------ | ----------- | -------------------------------------------------------------------------------- |
| Per-line redaction differs from whole-text redaction   | High   | Low         | Terms cannot contain newlines (`load_secret_terms` strips); pinned by a test     |
| Format change strands legacy `.json` archives unpruned | Medium | Medium      | Retention glob covers both extensions, sharing one budget                        |
| New guard is registered but blind (Plan 00230 shape)   | High   | Medium      | Run the rule against the pre-fix source and require a hit                        |
| A single transcript line is itself huge                | Low    | Medium      | Bounded by one entry rather than the file — accepted, recorded here as the floor |

## Delivery & Milestones

- (pending)
