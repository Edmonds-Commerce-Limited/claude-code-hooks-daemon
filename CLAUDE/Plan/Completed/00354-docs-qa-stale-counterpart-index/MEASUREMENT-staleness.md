# MEASUREMENT: counterpart staleness in the docs-qa EDIT path

Durable record of the two reproductions and the cost measurement that
decided the fix. Everything below was run, not reasoned about.

## 1. The mechanism

`untracked/docs-qa/index.json` stores, per document, the derived facts
(`links`, `quotes`, `block_hashes`, `block_locations`) alongside the
`mtime_ns` and `size` they were derived from.

Three entry points read it:

| Entry point             | Stage | Revalidates?                          |
| ----------------------- | ----- | ------------------------------------- |
| `build_and_save_corpus` | SWEEP | Yes — `stat()` per file before reuse  |
| `load_or_cold_corpus`   | EDIT  | No — parses the JSON verbatim         |
| `refresh_own_record`    | EDIT  | Only the ONE file being linted/edited |

So at EDIT stage every counterpart record is consumed exactly as the last
sweep left it. `refresh_own_record`'s docstring states this deliberately:
"Every OTHER document's record is left exactly as loaded — partner
staleness is accepted (that is the sweep's job)".

`duplicate-block`'s `_hash_index` builds `block_hash -> (path, start, end)`
straight from `corpus.documents`, so a stale counterpart record contributes
both a hash that may no longer exist and a line span that may no longer
mean anything.

## 2. Reproduction A — false positive (a citation to content that moved)

Sandbox project with one document, `CLAUDE/PLAN.md`, holding a Python
fence at lines 5-11.

1. `docs-qa --project-root <sandbox>` — sweep builds the index. Clean.
   The index records `CLAUDE/PLAN.md` with one block hash at lines 5-11,
   `size: 264`.
2. The fence is extracted into a new sibling `CLAUDE/EVIDENCE.md`, and
   `PLAN.md` is rewritten so the fence is replaced by a prose paragraph
   plus a three-item bullet list.
3. `docs-qa --lint <sandbox>/CLAUDE/EVIDENCE.md`:

```
Docs QA: 1 finding (0 block, 1 advise)
- [advise] duplicate-block [CLAUDE/EVIDENCE.md]: `CLAUDE/EVIDENCE.md:5-11`
  contains a structured block (fenced code, table, or list run) identical,
  after normalisation, to: `CLAUDE/PLAN.md:5-11`.
```

`CLAUDE/PLAN.md:5-11` at that moment holds:

```
The merge helper now lives in EVIDENCE.md. What remains here is a
plain prose list of the considerations:

- preserve the user's own keys
- never drop an unknown key
- report a conflict rather than guessing
```

The two share nothing. The finding sends a reader to a line range whose
content is unrelated, to fix a duplication that no longer exists.

## 3. Reproduction B — false negative (a real duplicate goes unreported)

Sandbox project with `CLAUDE/A.md` and `CLAUDE/B.md`, neither holding a
structured block.

1. Sweep builds the index. Both records carry empty `block_hashes`.
2. The SAME Python fence is added to both files on disk.
3. `docs-qa --lint <sandbox>/CLAUDE/A.md`:

```
Docs QA: 0 findings — CLAUDE/A.md is clean.
```

`refresh_own_record` gave `A.md` its new hash, but `B.md`'s cached record
still predates its fence, so `_hash_index`'s `len(paths) >= 2` test is
never satisfied and the genuine duplicate is silent. This is the quieter
half: nothing draws attention to it.

## 4. Cost measurement — why revalidation and not re-parsing

Measured against this repository's own corpus index (222 indexed
documents, 2833 KiB of markdown), on the machine the reproductions ran on:

| Pass                                                            | Cost      |
| --------------------------------------------------------------- | --------- |
| `stat()` every indexed document, compare `mtime_ns`+`size`      | 0.73 ms   |
| Re-read + re-parse every indexed document (blocks/links/quotes) | 1582.3 ms |

The EDIT path runs inside a PreToolUse budget on every documentation
`Write`/`Edit`, so the ~2000x difference decides it: revalidate by
`stat()`, re-parse only the records that actually disagree (0 of 222 in a
steady-state repo). Dropping the cross-file cache for single-file lint
would trade a rare wrong finding for a permanently slow common path.

Invalidating the whole index instead has the same detection cost — you
must still `stat()` everything to know something changed — and then
discards every still-valid record. `duplicate-block`'s cold-index rule
would turn that into complete silence for the check, which is strictly
worse than the false positive it set out to fix.

## 5. Post-fix measurement

`revalidate_corpus` against this repository's real index, immediately after
a sweep (so nothing has changed and nothing needs re-parsing):

| Metric                       | Value     |
| ---------------------------- | --------- |
| Indexed documents            | 225       |
| Revalidation pass (min of 9) | 0.82 ms   |
| Records reused by identity   | 225 / 225 |
| Records re-parsed            | 0         |

The steady-state cost matches the predicted `stat`-only pass, and every
untouched record is passed through by object identity rather than rebuilt.
A run taken while one document had genuinely changed measured 9.99 ms with
221 / 222 reused — i.e. the whole re-parse cost is attributable to the one
file that actually changed, which is the work the correctness fix exists to
do.

Both CLI reproductions above were re-run against the fixed code:

- Reproduction A now reports `0 findings — CLAUDE/EVIDENCE.md is clean`.
- Reproduction B now reports the duplicate, citing `CLAUDE/B.md:5-11`,
  which is where the fence genuinely is.

## 6. Other consumers of the cached index

Audited every check reading `context.corpus`:

| Check                | Stage(s)            | Cached counterpart state used | Exposed?                                   |
| -------------------- | ------------------- | ----------------------------- | ------------------------------------------ |
| `duplicate-block`    | EDIT, SWEEP         | `block_locations`             | **EDIT: yes** — reproduced both directions |
| `quote-source-stale` | EDIT                | `quotes` (reverse index)      | **Yes** — same shape, same cause           |
| `pointer-resolves`   | EDIT, SWEEP, STAGED | `links` (SWEEP only)          | No — SWEEP corpus is freshly revalidated   |
| `quote-drift`        | EDIT, SWEEP, STAGED | `quotes` (SWEEP only)         | No — SWEEP only, and re-reads content      |
| `at-import-census`   | EDIT, SWEEP         | path list (SWEEP only)        | No — SWEEP only, and re-reads content      |

The dividing line is the STAGE, not the check: any check consuming a
counterpart record at EDIT stage inherits the staleness, and no check
consuming one at SWEEP stage does, because `build_and_save_corpus`
revalidates. That is why the fix belongs in the corpus layer — fixing it
inside `duplicate-block` would leave `quote-source-stale` broken in the
same way, and would break again for the next EDIT-stage consumer added.

`pointer-resolves`' EDIT half reads no corpus at all; it resolves link
targets against the filesystem directly, which cannot go stale.
