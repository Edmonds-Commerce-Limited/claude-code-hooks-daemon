# Plan 00354: docs qa stale counterpart index

**Status**: Complete
**Created**: 2026-09-08
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Single Agent

## Overview

The docs-qa corpus index (`untracked/docs-qa/index.json`) caches, per
document, its `links`, `quotes`, `block_hashes` and `block_locations`
alongside the `mtime_ns` and `size` that identify the content those were
derived from. The SWEEP path (`build_and_save_corpus`) revalidates each
entry against `stat()` before reusing it. The EDIT path does not:
`load_or_cold_corpus` reads the JSON verbatim, and `refresh_own_record`
re-derives exactly one record — the file being linted or edited. Every
COUNTERPART record is consumed as-loaded, however old it is.

That is a documented decision (`refresh_own_record`: "partner staleness is
accepted — that is the sweep's job"), and it is wrong in both directions.
`duplicate-block` compares the linted file's blocks against every other
document's cached block set, so a counterpart whose content changed since
the last sweep produces a finding citing a `path:start-end` span that no
longer holds the cited block (false positive), while a counterpart that
GAINED a block since the last sweep makes a genuine new duplicate invisible
(false negative). Both were reproduced end-to-end through the real CLI —
see [MEASUREMENT-staleness.md](MEASUREMENT-staleness.md).

The exposure is not unique to `duplicate-block`. `quote-source-stale`'s
EDIT half derives its list of quoting documents from the same unvalidated
cached `quotes` field, so it has the identical shape. The fix therefore
belongs in the corpus layer, not in either check: revalidate the loaded
index against `stat()` before any EDIT-stage check consumes it.

## Goals

- `duplicate-block` at EDIT stage never cites a counterpart span whose
  on-disk content no longer contains that block.
- `duplicate-block` at EDIT stage reports a genuine duplicate against a
  counterpart that gained the block after the last sweep.
- `quote-source-stale` at EDIT stage names quoters from revalidated
  records, not from whatever the last sweep recorded.
- A counterpart deleted since the last sweep is dropped rather than cited.
- The EDIT path stays inside a PreToolUse budget: revalidation is bounded
  by a `stat()` per indexed document, and re-parses only what changed.
- A failing reproduction test exists for each direction BEFORE the fix, and
  drives the real `load → revalidate → check` path rather than a
  hand-built stale record.

## Non-Goals

- **Re-parsing every counterpart on every lint** (the "drop the cross-file
  cache for single-file lint" option). Rejected on measurement: re-reading
  and re-parsing all 222 indexed documents in this repo costs ~1582 ms
  against ~0.73 ms for a full `stat()` revalidation pass — a ~2000x
  regression on a path that runs inside a PreToolUse budget on every
  documentation `Write`/`Edit`. It would trade a rare wrong finding for a
  permanently slow common path.
- **Invalidating the whole index when any member changed.** Detecting
  "any member changed" costs the same full `stat()` pass as revalidating
  properly, then throws away every still-valid record; `duplicate-block`'s
  cold-index rule would degrade the check to complete silence. Strictly
  worse than revalidation for the same cost.
- **Discovering counterpart files created since the last sweep.** A record
  that has never been indexed cannot be revalidated — finding it needs the
  directory walk this plan rejects above. A duplicate against a
  brand-new never-swept file therefore stays invisible until the next
  sweep; that is the existing cold-index contract, and it is documented
  rather than fixed here.
- Changing `duplicate-block`'s advisory-only severity, or any check's
  block-eligibility.
- The SWEEP and STAGED stages. `build_and_save_corpus` already
  revalidates; `staged_context` reads git, not the index.

## Tasks

### Phase 1: Reproduction (RED)

- [x] ✅ **Task 1.1**: Test — EDIT-stage `duplicate-block` false positive.
  Build a real index via `build_and_save_corpus`, mutate a counterpart
  on disk so its block is gone, then run the EDIT stage through
  `load_or_cold_corpus` + `refresh_own_record`. Assert no finding cites
  the counterpart. Must fail before Phase 2.
- [x] ✅ **Task 1.2**: Test — EDIT-stage `duplicate-block` false negative.
  Same real-index setup; the counterpart GAINS the shared block after
  the index is built. Assert the duplicate IS reported. Must fail
  before Phase 2.
- [x] ✅ **Task 1.3**: Test — a counterpart deleted after the index was
  built is not cited as a duplicate partner.
- [x] ✅ **Task 1.4**: Test — EDIT-stage `quote-source-stale` names quoters
  from revalidated records (a document that stopped quoting the source
  is not named; one that started quoting it is).

### Phase 2: Corpus-layer revalidation (GREEN)

- [x] ✅ **Task 2.1**: Add `revalidate_corpus(corpus, project_root)` to
  `docs_qa/corpus.py`: per record, `stat()` the file; drop it when
  missing/unreadable, re-derive it when `mtime_ns`/`size` disagree,
  reuse it otherwise. A `cold` corpus is returned untouched (nothing
  to revalidate).
- [x] ✅ **Task 2.2**: Add `load_edit_corpus(...)` composing
  `load_or_cold_corpus` → `revalidate_corpus` → `refresh_own_record`
  as the single supported EDIT-stage entry point. The order is
  load-bearing and easy to get wrong: revalidating AFTER
  `refresh_own_record` would re-read the edited file from disk and
  discard the would-be content the EDIT stage exists to judge.
- [x] ✅ **Task 2.3**: Route both EDIT-stage callers — `cmd_docs_qa`'s
  `--lint` branch and `DocsQaEditHandler.handle` — through
  `load_edit_corpus`.
- [x] ✅ **Task 2.4**: Correct the stale contract prose in
  `refresh_own_record`'s docstring and the `corpus.py` module
  docstring, which currently state that partner staleness is accepted.

### Phase 3: Verification

- [x] ✅ **Task 3.1**: Re-run both CLI reproductions from
  MEASUREMENT-staleness.md and confirm each now reports correctly.
- [x] ✅ **Task 3.2**: Re-measure the revalidation pass against this repo's
  real index and record it in MEASUREMENT-staleness.md.
- [x] ✅ **Task 3.3**: `./scripts/qa/llm_qa.py all` green, coverage gate
  (95%) held.

## Success Criteria

- [x] Every Phase 1 test fails against the pre-fix code and passes after.
- [x] Both CLI reproductions behave correctly after the fix.
- [x] Revalidation of this repo's index stays within single-digit
  milliseconds (0.82 ms for 225 documents, 0 re-parses).
- [x] QA green on every check this change can affect: `format`, `lint`,
  `type_check` clean; 19769 tests passing at 95.2% coverage (gate 95%),
  `corpus.py` itself at 98.26%. The residual failures are environmental or
  pre-existing and are recorded below.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00354-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Defect reproduced end-to-end through the real CLI in both directions, and
  the cost of each candidate fix measured, before any code changed —
  [MEASUREMENT-staleness.md](MEASUREMENT-staleness.md).
- `revalidate_corpus` + `load_edit_corpus` land in `docs_qa/corpus.py`; both
  EDIT-stage callers routed through the composed entry point.

### Archive move is deferred to the merge, deliberately

`plan-qa --lint` reports `terminal-placement-hint` (ADVISE) against this
folder: a Complete plan normally ships its `git mv` into `Completed/` in the
same commit as the status flip. That move is deferred here because it also
requires reconciling the README's shared statistics block (Completed,
Active, and the folder-to-number totals), and this work was done on an
isolated worktree branch alongside another agent that is adding its own
README row. Both agents editing those counters guarantees a merge conflict
on lines neither of them is really changing. The README edit here is
therefore confined to this plan's own Active row; archiving and the counter
reconciliation belong to whoever merges, when the true post-merge counts are
known.

### Residual QA failures (not introduced here)

Recorded so a later reader does not re-investigate them:

- 13 acceptance/integration errors (`test_stop_hook_hard_block`,
  `test_playbook_harness`, `test_tool_use_error_recovery`,
  `test_forwarder_socket_stdin`) and the `smoke_test` tool abort on the same
  precondition: "Daemon not running". This work was done in an agent
  worktree with no daemon socket, and restarting the daemon was out of
  scope.
- 8 `error_hiding` violations, and the two
  `tests/unit/qa/test_audit_error_hiding.py` self-scan tests that assert on
  them, all sit in `install/settings_merge.py`, `scripts/upgrade.sh` and
  `scripts/upgrade_version.sh` — files this change never touches, so their
  content is identical to HEAD and the findings predate it.
- `semgrep` is not installed in this environment; `project_handlers`
  collects no tests here.
