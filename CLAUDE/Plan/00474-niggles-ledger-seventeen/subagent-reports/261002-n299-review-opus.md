STOPPING BECAUSE: review complete. Verdict: MERGE-WITH-FIXES.

# Review: worktree-n299-pathspec-followups (e62e5bca2), N299/N300/N301

**Summary.** Overall this is a large net gain: the branch now catches 11 of the probed shapes that main lets through. But it adds 3 new fail-open regressions, all from the same cause, and one new test does not actually test anything. All 388 tests in the touched files pass on the worktree's own venv.

**sensitive_content probe** (term left as an unstaged edit in the file git really records; "recorded" checked by running each command in a scratch repo):

| command | recorded | main | branch |
|---|---|---|---|
| `cd sub && git commit f.txt` / `-- f.txt` / `--include f.txt` | yes | allow | DENY |
| `cd sub && … ../f.txt`, `git -C sub …`, `(cd sub && …)`, `pushd sub && …` | yes | allow | DENY |
| `cd "sub dir" && …`, `cd link && …` (symlink), `cd /abs/sub && …` | yes | allow | DENY |
| `cd sub; cd ..; …`, `(cd sub); …`, `:/f.txt`, `'*.txt'`, `-a`, `-C sub -C ..`, `cd sub; git -C .. …`, `pushd; popd; …`, hook cwd=sub with `cd ..`, `cd; cd /root; …` | yes | DENY | DENY |
| **`cd nosuch; git commit f.txt`** | yes | DENY | **allow** |
| **`test -d nosuch && cd nosuch; git commit f.txt`** | yes | DENY | **allow** |
| **`cd sub & git commit f.txt`** (backgrounded cd) | yes | DENY | **allow** |
| `cd sub \|\| cd x; git commit f.txt` | yes | allow | allow |
| `cd sub && git commit f.txt; cd .. && git commit g.txt` | yes | allow | allow |
| `cd nosuch; …` with the term staged | yes | DENY | DENY |

docs_qa gives the same result for the regressions (`probe_docs.py`): `cd nosuch; git commit CLAUDE/Foo.md` and `cd other & git commit CLAUDE/Foo.md` both lose the broken-pointer finding (main reports it, branch does not). plan_qa takes the same `directory` into `GitFacts` and has the same weakness; I found that by reading the code, not by running it. The round-3 plan_qa regression does **not** come back: for pathspec commits `committed_from=None` is unchanged, so the tree is still read from disk.

## Critical: must fix before merge

**1. A recorded cd that never took effect sends the pathspec read to the wrong place (confidence 90%).**
- Where: `src/claude_code_hooks_daemon/utils/git_facts.py:549-580`, `commit_directory` and `pathspec_directory`.
- Problem: they trust every recorded `cd`. A cd that fails, is skipped by `&&`/`||`, or runs in the background does not move the commit. When the target does not exist, `run_git` fails there, and the union in `git_facts.py:191` falls back to `_with_all_staged(())`, which is the index only. When the target exists (the `&` case), the wrong file is read. The sensitive_content union pass at `sensitive_content.py:1017` and the docs_qa/plan_qa `GitFacts` reads go wrong the same way.
- Fix (fails closed): when `reading.moves` is non-empty, judge the union of both readings, i.e. the named paths read from the moved directory **and** from the hook cwd. Concretely:
  - add a second working-tree `_ScanPass` with `directory=<start dir>`;
  - in `GitFactsBase.staged_changes`, merge the pathspec diff from both directories;
  - make docs_qa/plan_qa build their view from both as well.
- A cheaper partial fix: fall back to cwd when the moved path is not an existing directory, and treat a cd followed by `&` or `|` as subshell-scoped. That alone still leaves conditional cds (`a && cd x`) wrong. Either way, add every row above as a regression test.

**2. The new test in `tests/unit/utils/test_git_facts.py` (around line 531, `test_a_moved_reading_is_the_index_plus_the_paths_named_where_it_moved_to`) tests nothing (confidence 95%).**
- Problem: it calls `commit_facts(...)` with no `cwd`, so `pathspec_directory` never applies the move (`if cwd and reading.moves`). `d/a.txt` is already in the index, so the union includes it either way.
- Evidence: `probe_messy.py` gives identical, passing results against main's source.
- Fix: pass `cwd=messy`, and assert on a **named, unstaged-only** file under `d/` (for example add `d/c2.txt`), so the test fails on main.

## Important: non-blocking, file as plan tasks

**3. Pre-existing on main, not caused by this branch (confidence 85%).**
- `cd sub || cd x; git commit f.txt` misses the term on both main and branch: `_after_directory_change` in `git_commit_parsing.py:843-866` stacks both cds whatever the `||` does. Fix: a cd after `||` or `&&`, or an alternative cd, should be recorded as `None`.
- With two commits in one command, the second commit's pathspecs are never scanned: `extract_commit_form` takes one form, and `moves=()`. Fix: union over every commit's pathspecs, from each commit's own directory.

**4. `remote_docs_commit_gate.py:107-119`: `cd <nested-worktree> & git commit` stands down even though the commit runs in the project (confidence 70%).**
- The backgrounded cd is not applied by bash, but the gate treats the commit as running in the other repository. Same root cause as #1, so it is fixed by the same `&` handling.
- Separate observation, not a regression: a worktree of this same project now gets no remote-docs gate at all. Main read the wrong index there anyway, so it was not really gated before either. Suggestion: judge the foreign checkout against its own index when its common dir equals the project's.

## Answers to your questions

- **(2) `ls-files --error-unmatch`:** it behaves the same as main's per-pathspec loop (`lsf.bash`).
  - Deleted on disk but still indexed: matches.
  - HEAD-only path (`git rm --cached`): the single call fails, then each pathspec is retried and `diff HEAD` finds it.
  - A directory pathspec, `*.txt` and `:!d` all match; an unknown path fails.
  - A batch call failing for any other reason drops to the old per-pathspec route, so nothing is lost.
- **(3) remote_docs mistaking the same repo for a foreign one:** I found no such case. A cd into a missing directory walks up to the project; subdirectories and `cd $VAR` are still judged (tested). `project_root` is resolved, as `staged_lint_gate` already relies on. The only exception is item 4.
- **(5) Conflicts:** against main, only `CLAUDE/Plan/00474-niggles-ledger-seventeen/NIGGLES.md` conflicts (ledger text). n241 merges cleanly onto main and onto this branch, and the two branches touch no files in common.

**Done well:** the `-C`/pushd/subshell/symlink/space handling, the `--git-dir`/`GIT_*`/`$VAR` fallback, the single ls-files call, and the sensitive_content tests that check both directions.

**Probes and evidence** (all under `/workspace/untracked/scratch/n299-review/`): `probe_sensitive.py`, `probe_docs.py`, `probe_messy.py`, `lsf.bash`, `run_with_src.py`, `compare.py`, `main.json`, `branch.json`, `pytest.txt`.

**Verdict: MERGE-WITH-FIXES.** Fix #1 (both-directories union plus the regression rows) and #2 (the test that tests nothing) before merging. File #3 and #4 as plan tasks.