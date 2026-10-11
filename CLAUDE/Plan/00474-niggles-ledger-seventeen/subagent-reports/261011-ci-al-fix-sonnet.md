# CI red after batch AL (merge 13f0b895c): causes and fixes (Addresses #69, ledger N425)

CI run 38153660205, QA on Python 3.11/3.12/3.13: 5 failed, 1 error. Four distinct causes.

## 1. `/usr/bin/docker run -e A=1 img cmd` judged `code-that-cannot-be-read`

- Cause: a program given by ABSOLUTE path is also tried as a script file (`_full_run_in_code_file` -> `_read_code` -> `_read_new`). `_read_new` returned UNSEEN for any regular file larger than the event's 16 MiB read budget.
- The GitHub runner has a real `/usr/bin/docker`, a binary of tens of MB, so it read as unseen code and failed closed. A dev host without docker at that path sees ABSENT and passed.
- Reproduced with a 40 MB file named `docker` in a temp dir: red before the fix, green after.
- Fix (`subagent_full_qa_blocker.py`): `_binary_head()` probes the first `_BINARY_PROBE_BYTES` of an over-budget file. A NUL there means a binary, which holds no code to read, so it returns TEXT content and `_code_kind` yields None. Over-budget text without a NUL stays UNSEEN.
- Tests: the host-dependent `/usr/bin/docker` parameter is replaced by `test_an_absolute_path_container_runtime_is_judged_like_a_bare_one` (a temp-dir docker, absent or present as a large binary), plus a test that an over-budget script without a NUL is still unseen.

## 2. `test_many_edits_each_run_are_judged_quickly` (x2) and `test_many_open_exec_calls_are_judged_quickly`

- Measured before (`13f0b895c^1`, 005b33da6) and after (HEAD), same machine, median of 5: 0.28/0.30/0.31 s versus 0.30/0.39/0.32 s. The code did not get slower.
- The cause is coverage tracing. CI runs `pytest --cov=src`. The same work takes 0.9-1.3 s with coverage locally and 1.7-2.2 s on the runner, against a bare 1.5 s bound.
- A host load average cannot see this, so `scaled_seconds` alone would not have fixed CI.
- Fix: `tests/load_scaling.py` gains `TRACING_FACTOR` (8.0), `tracing_factor()` (reads `sys.gettrace()`) and `scaled_cpu_seconds()` (= `scaled_seconds` x `tracing_factor`). It only lengthens a bound. The seven 1.5 s bounds in `test_subagent_full_qa_blocker.py` now use it.
- Verified under `--cov`: the previously failing cases take 1.4-1.85 s and pass.

## 3. `test_no_elapsed_time_is_compared_to_a_bare_number`

- It named three `assert time.perf_counter() - start < 1.5` lines in `test_subagent_full_qa_blocker.py` (CI lines 4114, 4122, 4353), from batch AL.
- Fixed by item 2's `scaled_cpu_seconds(1.5)`. The four `self._timed(...) < 1.5` bounds were not flagged by the guard's regex but are scaled the same way.

## 4. Teardown error in `TestEachStepRecordsItselfAsItFinishes.test_an_interrupted_run_keeps_the_steps_that_finished`

- File: `tests/unit/qa/test_llm_qa_resume.py`. The test stubs `run_tool` but not `ensure_live_daemon`.
- `_run_tools` calls `ensure_live_daemon("smoke_test")` first (`smoke_test` is a live-daemon tool). With no daemon running (CI), the real function STARTS one against the real checkout. The CI log says "DAEMON STARTED: no daemon was running before smoke_test, so llm_qa started one".
- That daemon's initialise rewrote `CLAUDE.md` and created the pid file (mtime None -> set). A dev host has a daemon up, so it never showed.
- Fix: an autouse fixture in that file stubs `ensure_live_daemon` and records the call. A new test pins that a live-daemon step goes through the stub.
- Would the batch AN jail have refused it? It would likely have refused the `CLAUDE.md` write, because the spawned Python daemon is armed through `sitecustomize` and the inherited environment. That is unconfirmed: I did not run it with the jail. The pid-file touch is not protected, and the test would still have started and left a real daemon running, so the stub is the right fix.

## QA

- pytest on the touched files: 1504 passed.
- Black (py311) clean; mypy clean on `subagent_full_qa_blocker.py` and `tests/load_scaling.py`.
- `llm_qa.py changed --base main --allow-unmapped`: changed_tests 5147 passed, 0 failed. Its detectors were green except three, none from a defect left in the commit:
  - `error_hiding` flagged a first draft of `_binary_head`, which returned None on an OSError. Reworked into `_over_budget_content`, and a re-run is clean.
  - `github_urls` flagged `.coverage`, left by my own `--cov` run. Deleted, and a re-run is clean.
  - `plan_qa` advises that the journal of plan 00495 is quiet. Unrelated to this change.
- The 1.5 s bounds were not re-measured on the CI runner. Under local `--cov` the unscaled bound would still fail (1.4-1.85 s) and the scaled one passes.
