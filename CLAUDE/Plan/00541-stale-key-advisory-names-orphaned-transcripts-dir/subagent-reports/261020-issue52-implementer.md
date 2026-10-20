# Issue 52 implementer report (Plan 00541)

## Change

- `src/claude_code_hooks_daemon/constants/handlers.py`: the `transcript_archiver` entry of `RETIRED_HANDLERS` now ends "Safe to delete this key from your config; delete `untracked/transcripts/` to reclaim the disk. Those archives are copies of transcripts you still have."
- `tests/unit/config/test_handler_name_validation.py`: new `test_transcript_archiver_advisory_names_the_orphaned_directory`.
- `CLAUDE/UPGRADES/UNRELEASED/release-notes/006-transcript-archiver-advisory-names-orphaned-dir.md`.
- Plan Tasks 1.1 and 2.1 ticked.

## Evidence

- Red: the new test failed on `assert "copies of transcripts you still have" in advisory` before the text change (`untracked/scratch/52-red.txt`).
- Green: the new test plus `tests/unit/install/test_handler_key_audit.py` and the rest of the name-validation file, 53 passed (`untracked/scratch/52-green.txt`).
- No other file embeds the old sentence; no generated doc needed regenerating.

## QA

`./scripts/qa/llm_qa.py changed` failed on one item only: `constants/handlers.py` is unmapped as `too-broad` (its import reach is the full suite, and the existing map rule does not narrow it). Its 37 selected tests passed. Re-ran with `--allow-unmapped`, QA_EXIT=0. The coordinator's full gate covers the broad reach.
