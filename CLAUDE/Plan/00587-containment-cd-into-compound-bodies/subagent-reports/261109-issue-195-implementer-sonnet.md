# Plan 00587 / GitHub #195: implementer report

## Root cause

The body steps ARE seen by the cd tracker, with the right directory chain (`('sub',)`). What was wrong is
`moves_certain`: `_walk` in `utils/git_commit_parsing.py` marks a chain uncertain at any operator that is not `&&`
while a directory chain exists. A compound body is introduced by `;` (`for x in a;` then `do`, `if true;` then
`then`) or by a bare `(`, so every body step came back `moves_certain=False`. `_targets_after_cds` then reads such a
step from the cd target AND from the start directory (`landing_directories(optional=len(directory))`). The start-directory
reading of `../loop.err` is `/workspace/../loop.err`, which is the deny seen. A `{ ...; }` group has no such operator
before its body, which is why it already passed.

## RED (before the fix)

New class `TestACompoundBodyRunsWhereTheChainsCdLanded` in
`tests/unit/handlers/pre_tool_use/test_project_containment.py`. Result: `6 failed, 13 passed`:

- FAILED allowed: `for` (the issue's 2>>../loop.err), `while`, `until`, `if`, `( )`, `for ... | tee ../x`
  (each `assert True is False`, i.e. matches() denied).
- Already passing, kept as regression guards: `{ ...; }` allowed; all denial-direction shapes (cd /tmp bodies, `../../x`
  escapes, target before the cd).

## GREEN

`_walk` takes keyword-only `bodies_follow_cd`; when true, an operator inside an open group/subshell frame whose
directory chain equals the current one (no `cd` of the body's own yet) does not set `uncertain`. `simple_commands`
exposes it (default False). `project_containment._steps_after_a_cd` passes True. No second parser.

Deviation from the brief boundary: the fix is in the shared `utils/git_commit_parsing.py` because the uncertainty is
computed there; it is opt-in so the git gates and every other caller read exactly as before. Two tests added in
`tests/unit/utils/test_git_commit_parsing.py` (default keeps doubt, opt-in removes it, a body's own cd keeps doubt).

## Still denied (tests)

cd /tmp then each body shape; cd sub then `../../x` in for/if/group/subshell; target in a loop before the `cd`.

## Known limit

`cd sub && for ...; do a; b; done` with later body operators: an operator after a body-local `cd` still sets doubt, so a
`cd` inside a body keeps both readings (non-goal of the plan).

## Verification

Containment, git_commit_parsing, git_invocation_directory, git_facts_command_directory and commit_location test
modules: 752 passed before the extra tests; test_git_commit_parsing 294 passed. Targeted QA verdict: see the reply.
