# Issue #43 implementation report — Sonnet subagent

**Plan**: 00425
**Worktree**: `untracked/worktrees/worktree-issue-43-remote-docs-index/`

## What changed

- `src/claude_code_hooks_daemon/daemon/cli.py`
  - `_remote_docs_check` now takes `project_root` and compares
    `render_index(tree)` against `<project_root>/.claude/REMOTE-DOCS.md`
    (exact string compare; missing file treated as stale). Reports a new
    finding, folds it into the attention count, prints
    `bin/hooks-daemon remote-docs index` as the remedy.
  - `cmd_remote_docs` dispatches a new `index` action before the fetcher is
    resolved, so it never warns about a browser it isn't going to use. Its
    body is the existing `_regenerate_remote_docs_index` call, returning 0.
  - `remote_docs_action` choices gained `"index"`, with updated help text.
- `src/claude_code_hooks_daemon/remote_docs/index.py` — module docstring and
  the generated `_HEADER` now name the deletion gap, `check`'s new finding,
  and the `index` command as the fix (both `add` and `refresh` remain true,
  now joined by a third verb).
- `CLAUDE/RemoteDocs.md` — added a paragraph on the deletion gap, the exact
  comparison, and the repair path.
- `docs/guides/REMOTE_DOCS.md` — added `remote-docs index` to the command
  table and a two-sentence pointer to `CLAUDE/RemoteDocs.md` for depth
  (kept terse per the human-docs house rule).
- `CLAUDE/UPGRADES/UNRELEASED/release-notes/02-remote-docs-check-reports-a-stale-index.md`
  — new callout, operators audience.
- `tests/unit/remote_docs/test_cli_remote_docs.py` — 5 new tests (see RED
  evidence below): 3 on `TestListAndCheck` for the deletion/stale-index/
  missing-index cases and the remedy line, 2 in a new `TestIndexAction` for
  the `index` action's re-render behaviour and its no-network guarantee.

No changes to the provenance schema, fetchers, `add`/`refresh` behaviour, or
what the index contains (columns/ordering untouched, Plan 00326 stays).

## RED evidence (captured before the fix, from this session)

Command: `pytest tests/unit/remote_docs/test_cli_remote_docs.py -q`, run
against the test file with the 5 new tests added but before any of the
Phase 1/2 source changes.

```
FAILED tests/unit/remote_docs/test_cli_remote_docs.py::TestListAndCheck::test_check_reports_a_stale_index_after_a_deletion - AssertionError: assert 0 == 1
FAILED tests/unit/remote_docs/test_cli_remote_docs.py::TestListAndCheck::test_check_names_the_index_command_as_the_stale_index_remedy - assert 0 == 1
FAILED tests/unit/remote_docs/test_cli_remote_docs.py::TestListAndCheck::test_check_reports_a_missing_index_as_stale - AssertionError: assert 0 == 1
FAILED tests/unit/remote_docs/test_cli_remote_docs.py::TestIndexAction::test_index_re_renders_the_file - assert 2 == 0
FAILED tests/unit/remote_docs/test_cli_remote_docs.py::TestIndexAction::test_index_touches_no_network - assert 2 == 0
5 failed, 30 passed in 2.68s
```

Detail on the two `TestIndexAction` failures — `cmd_remote_docs` fell
through to the `refresh` branch because `"index"` was not yet a recognised
action, and `_remote_docs_refresh` returned exit 2 with:

```
remote-docs refresh: name a PATH or pass --all
```

which confirms these two tests genuinely exercised the missing action
(not a fixture bug) rather than passing by accident.

## GREEN

Same file after the Phase 1/2 source changes: `30 passed` became
`35 passed`, 0 failed. Full `tests/unit/remote_docs/` directory:
`228 passed` (was 223 before the new tests).

## QA_EXIT

`QA_EXIT=1`.

Breakdown (`./scripts/qa/llm_qa.py all`, `33/35 PASSED, 2/35 FAILED`):

- `tests`: 24897 passed, 0 failed, **18 errored**, 24 skipped, coverage 95.2%.
  Every errored test is one of:
  `test_absolute_path_socket_deny.py` (6), `test_daemon_source_freshness.py`
  (2), `test_playbook_harness.py` (5), `test_stop_hook_hard_block.py` (3),
  `test_tool_use_error_recovery.py` (2) — all acceptance tests that dispatch
  against the **running daemon socket**.
- `smoke_test`: 0/3 probes passed, with the tool error:
  `STALE DAEMON: the running daemon's loaded code (source_fingerprint 66707663ed38) does not match the current working tree (source_fingerprint d5c7af76b4b7)`.

Both failures trace to the same cause: the daemon process serving this
worktree's socket has not been restarted since these changes landed, so
every acceptance/smoke probe that talks to it judges stale code. This
matches the environment hazard flagged in my brief (the playbook harness
can misbehave in a worktree) but manifests here as a fingerprint mismatch
rather than a hang — no test run stalled. **None of the 18 errored tests
are in `tests/unit/remote_docs/` or touch remote-docs code**; every unit
test, including all 5 new and 223 pre-existing remote-docs tests, is in the
24897 passed. I did not restart the daemon myself, since that is an
irreversible-ish operational action outside this task's scope and the brief
did not authorize it.

## Playbook harness stall

Not encountered — `test_playbook_harness.py`'s 5 tests errored quickly (part
of the same batch, same stale-daemon cause) rather than hanging. No test run
exceeded a few seconds.

## Disagreements with the brief

None. The staleness comparison (exact string equality against
`render_index`) worked exactly as the brief predicted — no reliability
issue found.

## Commit

Committed in the worktree as a single commit; not merged, not pushed.
