# Task 1 implementer report (Plan 00597)

- Rule 3 of `matches()` (echo/printf glob): the gap after the command now steps over a whole substitution (`$(...)`, backticks, `<(...)`) via `_ECHO_ARGUMENT_GAP` and never reads into it; the glob must not open with a full 5-digit plan number (`(?!\d{5})`).
- RED seen: 6 failures in the new test file (5 allow cases, plus the bare `echo $(ls <plan-dir>)` deny case, see below).
- Deviation: the brief's deny case `echo $(ls <plan-dir>)` (no glob) is NOT denied on main either (no rule matches a bare ls of the plan dir inside echo), so it is out of scope. It is replaced by `echo $(ls <plan-dir>/*)` and a backtick form, both of which deny.
- Tests: new file tests/unit/handlers/pre_tool_use/test_plan_number_helper_echo_glob_substitution.py (13 pass); the three existing plan_number_helper test files plus it: 268 pass.
- Release note: CLAUDE/UPGRADES/UNRELEASED/release-notes/053-plan-number-helper-echo-glob-inside-substitution.md.
- `llm_qa.py changed`: 42/42 PASSED.
