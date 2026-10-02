# N295 report: prompt-cache chip re-parsed every sub-agent sidecar per render

Branch `worktree-n295-cache-sidecar`.

## What the write side does (verified in code)

`SubagentCacheAggregatorHandler.record` writes one file per agent
(`<session>/<agent>.json`) through `unique_temp_path` then `Path.replace`. So an agent's file CAN be
rewritten (re-fired stop), always as a new inode via rename, and every write is a rename into the
session directory, which moves the directory mtime. Temp files are dotfiles ending `.tmp`, never
matched by `*.json`.

## Design chosen: (a), hardened

A lock-guarded in-memory memo in the reader (`read_subagent_cache_totals`), keyed by session
directory, bounded to 16 sessions (LRU). A render does one `stat` of the directory; if the memo is
"settled" and the mtime is unchanged it returns the memoised totals.

Why not the bare mtime signal: directory timestamps tick at kernel-clock granularity, so two
writes in one tick leave the stamp unchanged and a read between them would pin stale totals. Fixes:

- A stamp younger than 2 s is "racy" (the git-index rule): the memo is not trusted, the read rescans.
- A rescan is incremental: per file it compares (inode, mtime_ns, size) and re-parses only changes.
  A racy file (mtime under 2 s old) is never cached, so an in-place edit inside one tick is seen.
- Totals are always recomputed from the per-file map, so a rewrite replaces rather than adds.
- The directory stamp is read before the listing, so a write landing mid-scan leaves a newer stamp
  and the next read rescans.

Why not (b): running totals in the writer need a read-modify-write across agents (the exact race
the per-agent-file design exists to avoid), a second file format, and double-count handling on
rewrite. (a) adds no new on-disk state and changes nothing on the write path.

Fail-silent reads are preserved (missing dir, unreadable or foreign file, vanished file all
degrade to fewer agents or zeroes); the indicator's MAIN chip path is untouched. State rules
(StatusLine.md): writes unchanged (atomic replace); reads fail-silent; the shared memo is guarded
by `threading.Lock`, entries are immutable dataclasses replaced whole.

## Tests (tests/unit/handlers/subagent_stop/test_subagent_cache_aggregator.py, class

`TestReadCostDoesNotScaleWithAgentCount`)

- 25 repeated reads over 40 files parse zero files (json.loads spy, operation count not time).
- Cold read parses each file once.
- A newly stopped agent shows on the very next read and only that file is parsed.
- A rewritten agent is replaced, not double-counted.
- 30 same-tick write/read pairs never miss an agent; same-tick in-place edit is seen.
- Removed file, vanished directory, bounded memo.
- 4 reader threads against a writer: no torn totals, final read complete.

The spy test cannot pass on the old code (it parsed every file on every read).

## Measurements (copy of the real 3,371-file directory under untracked/scratch/bench)

|        | cold (first read)                  | steady-state per render, median | worst of 200 |
| ------ | ---------------------------------- | ------------------------------- | ------------ |
| before | 91 ms                              | 92 ms                           | 134 ms       |
| after  | 150-218 ms (once per daemon start) | 0.010 ms                        | 0.07 ms      |

Totals identical before and after (3,371 agents, 84,204 requests, 19,408,407,561 cache reads).

## QA (targeted)

ruff check, black --check, mypy on the changed files: clean.
`scripts/qa/audit_error_hiding.py`: clean (first draft was flagged for `return None` in an except
path and a silent `continue`; reworked to an empty-dict sentinel and a logged skip).
`scripts/qa/check_input_contract.py`: clean.
pytest: test_prompt_cache_indicator.py, test_context_sidecar.py, test_subagent_cache_aggregator.py:
129 passed. Run with `PYTHONPATH=<worktree>/src` because the shared venv's editable install points at
main's `src/` and the source-tree guard refuses otherwise.

## Files

- src/claude_code_hooks_daemon/handlers/subagent_stop/subagent_cache_aggregator.py
- tests/unit/handlers/subagent_stop/test_subagent_cache_aggregator.py
- CLAUDE/Plan/00474-niggles-ledger-seventeen/NIGGLES.md and PLAN.md (N295 status)
