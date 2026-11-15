# Code Review: commit d696d45cc (Plan 00606 fixes)

Reviewer: code-reviewer (opus). Read-only review; no source edited.

## Summary

The three fixes do what the plan asks, and every new behaviour test fails without its fix (the
`get_socket_path` attribute, the `exclude`/`remove_workable` calls and the setup route did not exist before).
The 151 targeted tests pass (`PYTHONPATH=src` from the worktree; output in
`untracked/scratch/probe_606_pytest.txt`). There are no critical defects. The main finding is that the
setup_worktree matcher reimplements command-word parsing, and its version misses wrappers that the git path
sees through. There is also one test that would pass without the code it claims to cover.

Probes (kept as evidence, in the worktree):

- `untracked/scratch/probe_606_matcher.py`: about 35 command shapes run through `created_branches`, plus issue-number parsing.
- `untracked/scratch/probe_606_wrappers.py`: compares how the git path and the script path handle wrappers.
- `untracked/scratch/probe_606_bash_n_theatre.py`: the `bash -n` test case passes with the `-n`/`-c` check disabled.

Run them with `PYTHONPATH=src /workspace/untracked/venv-workspace-py313-0d6d49c6/bin/python <probe>`.

## Verified non-issues

- **Issue parsing.** `_ISSUE_IN_NAME` requires an `issue-N` or `gh-N` segment. So `worktree-476-ci-gate-trial`,
  `worktree-plan-606-followups` and `plan-00605-issue` give None, and `worktree-issue-203-x` gives 203. The runbook
  names branches `worktree-issue-<N>-*` (IssueSdlc.md:359,394), so the fix matches the real flow.
- **Lookup failure.** `remove_workable` runs before the GitHub lookup, so a failed lookup still drops the finished
  issue and keeps `recorded_at`, which is tested. `refresh_workable_cache` writes nothing when the listing raises.
  The read-modify-write in `remove_workable` is not atomic against a concurrent `issue-validity --list-eligible`,
  but that race existed before this commit.
- **Existing branch name.** `creation_report` returns an empty report when the name is already a local ref
  (core/branch_creation.py:839-841). So running setup_worktree.sh on an existing branch is never blocked, and the
  script itself fails on `worktree add -b`.
- **Recorder.** `record_creation` refuses to overwrite an existing creator (branch_records.py:183). A route of
  `setup-worktree` is not `worktree_create`, so the reaper never deletes the branch.
- **No double counting.** The script and an inline git command appear once each. `bash -c '...'`, `$( )` and
  `cd x && ...` are handled correctly, and the directory is resolved from the script's location. `cat`, `echo`,
  `grep`, `git grep`, `source`, `chmod` and a `cat` heredoc give no creation.

## Major

### 1. The setup matcher reimplements command-word parsing and misses wrappers that the git path handles (Confidence: 85%)

**Location:** `src/claude_code_hooks_daemon/utils/git_branch_creation.py:151-176`

**Evidence (probe_606_wrappers.py / probe_606_matcher.py):**

| command                                              | detected? |
| ---------------------------------------------------- | --------- |
| `timeout 60 git switch -c foo`                        | yes       |
| `timeout 600 ./scripts/setup_worktree.sh worktree-x`  | **no**    |
| `env A=1 git switch -c foo`                           | yes       |
| `env A=1 ./scripts/setup_worktree.sh worktree-x`      | **no**    |
| `nohup` / `sudo` + script                             | **no**    |

`_script_and_arguments` only skips leading `NAME=` words and a bare shell interpreter. The repository already has
`peel_command_wrappers` (`utils/shell_segmentation.py:1191`), which knows the grammar of each wrapper's options.
`timeout N` is a plausible way to run the script, because setup_worktree.sh builds a venv and is slow. The
hooks-daemon long-running guard actively pushes agents towards adding `timeout`. This is the bypass a careless
agent hits, which is exactly the gap Plan 00606 Task 1.3 set out to close.

**Fix:** peel the words with `peel_command_wrappers` before testing for the script or an interpreter, and add
`timeout 600 ./scripts/setup_worktree.sh worktree-x` and `env A=1 ...` to the positive cases in the parametrised
test.

### 2. Interpreter options are read as letter clusters, so long options and options that take a value give false negatives (Confidence: 80%)

**Location:** `src/claude_code_hooks_daemon/utils/git_branch_creation.py:165-169`

