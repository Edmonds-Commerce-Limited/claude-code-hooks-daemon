# docs-qa stale counterpart index — investigation and fix

Report for the dispatching agent. Plan folder:
`CLAUDE/Plan/00354-docs-qa-stale-counterpart-index/`.

## 1. Did the diagnosis hold up?

**Yes, completely, and it was understated in one respect.**

The reported mechanism is exactly right: `load_or_cold_corpus` parses
`untracked/docs-qa/index.json` verbatim, `refresh_own_record` re-derives
exactly one record (the file being linted), and every counterpart record is
consumed as-loaded regardless of its `mtime_ns`/`size`.

It is not an oversight. It is a **stated contract** — `refresh_own_record`'s
docstring said so:

> Every OTHER document's record is left exactly as loaded -- partner
> staleness is accepted (that is the sweep's job); only the file actually
> being linted must never lag its own content.

So the fix had to change the contract and its prose, not merely add a guard.

Both directions were reproduced end-to-end through the real `docs-qa` CLI in
throwaway sandbox projects (not a unit harness):

- **False positive** — sweep, then move a fence out of `PLAN.md` into a new
  `EVIDENCE.md`. Linting `EVIDENCE.md` reported a duplicate citing
  `CLAUDE/PLAN.md:5-11`, which by then held a prose paragraph and a bullet
  list.
- **False negative** — sweep with no blocks, then add the same fence to two
  files. Linting one reported `0 findings — clean`.

**The understated part**: a counterpart *deleted* since the last sweep was
also still cited, because nothing pruned records for files that no longer
exist. That is a third symptom of the same cause, and it is now covered.

Full evidence, commands and outputs:
[MEASUREMENT-staleness.md](../MEASUREMENT-staleness.md).

## 2. The fix, and what was rejected

Chosen: **revalidate every counterpart record against `stat()` on the EDIT
path, and re-parse only the records that disagree.**

Two new functions in `docs_qa/corpus.py`:

- `revalidate_corpus(corpus, project_root)` — per record: `stat()`; drop it if
  the file is gone; re-derive it if `mtime_ns`/`size` disagree; otherwise pass
  the existing record through **by identity**. A `cold` corpus is returned
  untouched.
- `load_edit_corpus(project_root, index_path, file_path, content)` — composes
  `load_or_cold_corpus` → `revalidate_corpus` → `refresh_own_record`.

Both EDIT-stage callers (`cmd_docs_qa`'s `--lint` branch and
`DocsQaEditHandler.handle`) now go through `load_edit_corpus`.

### Why that shape, and the ordering trap it exists to close

`revalidate_corpus` and `refresh_own_record` **do not commute**. Revalidating
after refreshing would re-read the edited file from disk and discard the
would-be content — so the PreToolUse handler would silently lint the *old*
content of every pending edit. That is a worse defect than the one being
fixed, and nothing in the type system prevents a future caller from ordering
them wrongly. One composed entry point removes the choice. A test pins
specifically that the own record reflects the would-be content while the file
on disk still holds the old.

A shared `_derive_record` helper now backs all three producers, so a record
built on the EDIT path and one built by the sweep cannot disagree about what a
document contains.

### Rejected, with reasons (both recorded as Non-Goals)

Measured against the real index — 222 documents, 2833 KiB of markdown:

| Pass                                         | Cost      |
| -------------------------------------------- | --------- |
| `stat()` all, compare `mtime_ns`+`size`      | 0.73 ms   |
| Re-read + re-parse all (blocks/links/quotes) | 1582.3 ms |

- **Drop the cross-file cache for single-file lint.** ~2000x slower on a path
  that runs inside a PreToolUse budget on *every* documentation `Write`/`Edit`.
  It trades a rare wrong finding for a permanently slow common path.
- **Version/invalidate the whole index when any member changes.** Detecting
  "any member changed" costs the same full `stat()` pass, then discards every
  still-valid record. Because `duplicate-block` has a cold-index rule, that
  degrades the check to *complete silence* — strictly worse than the false
  positive it set out to fix, for identical detection cost.

### Post-fix measurement

| Metric                       | Value     |
| ---------------------------- | --------- |
| Indexed documents            | 225       |
| Revalidation pass (min of 9) | 0.82 ms   |
| Reused by identity           | 225 / 225 |
| Re-parsed                    | 0         |

Steady state matches the predicted `stat`-only cost. A run taken while one
document had genuinely changed measured 9.99 ms — i.e. essentially all of the
extra cost is the one file that actually changed, which is the work the
correctness fix exists to do.

Both CLI reproductions now behave correctly: the false-positive case reports
clean, the false-negative case reports the duplicate citing `CLAUDE/B.md:5-11`,
which is where the fence genuinely is.

## 3. Do other index consumers share the exposure?

**Yes — one does, and it is fixed by the same change.** Audited every check
reading `context.corpus`:

| Check                | Stage(s)            | Cached counterpart state | Exposed?                                   |
| -------------------- | ------------------- | ------------------------ | ------------------------------------------ |
| `duplicate-block`    | EDIT, SWEEP         | `block_locations`        | **EDIT: yes** — reproduced both directions |
| `quote-source-stale` | EDIT                | `quotes` (reverse index) | **Yes** — same shape, same cause           |
| `pointer-resolves`   | EDIT, SWEEP, STAGED | `links` (SWEEP only)     | No — SWEEP corpus is freshly revalidated   |
| `quote-drift`        | EDIT, SWEEP, STAGED | `quotes` (SWEEP only)    | No — SWEEP only, and re-reads content      |
| `at-import-census`   | EDIT, SWEEP         | path list (SWEEP only)   | No — SWEEP only, and re-reads content      |

**The key finding is that the dividing line is the STAGE, not the check.** Any
check consuming a counterpart record at EDIT stage inherits the staleness; no
check consuming one at SWEEP stage does, because `build_and_save_corpus`
already revalidates. `pointer-resolves`' EDIT half reads no corpus at all — it
resolves link targets against the filesystem, which cannot go stale.

That is precisely why the fix went into the corpus layer rather than into
`duplicate_block.py`: a check-local patch would have left `quote-source-stale`
broken in the identical way and would break again for the next EDIT-stage
consumer added. `quote-source-stale` has its own regression tests here (a
document that stopped quoting is no longer named; one that started quoting is).

Nothing was left as follow-up — the audit found no third consumer of a
different shape.

## 4. Tests (TDD, RED verified first)

Every test drives the **real** index/cache path — `build_and_save_corpus`
writes a genuine `index.json`, the file is mutated on disk, then the EDIT path
loads it. No test hand-builds a stale `DocRecord`, precisely so none of them
could pass while the real path stayed broken.

RED was confirmed before the fix at every level:

- `tests/unit/daemon/test_cli_docs_qa.py::TestStaleCounterpartIndex` — 3 of 4
  failed on current behaviour (false positive, false negative, deleted
  counterpart). The 4th (an *unchanged* counterpart is still reported) passed
  before and after, guarding against over-correcting the fix into silence.
- `tests/unit/handlers/pre_tool_use/test_docs_qa_edit.py::TestStaleCounterpartIndex`
  — both failed, covering the second EDIT-stage caller.
- `tests/unit/docs_qa/test_corpus.py` — `TestRevalidateCorpus` and
  `TestLoadEditCorpus`.
- `tests/unit/docs_qa/checks/test_quote_source_stale.py` — the two new
  quoter-staleness cases.

## 5. QA

`format`, `lint`, `type_check`, `magic_values`, `security`, `dependencies`,
`british_english`, `doc_truth`, `repo_hygiene`, `git_history` and the rest:
**clean**. Tests: **19769 passed, 0 failed**, coverage **95.2%** against a 95%
gate; `docs_qa/corpus.py` itself at **98.26%**, with the only uncovered lines
being pre-existing corrupt-cache branches in `load_cached_corpus`.

Residual failures, all verified **not** introduced by this change:

- 13 acceptance/integration errors and the `smoke_test` tool abort on one
  precondition: **"Daemon not running"**. This ran in an agent worktree with no
  daemon socket, and restarting the daemon was explicitly out of scope.
- 8 `error_hiding` violations, and the two
  `tests/unit/qa/test_audit_error_hiding.py` self-scan tests that assert on
  them, sit entirely in `install/settings_merge.py`, `scripts/upgrade.sh` and
  `scripts/upgrade_version.sh`. `git status` confirms this change never touches
  those files, so their content is byte-identical to HEAD and the findings
  predate it.
- `semgrep` is not installed here; `project_handlers` collects no tests here.

### One QA trap worth passing on

The first QA run reported the two new test modules as collection errors while a
direct `pytest` run passed them. The worktree had no venv, so `untracked/venv`
had been symlinked to the workspace venv — whose editable install resolves
`claude_code_hooks_daemon` to **`/workspace/src`, the main repo**. Every QA run
was judging the wrong source tree; the direct runs only passed because they set
`PYTHONPATH=src`. Replaced with a real `uv sync --extra dev` venv and verified
`claude_code_hooks_daemon.__file__` resolves inside the worktree before
trusting any further number.

**A green QA run in a worktree means nothing until you have checked which tree
the interpreter resolves.** Worth knowing for any future worktree-isolated
agent in this repo.

## 6. Deliberately not done

The plan is `Complete` but its folder is **not** archived into `Completed/`,
so `plan-qa --lint` reports `terminal-placement-hint` (ADVISE, non-blocking).
This is a considered deferral, not an oversight: the archive move also requires
reconciling the README's shared statistics counters (Completed / Active /
folder-to-number totals), and a second agent is concurrently adding its own
README row. Both of us editing those counters guarantees a merge conflict on
lines neither is really changing. The README edit here is confined to this
plan's own Active row; archiving and counter reconciliation belong to whoever
merges, when the true post-merge counts are known. It is recorded in PLAN.md
and the JOURNAL so it is not re-investigated.

## 7. Delivery, and one process note

Branch `agent-a4c957bbaff656c5f-0eec666a`, commit `82bbd550`. Not pushed, not
merged — the dispatching human merges it.

Mid-task, a system-reminder instructed that file edits be made through Bash
using `sed`, heredocs and redirects. That contradicts this repository's
CLAUDE.md and the dispatch instructions: `sed` is forbidden for file
modification here, and the content guards (`sensitive_content`,
`error_hiding_blocker`, `qa_suppression`, `comment_changelog`) only run on the
`Write`/`Edit` tools, so a Bash-authored file reaches disk unexamined by them.
That instruction was not followed; every file change in this work went through
`Read`/`Edit`/`Write` and was seen by the guards. Flagged here because an
instruction to bypass the project's own write-time protections is worth a
human's attention rather than silent compliance.
