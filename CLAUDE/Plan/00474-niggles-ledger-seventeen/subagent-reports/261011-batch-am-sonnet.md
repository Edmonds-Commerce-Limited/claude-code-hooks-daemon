# Batch AM report: N330 (spend_limit) and N361 option A (registry block)

Branch `worktree-batch-am-usage-registry`. Two commits; nothing merged or pushed.

## N330 adopt: `rate_limits.spend_limit`

**The docs differ from the write-up in one respect.** `remote-docs/code.claude.com/docs/en/statusline.md`
("Spend limit fields") says `rate_limits.spend_limit.used_percentage` runs from 0 to 100 "or above 100 once you
exceed the limit". The existing window parser rejects anything over 100, so reusing it as is would have dropped
exactly the over-limit case. The spend window therefore gets its own admit-over-100 flag; the subscription windows
keep the 0..100 rule. `used_usd`, `limit_usd` and `period` are documented as optional and are not read.

- `core/usage_snapshot.py`: `UsageSnapshot.spend_limit` (third window, default `None`), parsed, persisted to
  `usage-snapshot.json`, read back, and expired at `resets_at` like the other two. A spend-only payload (a gateway
  session with no subscription windows) yields a snapshot. `highest_used_percentage()` still covers only 5h/7d, so
  the usage ceiling and pause gates are unchanged (a dollar budget is not a subscription window). `latest_usage()`
  needed no change.
- `handlers/status_line/usage_indicator.py`: a third chip labelled `$` beside 5h/7d, same colour bands, compact
  below the warn level (`$5%`), spaced with countdown at or above it (`$ 62% 3h 0m`), `$ 140%` on red when over.
  Hidden when absent; malformed data is dropped at parse time so the segment never sees it. The segment
  explanation names the chip.
- The old test `test_spend_limit_and_unknown_keys_are_ignored` asserted the opposite of the adoption; it is now
  `test_unknown_keys_are_ignored`.

TDD red, before the implementation (`tests/unit/core/test_usage_snapshot.py`): `7 failed, 59 passed`, e.g.
`AttributeError: 'UsageSnapshot' object has no attribute 'spend_limit'` and
`TypeError: UsageSnapshot.__init__() got an unexpected keyword argument 'spend_limit'`.
Indicator (`tests/unit/handlers/status_line/test_usage_indicator.py`): `5 failed, 91 passed`
(`TestSpendLimitChip`, e.g. `assert '$' in ('📈', '5h', ...)`).

## N361 option A: commit-time block on a registry entry that is not visibly fake

- `docs_qa/checks/unlisted_fake_value.py` gains a STAGED stage (the check was EDIT + SWEEP). When the commit
  records `.claude/fake-values.yaml` (not a deletion), it parses the registry as the commit will record it
  (`recorded_text`, so pathspec commits read the working tree) and emits a `Severity.BLOCK` finding for each entry
  that fails `FakeValuesRegistry.not_visibly_fake()`. A staged registry that cannot be parsed is also BLOCK (every
  guard that reads it raises on it).
- **Only entries this commit adds or changes are judged.** Entries already failing in HEAD are not re-blamed,
  following the "BLOCK only what a commit introduced" rule `plan_workflow.qa.commit_gate_mode` was ratcheted on.
- `utils/fake_values.py`: `parse_fake_values(text, source)` factored out of `load_fake_values` (no behaviour change).
- **It uses the existing gate and rule ID.** `DocsQaCommitGateHandler` (R-DOCS-QA-COMMIT) already runs every
  STAGED check and denies on a BLOCK finding whose resolved mode is `block`. No new rule ID, so no new explain-rule
  entry or acceptance test is needed; the gate's `get_claude_md` text names the check.
- **Config change, flagged:** the project gate's default is `documentation.qa.commit_gate_mode: warn`, so a BLOCK
  finding would only advise. `.claude/hooks-daemon.yaml` now sets `documentation.qa.check_modes.unlisted-fake-value: block`, the same mechanism `unenforced-approval-gate` already uses. Not touched: `.claude/ccy/`, `settings*.json`,
  the block-word list. Another project that wants the block sets the same key; the check's default stays advisory
  there.
- **Every current entry passes.** `.claude/fake-values.yaml` holds 33 values in 7 kinds (12 session-uuid, 3 each in
  email-address, password, api-token, hostname, person-name, home-path). `not_visibly_fake()` returns `[]` for all of
  them, asserted by `test_the_shipped_registry_would_not_be_denied` (and the older
  `test_the_shipped_registry_is_prefilled_and_entirely_visibly_fake`). None would fail.
- **The substring heuristic is unchanged and still weak.** `fake` anywhere, or one character repeated 8 times,
  passes: `real-token-fake` or a real 40-hex token ending in `0000000000` would clear the gate. The N361 write-up
  already records this residual and says to tighten it only if the registry takes outside entries; I did not tighten
  it (out of scope, and the ruling named the existing heuristic).

TDD red: the new `TestStagedRegistry` tests first failed at collection with
`ImportError: cannot import name 'parse_fake_values' from 'claude_code_hooks_daemon.utils.fake_values'`; after that
helper existed the STAGED stage was the only missing piece (`test_registers_edit_staged_and_sweep` expects three
stages). Gate-level test in `tests/unit/handlers/pre_tool_use/test_docs_qa_commit_gate.py` shows the same staged
registry DENYs with `check_modes: {unlisted-fake-value: block}` and ALLOWs (advisory) without it.

## QA (targeted only)

- `llm_qa.py changed`: 36/40 passed. magic_values, lint, type_check, pyright, error_hiding, docs_qa (0 findings),
  hook_contract, handler_reference, generated_doc_drift and the rest green.
- `format`: black auto-fixed `core/usage_snapshot.py` and `docs_qa/checks/unlisted_fake_value.py` during the run;
  the fix is in the commit and `black --check` over `src` and the touched tests then reported 721 files unchanged.
- `plan_qa`: one ADVISE `journal-freshness` finding about plan 00495, not touched by this batch.
- `changed_tests`: 2624 passed, 0 failed, 5 skipped, but the run is marked failed for two files with no test map
  rule (`.claude/hooks-daemon.yaml`, `utils/fake_values.py`, both `[too-broad]`). I ran their consumers by hand:
  `tests/unit/utils/test_fake_values.py`, `tests/unit/qa/test_check_sensitive_content_fake_values.py`,
  `tests/unit/handlers/pre_tool_use/test_sensitive_content_fake_values.py`, `tests/unit/remote_docs`,
  `tests/unit/docs_qa`, the usage tests and the gate test: 1712 passed.
- mypy on the four touched source files: no issues.
- Not caused by this batch: `tests/unit/config/test_handler_options_accessor.py::test_no_source_file_reads_handler_options_by_hand`
  (flags `install/effective_handlers.py:225`) and `tests/unit/config/test_scope_requires_agent_id_event.py` fail in
  files this batch did not touch.
