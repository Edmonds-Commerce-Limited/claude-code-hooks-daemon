# Plan 00553 report: supervisor indicator scoped to session (issue #140)

## Red run (before implementation)

Collected with the new test files and the old handler:

    ImportError: cannot import name '_MAX_TRACKED_SESSIONS' from
      'claude_code_hooks_daemon.handlers.status_line.supervisor_indicator'
    ModuleNotFoundError: No module named 'claude_code_hooks_daemon.utils.process_tree_sessions'

This is an import-level red, not a behavioural one: the new tests inject the process table through
`_proc_root`, which the old handler lacks, so I did not run the reproduction against old code.

## Green

`tests/unit/handlers/status_line/`, `tests/unit/utils/test_process_tree_sessions.py` and
`tests/integration/test_claude_md_guidance_coverage.py`: 1181 passed.

## Design

- `utils/process_tree_sessions.py`: read-only daemon copy of the Plan 00551 rule (`CLAUDE_CODE_SESSION_ID` in the
  environ of a process or its ppid descendants). Not imported from `claude-supervise.py`, which is untouched.
- Handler: `_supervisor_owns_session` gates both the status-file pid and the `/proc` scan candidates. Caches moved
  into a per-session `_SessionMemo` map (bounded by `_MAX_TRACKED_SESSIONS`), all behind one `threading.Lock`.
  No/blank/non-string `session_id` gives the unscoped orange/none decision, uncached.
- Plan 00171 negative cache and walk interval are kept, per session.

## Cost

One `stat` read per numeric `/proc` entry plus one `environ` read per member of the candidate's subtree, only on
a cache miss. A session that owns its supervisor pays it once. A non-owning session pays it at most once per
5 s negative-cache TTL (status-file path) and once per 60 s walk interval (scan path).

## Judgement calls

- A worker-only fallback match is owned only if the worker's own subtree carries the id, which it normally does
  not. So a host-less worker no longer paints green. Intended, but a behaviour change.
- The lock covers whole resolution, so concurrent renders of different sessions serialise during a miss.
- `explain_segment` has no session, so it reports the unscoped decision.
- Existing tests now pass a `session_id` and patch ownership true; ownership itself is tested in
  `test_supervisor_indicator_session_scope.py` against a fake `/proc` under `tmp_path`.

## QA

`llm_qa.py changed`: 35 of 41 passed on the first run; the four failures (format, error_hiding, plan_qa, semgrep) were fixed (autofix, an isdigit parse in place of try/except, memo eviction inlined under the lock, Success Criteria left unticked until merge). A re-run of just those four checks is clean. Targeted pytest: 793 passed.
