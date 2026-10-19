# N516 and N517: the spend-meter status segment

Branch `worktree-n516-spend-segment`. Brief: `untracked/scratch/brief-n516.md`.

## N517 verdict: (a) benign, mis-scored by a size test

No session UUID is recorded here; "the session" is the one whose ledger held the owner's 47 (now 48) markers.

Evidence, from the real sub-agent transcripts under `~/.claude/projects/-workspace/<session>/subagents/` (probe
scripts in the worktree's `untracked/scratch/n517_*.py`):

1. All 48 markers are `subagent-context-budget` / `no-usage-in-tail`.
2. `read_tail` over each finished transcript now finds usage in **48 of 48**. The parser and the tail window are
   correct, so this is not (b).
3. Each marker's mtime is **0.06 to 0.10 s after the timestamp of that agent's first assistant record**, and before
   its second request. So every marker was written at the agent's first tool call. At that moment the first
   assistant record, the only carrier of `usage`, had not yet been flushed.
4. `read_tail` raised rather than returning "fresh" because of `FRESH_AGENT_MAX_BYTES` (256 KiB). A usage-free file
   counted as fresh only below that size. The bytes ahead of the first assistant record are now **351 to 430 KB** for
   every marked agent: the prompt, attachments (one of about 220 KB), and the new `api-request-shape`,
   `api-request-blob` and `api-request` records (about 150 KB). Across the session, 230 of 520 transcripts exceed
   256 KiB before their first usage. 25 such agents since the first marker were not marked; the likely reason is
   that the flush won the race on those agents.

Fix (`utils/transcript_tail.py`): fresh now means the whole file was read and holds **no real assistant record**,
whatever its size. An assistant record without `usage` still raises `NoUsageInTail`, so the review-B2 guard against a
renamed usage field survives. A file whose start lies past `MAX_WINDOW_BYTES` still raises. `FRESH_AGENT_MAX_BYTES`
is removed. The fix is in the shared reader, so `resume_guard`, `session_load`, `dispatch_tier` and
`spawn_rate_advisor` gain the same answer. Three B2 fixtures (tail, budget gate, resume guard) were 1 MB files of
`user` records. They now use assistant records with no usage, which is the shape a renamed field really produces.

What is lost: a format change that renames the record **type** `assistant` would now read as fresh. The 256 KiB rule
missed that change too, but only below 256 KiB.

Red (before the fix):

```
FAILED test_transcript_tail.py::TestMissPathIsBounded::test_a_first_call_transcript_over_256_kib_is_a_fresh_agent - NoUsageInTail: no usage in t...
FAILED test_transcript_tail.py::TestMissPathIsBounded::test_a_usage_free_assistant_record_is_unmeasured_even_when_small - Failed: DID NOT RAISE
FAILED test_subagent_context_budget.py::TestSoftBand::test_first_call_before_any_assistant_record_is_silent_and_not_unmeasured - assert 1 == 0
3 failed, 104 passed
```

Green: the 15 test files that touch the reader or its callers pass (1605 tests).

## N516: the segment

- **Unit `tok-eq`** (token equivalents). `tok` is the abbreviation a status-line reader already knows, and `-eq`
  marks the figure as not a plain token count. It is the documented term ("input-token equivalents") with the
  word "input" dropped: the weights cover output and cache traffic too, so "input" misled anyway. It costs 3
  characters over `ite`. The rejected options: `wtok` (as cryptic as `ite`), `≈tok` (reads as an approximate count,
  not a weighted one) and `tokens` (forbidden by the brief). The `spend` and `tier` CLI tables keep their `ite`
  column, because they carry a legend. `explain_segment` names the link (`hooks-daemon spend calls the same figure ite`).
- **`compact()`**: k has no decimal, M has one, G has two, and a trailing zero is dropped. Rounding is half up
  (Decimal), not Python's half-even. A figure that rounds to 1000 moves to the next scale (`999_500` gives `1M`, not
  `1000k`). `compact` has no caller outside `spend_meter.py`.
- Updated: the module docstring, `explain_segment` (it now also says `max` is in tokens, and that `unmeasured`
  counts agents), the acceptance-test text, `docs/guides/HANDLER_REFERENCE.md`, and the `spend_meter` comment in
  `.claude/hooks-daemon.yaml` and `.claude/hooks-daemon.yaml.example`. Not touched: released history
  (`config-changes/v3.70.0.yaml`, `v3.69.0-to-v3.70.0` release note 078).
- Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/002-spend-meter-readable-unit-and-first-call-unmeasured.md`.

Red (before the fix): 13 failed and 11 passed in `test_spend_meter.py`. Examples:
`'| Σ⚙ 64.5k ite' == '| Σ⚙ 65k tok-eq'`, `'277.5k' == '278k'`, `'999.5k' == '1M'` and `'1000M' == '1G'`.
Green: 24 passed.

The owner's reading now renders as `Σ⚙ 61.2M tok-eq · 1 live (1 opus) · max 278k · 47 unmeasured` (a test pins
it). After N517, the unmeasured part should seldom appear at all.
