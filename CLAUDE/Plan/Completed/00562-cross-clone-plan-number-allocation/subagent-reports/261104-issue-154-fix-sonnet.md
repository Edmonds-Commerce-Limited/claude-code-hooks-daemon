# Issue 154 fix report (review findings on 513979b15)

## Changes per finding

1. Hook path never fetches. `remote_highest_plan_number(repo_root, plan_subdir, *, fetch=False)` in `plan_numbering.py` only runs `git fetch` when `fetch=True`; `next_plan_number_for_target` never passes it, so plan_number_helper and markdown_organization read the already-fetched `refs/remotes/<remote>/*` only. Only `mkplan.bash` fetches. Tests: a recording `run_git` proves no `fetch` argv, and a hanging `ext::` remote does not delay the hook path.
2. Reason is no longer lost. The scan returns `RemoteScan(highest, reason)` with a `notice` property; the reason keeps git's stderr. New `next_plan_number_with_notice` returns `(number, notice)` for callers that can show it; `next_plan_number_for_target` logs the notice with `logger.warning` (the stderr write is gone). The two handlers keep using `next_plan_number_for_target` (their many tests patch that name), so for them the notice goes to the daemon log, not into the message. Say so if you want it surfaced in the handler context.
3. Parity on a failed `ls-tree`: Python now treats the remote as unchecked (reason names the ref), matching mkplan.bash. Tests corrupt a remote-tracking ref (points at a blob) and check both sides.
4. Test gaps: real hung-fetch tests for mkplan.bash (new env `MKPLAN_REMOTE_FETCH_TIMEOUT_SECONDS`, default stays the 30 s constant `REMOTE_FETCH_TIMEOUT_DEFAULT_SECONDS`, which the parity test now reads) and for the daemon (monkeypatched `Timeout.GIT_FETCH_SESSION`), both against `ext::sh -c 'sleep 30'`. Cancelled/ test covers bash and Python.

Both mkplan copies are byte-identical. Release note 033 updated (only mkplan fetches, logged reason, known limit on nested archives). The suggestion to drop `--name-only` was not taken.

## Results

- `tests/unit/scripts/test_mkplan_remote_scan.py` plus `tests/unit/handlers/utils/`: 230 passed.
- `llm_qa.py changed`: 42/42 PASSED. The first run flagged B404 (a `subprocess` import used only for a type) and formatting; fixed by passing stderr text instead and running the autofix.
- `test_plan_number_helper.py` plus `test_markdown_organization.py`: 460 passed.
