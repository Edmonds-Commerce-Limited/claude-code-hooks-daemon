# Fact check: NIGGLES.md entry N380 (diff 00474-niggles-ledger-seventeen.diff)

Checked against /workspace main (c83d3d63a), `untracked/scratch/qa-changed-range.txt` and `untracked/qa/changed_tests.json`.

## REFUTED (most consequential first)

1. **C10 "Agents cannot run `llm_qa.py` (R-SUBAGENT-FULL-QA), so the merge gate has to be the coordinator's `changed --range ...`"**
   REFUTED.

   - `.claude/hooks-daemon.yaml:524-528` declares `llm_qa.py` with `full_words: [all, tests]`. Only those subcommands are "full".
   - Lines 521-565 and the `targeted_qa_commands` list (`./scripts/qa/llm_qa.py changed`) show `changed` is declared TARGETED.
   - `--range` is a declared `value_flags` entry, so `changed --range A..B` is judged targeted and is allowed for agents.
   - Plan change: say "agents cannot run `llm_qa.py all` or `tests`". Drop the inference that only the coordinator can run `changed --range`. The real reason the coordinator runs it is that agents did not run it.

2. **C9 "`changed` with no `--range` on a clean main selects nothing (0 changed files)"**
   REFUTED as worded.

   - `scripts/qa/run_changed_tests.py:1031-1038` refuses a run with HEAD on the base branch: "HEAD is on `main`, the base itself ... committed work cannot be told apart". It does not select 0 files.
   - The docstring at lines 37-40 says the same.
   - A 0-file selection arises only from a non-base branch or worktree whose HEAD equals the merge base, as in an integration worktree after a merge.
   - Plan change: write "on the base branch it is refused; on a merged head in a worktree it selects nothing".

## UNVERIFIABLE-HERE or weak

- **C11 "The six regressions are on a worktree branch."**
  - No branch diff (`main...agent-a13c...`, `agent-a46aaf...`, `agent-a9b4f...`) touches the priority-band, HookInputField, default-enabled-template, event-socket or registry-option tests.
  - `agent-a46aaf37c1a16d458-6185c9b3` is the 00499 Phase 1b branch. It touches `write_protected_paths.py` and its tests, and it has uncommitted edits.
  - It might carry the `write_protected_paths` option-injection fix, but this cannot be confirmed without running the tests.
  - Name the branch, or say the fixes are not yet located.
- **C3 "none ... lives near the changed module, so a targeted run by name or import never selects them"** and **"no agent ran"**.
  - The tests were selected by `changed --range` (253 test files from 90 files), so range mapping does reach them.
  - Whether a per-branch `changed` run would have selected them depends on the mapper, and cannot be settled without running it.
  - Which agents ran what is not on disk.

## Table

| #   | Claim                                                                                        | Verdict                   | Evidence                                                                                                                                                                                                                        |
| --- | -------------------------------------------------------------------------------------------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | After N379, `llm_qa.py changed --range 85c4c73b1..HEAD` was run                              | VERIFIED                  | `untracked/qa/changed_tests.json` has `"range":"85c4c73b1..HEAD"`, and `git cat-file -t 85c4c73b1` returns commit                                                                                                               |
| 2   | "every merge since the last green gate"                                                      | VERIFIED                  | `git log --merges 85c4c73b1..HEAD` lists the 00499, N359, 00470 6.4 and 00500 2.5 merges (87 files changed)                                                                                                                     |
| 3   | 6 tests fail                                                                                 | VERIFIED                  | `qa-changed-range.txt:79`: "13250 passed, 6 failed"; json `failed:6`                                                                                                                                                            |
| 4   | Failing: the priority-band check                                                             | VERIFIED                  | `test_priority_bands_match_the_code.py::...test_no_handler_priority_falls_outside_every_band` is in the failed list                                                                                                             |
| 5   | Failing: the default-enabled template consistency check (x2)                                 | VERIFIED                  | `test_template_marks_only_expected_handlers_disabled` and `test_handler_overrides_match_expected` are in the failed list                                                                                                        |
| 6   | Failing: registry option injection for `write_protected_paths`                               | VERIFIED                  | `test_registry_option_injection.py::...[write_protected_paths]` is in the failed list                                                                                                                                           |
| 7   | Failing: the `HookInputField` single-source check                                            | VERIFIED                  | `test_hook_input_field_single_source.py::...test_every_hook_payload_read_uses_the_constant` is in the failed list                                                                                                               |
| 8   | Failing: event-socket enrichment "left untouched" test                                       | VERIFIED                  | `test_event_socket_hook_event_name_enrichment.py::...test_payload_already_carrying_hook_event_name_is_left_untouched[asyncio]` is in the failed list                                                                            |
| 9   | "on main"                                                                                    | UNVERIFIABLE-HERE         | The run was in a tree where the working tree changed during the run (the "NOT RECORDED" warnings). The tests exist on main, but I did not re-run them. The range merges are on main, and `qa-changed-range.txt` was run on main |
| 10  | The 00499 Phase 1 failures: priority-band, template (x2), `write_protected_paths`            | UNVERIFIABLE-HERE         | `write_protected_paths` is in `constants/handlers.py:100` and 00499 merged (8887b2435). Which test belongs to which plan is attribution, not on disk                                                                            |
| 11  | The 00470 Task 6.4 failures: HookInputField and event-socket                                 | UNVERIFIABLE-HERE         | The 6.4 commits (97e402fb4, 125919302) touched `daemon/server.py`, which is plausible, but attribution needs a run                                                                                                              |
| 12  | Each test guards a property that every handler or payload read must satisfy                  | VERIFIED                  | The test names say so, e.g. "every_hook_payload_read_uses_the_constant" and "no_handler_priority_falls_outside_every_band"                                                                                                      |
| 13  | `changed` with no `--range` on clean main selects nothing (0 changed files)                  | REFUTED                   | See REFUTED item 2                                                                                                                                                                                                              |
| 14  | So "run `changed` on the merged head" checks nothing after a merge                           | PARTLY                    | Holds for a worktree merged head at the merge base. On main it is refused (`run_changed_tests.py:1031`). `CLAUDE/QA.md:110-117` and the advisor's old text told people to run bare `changed` on the merged head                 |
| 15  | Agents cannot run `llm_qa.py` (R-SUBAGENT-FULL-QA)                                           | REFUTED                   | See REFUTED item 1                                                                                                                                                                                                              |
| 16  | Six regressions are on a worktree branch                                                     | UNVERIFIABLE-HERE         | See above                                                                                                                                                                                                                       |
| 17  | Remedy 1: `merge_qa_advisor` should print the exact `--range <pre-merge head>..HEAD` command | VERIFIED as a gap on main | HEAD's `merge_qa_advisor.py` says only "Then `./scripts/qa/llm_qa.py changed` on the merged head". An uncommitted working-tree diff in /workspace adds the `--range` text. This is a remedy, not a current-state claim          |
| 18  | Remedy 2: the coordinator runs that range after every merge onto main                        | Intention, skipped        |                                                                                                                                                                                                                                 |
