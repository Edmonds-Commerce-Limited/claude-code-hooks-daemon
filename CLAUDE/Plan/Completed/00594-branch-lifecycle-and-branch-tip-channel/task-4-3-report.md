# Task 4.3 report: park record survives a refused push, a merge clears it visibly

Branch: `plan-00594-task-4-3-park-survives-push`. Ledger item N607. Release note 043.

## Finding against the brief

The coordinator's fact-check was right. `park_branch` already wrote the park commit and moved the ref
before pushing, so a refused push (pre-push hook, exit 1) left a whole local park and returned
`pushed=False` with git's stderr and the retry command. The pinning test
`test_a_pre_push_gate_refusal_leaves_the_record_and_reports_git_reason` exercises a real repo with a failing
pre-push hook. The genuine gaps, each demonstrated red first:

1. No durable park record (reason, time, owner) apart from the commit trailer. Added
   `branch.<name>.hooksDaemonParked{,Reason,At,By}` in git config, written after the ref moves and before the push
   (`write_park_record`, `read_park_record`, `clear_park_record` in `core/branch_park.py`).
2. Exit status: a refused push exited 0, the same as a full park. Now `EXIT_PARKED_NOT_PUSHED = 3`, and the output
   says `WARNING: parked locally, not pushed`, with git's reason and `Retry: git push <remote> <name>`.
3. Merge ended a park silently. `CleanupReport.park_cleared` and `render` now print
   `Park cleared: <name> (<reason>)` from `cleanup_after_merge` (act and advise), `delete_if_merged` and
   `clean_sweep`; `branch-park --clear` prints `Park record cleared: ...`.

Not changed: the remote-only path still parks nothing on a refused push (no local ref can carry a park; the error
says so). Pool cap logic untouched. The design's group-pool PARKED resolution and the session-start "park
cleared" print (DESIGN 2.4 second and third bullets) are not part of this task and remain open.

## TDD evidence

Tests were written before any source change. Observed red: first run was a collection ImportError
(`EXIT_PARKED_NOT_PUSHED`, `read_park_record` absent). After adding the park-record code, a second run showed the
5 clearing tests failing with `TypeError ... unexpected keyword argument 'park_cleared'` and the CLI tests failing
on exit status; I then fixed these to green. The existing CLI fixture used an unreachable remote, so its tests were
moved onto a real bare remote, and the failed-push test sets an unreachable URL explicitly.

## Tests

New: `tests/unit/core/test_branch_park_record.py` (9), additions in `tests/unit/daemon/test_cli_branch_park.py`.
Suites run separately: tests/unit/core 4159 passed; tests/unit/daemon 3333 passed, 2 failed (the known
venv_start artefact only); scripts + session_start + the two integration files 1614 passed;
pre_tool_use + test_cleanup_after_merge 12154 passed, 1 failed:
`test_project_containment.py::TestProjectRootDoublePatchDoesNotLeakAcrossFiles::test_the_polluter_and_a_victim_pass_together_in_one_process`.
That test spawns a child pytest, which hit an INTERNALERROR at session start; it does not touch branch code and I
believe it is the same PYTHONPATH artefact, but I did not run it without the override to confirm.
QA (format lint type_check error_hiding magic_values semgrep plan_qa docs_qa): 8/8 passed.