`set(word.lstrip("-"))` treats `--norc` as the letters {n,o,r,c} and `--login` as containing `n`, so both are
taken to mean "does not run". `bash --norc scripts/setup_worktree.sh worktree-x` and `bash --login ...` therefore
give no creation. An option that takes a value (`-o pipefail`, `-O extglob`, `--rcfile x`) makes its value the
script word, so those give no creation either. All of these were verified by the probe. A less likely shape than
Major 1, but it is the same parser defect.

**Fix:** split short clusters (`-xc`) from long options. Treat only `--` followed by no word, `-n`/`-c` clusters
and `--noexec` as non-running. Skip the value after `-o`, `-O`, `--rcfile` and `--init-file`. Better still, reuse
the interpreter and `-c` handling that `git_commit_parsing` already has (`_SHELL_COMMAND_LETTER`, around line 907).

## Minor

### 3. The `bash -n` test would pass without the code it covers (Confidence: 90%)

**Location:** `tests/unit/utils/test_git_branch_creation.py:144`

The case `"bash -n scripts/setup_worktree.sh"` passes no branch name, so `_setup_script_creation` returns None
because `name` is empty, whatever `_NON_RUNNING_SHELL_LETTERS` holds. probe_606_bash_n_theatre.py empties that
set and the test input still gives `[]`. The same input with a name then returns a creation. The `-n`/`-c`
branch at git_branch_creation.py:39 and :167 is therefore untested.

**Fix:** change the case to `"bash -n scripts/setup_worktree.sh worktree-feat"` and add
`"bash -c 'true' scripts/setup_worktree.sh worktree-feat"`.

### 4. A real run is enshrined as "creates nothing" (Confidence: 70%)

**Location:** `tests/unit/utils/test_git_branch_creation.py:147`; `_SETUP_SCRIPT_TAIL` at git_branch_creation.py:35

`./setup_worktree.sh worktree-feat` (after `cd scripts`) really does run the script, which creates the branch
because it resolves its root from `BASH_SOURCE`. The test asserts that this shape creates nothing. The shape is
unusual, but a test should not assert a false negative as intended behaviour.

**Fix:** either match `setup_worktree.sh` when the preceding `cd` chain ends in `scripts`, or drop the case and
note the known gap in the docstring.

### 5. No recorder test for the new route (Confidence: 75%)

**Location:** `tests/unit/handlers/post_tool_use/test_branch_touch_recorder.py` (no `setup_worktree` case)

The commit says that `branch_touch_recorder` records script-created branches. That only works indirectly, through
`created_branches`, and no test asserts that a `setup-worktree` creator record is written in the directory the
script resolves to.

**Fix:** add a recorder test that runs `./scripts/setup_worktree.sh worktree-x` against a repository with that ref
and asserts that `creator_route == "setup-worktree"`.

### 6. Assignments are taken from every word, not only the leading ones; private import across modules (Confidence: 70%)

**Location:** `src/claude_code_hooks_daemon/utils/git_branch_creation.py:21,198`

`assignments=tuple(word for word in step.words if _ASSIGNMENT_WORD.match(word))` also collects argument words. A
second argument shaped like `GIT_DIR=x` would then trip `placement_problem` and push the verdict back to `cwd`.
This is inconsistent with `_is_leading_assignment`, defined 20 lines above. `_ASSIGNMENT_WORD` is also a private
name of `git_commit_parsing` imported from another module.

**Fix:** reuse the leading-assignment slice that `_script_and_arguments` already computes, and make the pattern
public (or add an `is_assignment_word` helper) in `git_commit_parsing`.

### 7. Discovery calls a resolver that has side effects (Confidence: 60%, below the threshold, noted only)

**Location:** `tests/acceptance/conftest.py:111`

`get_socket_path` creates the untracked directory, and the fallback may create a runtime directory under `/tmp`.
That is harmless for acceptance runs. The unit test stubs it out.

## Positive observations

- `_next_issue_line` closes the "lookup failed, stale entry stays" hole by removing the issue first, and its docstring states why.
- The `exclude` parameter on `refresh_workable_cache` is small and has a sensible default.
- The work-queue tests cover the branch source, the name source, lookup failure and the case with no issue number. Each fails without the fix.
- The socket discovery test asserts that the resolver is called with `REPO_ROOT` and that the env override wins.

## Verdict

REQUEST CHANGES (non-blocking for correctness). Major 1 leaves the exact gap that Task 1.3 targets open for
`timeout`- or `env`-wrapped runs. Every other finding can be filed as a follow-up.
