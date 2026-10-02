# Ledger 00474 N299, N300, N301: pathspec follow-ups

Branch `worktree-n299-pathspec-followups`.

## Red, before any source change

New facts tests (`tests/unit/utils/test_git_facts_command_directory.py`) failed at collection:

```
ImportError: cannot import name 'commit_directory' from 'claude_code_hooks_daemon.utils.git_facts'
```

Handler tests, same run (`-k "AnotherRepo or moves_to"`): 7 failed, 3 passed.

```
FAILED test_remote_docs_commit_gate.py::TestACommitInAnotherRepositoryIsNotJudgedAgainstThisOne::test_a_hook_directory_in_another_repository_stands_down
FAILED ...::test_a_nested_worktree_inside_the_project_stands_down
FAILED ...::test_a_command_that_moves_into_another_repository_stands_down[cd {other} && git commit -m x]
FAILED ...::test_a_command_that_moves_into_another_repository_stands_down[git -C {other} commit -m x]
FAILED test_sensitive_content.py::TestPathspecViewIsUsedOnlyWhenTheReadingIsCertain::test_a_pathspec_is_read_from_the_directory_the_command_moves_to[cd sub && git commit -q -m x f.txt]
FAILED ...[git -C sub commit -q -m x f.txt]
FAILED ...[(cd sub; git commit -q -m x f.txt)]
```

The docs QA test (`TestPathspecsAreReadWhereTheCommandRuns`) was written after the implementation and its
red could not be shown: running it against main's source trips `tests/source_tree_guard.py`.

## Green

2016 passed over the touched test files plus `tests/unit/docs_qa` and `tests/unit/plan_qa`.

## What changed

- N299: `CommitReading.moves` records the `cd`/`pushd` chain, then `-C` operands (None for an unstatable
  move: `cd -`, `$VAR`, `~`, `--git-dir`, `--work-tree`, `GIT_*`). `commit_directory` resolves it from the
  hook cwd; `pathspec_directory` keeps it only when it lands inside the repository, else falls back to cwd.
  `commit_facts` uses it for both the certain and the union view; `sensitive_content` reads the union pass
  from `facts.directory`. The same gap was in the docs QA and plan QA commit gates (they passed no
  directory at all, so a named path was always read from the root); both now pass `pathspec_directory`.
- N300: `remote_docs_commit_gate` stands down when the hook cwd, after any `cd`/`-C` move, is in another
  repository (`GitRepo.resolve_for`, the staged_lint_gate mechanism). A move it cannot state is judged
  against this project, as before.
- N301: `every_pathspec_matches` is one `ls-files --error-unmatch` for all paths. Only when that fails
  (an unmatched path, or a path only HEAD has, e.g. after `git rm --cached`) does it ask per pathspec as
  before, so the failure and rare shapes are unchanged. Tests count `run_git` calls: 12 paths is 1 call.
  Gates do not share the answer across each other: each builds its own facts per command and a
  module-level cache keyed on the command would outlive the index it describes.

## Left open

- `guard_config_commit_gate._pathspec_covers` compares a pathspec to the config path as text from the
  root. `cd .claude && git commit hooks-daemon.yaml` is not seen as covering `.claude/hooks-daemon.yaml`,
  so the gate reads no config change. Not a regression and not a false positive, so not touched here;
  worth its own niggle.
- `staged_lint_gate._is_foreign_repo` still looks at the hook cwd only, not a `cd`/`-C` move into another
  repository (remote_docs now does).
- The single-call fast path does not use `--literal-pathspecs`, same as the per-path check it replaces.

## Round 2 (Opus review fixes)

Review: [261002-n299-review-opus.md](261002-n299-review-opus.md), verdict MERGE-WITH-FIXES.

### Fail-open regression (review item 1)

`commit_directory` / `pathspec_directory` trusted every recorded `cd`. Fix, fail closed:

- The parser (`git_commit_parsing._invocations`) now records whether each move is CERTAIN
  (`GitInvocation.moves_certain`, `CommitReading.moves_certain`). A move is certain only when every
  operator from the `cd` on is `&&` and the operator before it is not `||`, `|` or `|&`. `;`, `&`,
  newline, a trailing `||`, and a `cd` in a pipeline are uncertain. A subshell restores the flag with
  the directory. `-C` moves are git's own argv and stay certain.
- `unmoved_directories(reading, cwd, repo_root)` names the hook's own directory as a second place
  the commit may run. `GitFactsBase(extra_directories=...)` reads the pathspecs from every
  directory (a directory git cannot run in is skipped, `None` only when none answers) and merges
  the changes and named paths. `commit_facts` passes it on the union reading.
- Every gate uses it: `sensitive_content` (one working-tree pass per directory), `docs_qa` and
  `plan_qa` (`staged_context(extra_directories=...)`), and `remote_docs` (`_is_foreign_repo` stands
  down only when BOTH the hook directory and the moved one are another repository).
- Behaviour change worth knowing: `(cd sub; git commit f.txt)` is now uncertain (the `;` does not
  guarantee the `cd` worked), so both `f.txt` and `sub/f.txt` are judged. The `&&` form stays exact.

### Vacuous test (review item 2)

`test_a_moved_reading_is_the_index_plus_the_paths_named_where_it_moved_to` now passes `cwd=messy`
and names `d/e2.txt`, a path committed then edited and left unstaged, so only a read from `d/`
names it. Verified: with `pathspec_directory` replaced by main's logic (moves ignored, run through
`untracked/scratch/run_main_logic.py`, not committed) it FAILS; with the fix it passes.

### Red to green

Before the fix: 15 failed (new rows across sensitive_content, docs_qa, plan_qa, remote_docs, and
the strengthened moved-reading test) plus an import error for the new `unmoved_directories` rows.
After: all green. plan_qa is proven by a test, not by reading: `cd nosuch; git commit ... PLAN.md`
with an unstaged terminal flip is denied (`BLOCKED [R-PLAN-QA-COMMIT]`), as is `cd CLAUDE & git
commit ... Plan/00001-first/PLAN.md`, which only the moved directory names.

### Not done here

Review items 3 and 4 (a second commit's pathspecs, and judging a same-project worktree against its
own index) are filed as N306 and N307 on main.
