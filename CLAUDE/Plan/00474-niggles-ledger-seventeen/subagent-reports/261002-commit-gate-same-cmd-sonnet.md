# Commit gates: same-command add (N246/N61), every commit (N307), every cd directory (N306)

Branch `worktree-commit-gate-same-command`, based on `e27b9451a`. Agent: Sonnet 5.5.

## What changed

- **N246 / N61.** `utils/staging_simulation.py` (new) runs each `git add` that comes before the last
  `git commit` of the command against a COPY of the index, with new blobs written to a scratch object
  directory (`GIT_INDEX_FILE`, `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`). The real index,
  object store and working tree are never written (a test compares the index bytes and `count-objects`).
  `sensitive_content`, `staged_lint_gate`, docs QA, plan QA and `remote_docs_commit_gate` read git with that
  environment, so the index they judge is the one the commit records. An add whose scope cannot be read
  (a `$VAR`, `$( )`, `{a,b}`, `-p`, `--pathspec-from-file`, `--chmod`, a `cd -`) is applied as `git add -A`, so
  the judged set is never smaller than the add could stage. A pathspec git rejects ("did not match", "ignored
  by .gitignore") stages nothing, as in the real command. An add in another repository is skipped.
- **N307.** `CommitReading.runs` carries every commit (form, moves, `-a`); `CommitReading.stagings` carries the
  adds. `commit_scopes` gives each commit's pathspecs the directory THAT commit runs in. `GitFactsBase` takes
  `scopes`, so a second commit's pathspecs and a second commit's `-a` are judged; docs and plan QA use
  `union` for a multi-commit command. `guard_config_commit_gate` reads every commit for `-a` and pathspecs.
- **N306.** `landing_directories` returns every directory a `cd` chain may land in (every subset of the
  moves that may not have taken effect, then the `-C` operands). `run_directories` keeps those inside the
  repository. This replaces `unmoved_directories` and `pathspec_directory`.

Not done: `guard_config_commit_gate` is advisory only (it never denies) and still reads the real index for a
same-command add. A command with more than five `cd`s that may not take effect tries only the whole chain,
each alone, and none.

## Red to green

- `tests/unit/handlers/pre_tool_use/test_sensitive_content_same_command.py`, run on the unchanged tree:
  `29 failed, 17 passed`. After the change: 46 passed.
- All six new handler-level test classes (sensitive_content, staged_lint_gate, docs QA, plan QA,
  remote_docs, guard_config) run against an export of `e27b9451a`'s `src`: `51 failed, 216 passed`
  (the 216 are rows whose behaviour is unchanged). After the change: all pass.
- New unit files: `tests/unit/utils/test_staging_simulation.py` (36 tests), plus classes in
  `test_git_commit_parsing.py` and `test_git_facts_command_directory.py`.
- Touched set (`tests/unit/utils/test_git_*`, `test_staging_simulation.py`, `tests/unit/docs_qa`,
  `tests/unit/plan_qa`, `test_blocking_handler_evasion.py`, and the six gate test files): 2541 passed.
- Coverage of the new and changed modules over that set: `staging_simulation.py` 100%, `git_facts.py`
  94.6%, `git_commit_parsing.py` 95.1% (the uncovered lines in both are older code).

## Static checks

ruff clean, black `--target-version py311` clean, mypy clean on the 12 touched source files and the new
test, `run_pyright_check.py --json` 0 errors 0 warnings, `audit_error_hiding.py` clean (a `try/except OSError` that logged was replaced by `TemporaryDirectory(ignore_cleanup_errors=True)`).

## Git-ground-truth probe (55 rows)

Probe: `untracked/scratch/commit-gate-same-cmd/probe_sensitive.py` (a copy of the N299 review probe, plus 29
rows for the new shapes and an ignore rule). `truth` is whether the term is in `git log -p` after running the
command for real. Left is `main` (`472343f7b`), right is this branch.

- No row has truth=RECORDED and branch=allow.
- Rows main allowed and the branch denies, where the term IS recorded: 21 (the fixes).
- Rows main denied and the branch allows, where the term is NOT recorded: 1 (`two-commits-unrelated`, a
  false positive removed).
- Rows main allowed and the branch denies, where the term is NOT recorded: 1, `cd-or-cd-second`
  (`cd x || cd sub; git commit f.txt` with the term in `sub/f.txt`). `cd x` succeeds in the probe, so git
  records `x/f.txt`. The reading cannot know whether `cd x` fails, and N306 asks for every directory a `cd` could
  land in, so this is the price of the fix. It needs a decision from the coordinator if it matters.

```
cd-sub-rel-up        truth=RECORDED main=DENY  branch=DENY
cd-sub-a             truth=RECORDED main=DENY  branch=DENY
C-sub                truth=RECORDED main=DENY  branch=DENY
cd-sub-cd-up         truth=RECORDED main=DENY  branch=DENY
subshell-in          truth=RECORDED main=DENY  branch=DENY
subshell-out         truth=RECORDED main=DENY  branch=DENY
top-magic            truth=RECORDED main=DENY  branch=DENY
glob                 truth=RECORDED main=DENY  branch=DENY
pushd                truth=RECORDED main=DENY  branch=DENY
space-dir            truth=RECORDED main=DENY  branch=DENY
symlink              truth=RECORDED main=DENY  branch=DENY
cd-missing-semi      truth=RECORDED main=DENY  branch=DENY
test-and-cd          truth=RECORDED main=DENY  branch=DENY
cd-or-cd             truth=RECORDED main=allow branch=DENY   (N306, fixed)
cd-bg                truth=RECORDED main=DENY  branch=DENY
two-commits          truth=RECORDED main=allow branch=DENY   (N307, fixed)
cd-then-C-up         truth=RECORDED main=DENY  branch=DENY
C-C                  truth=RECORDED main=DENY  branch=DENY
abs-cd               truth=RECORDED main=DENY  branch=DENY
dashdash             truth=RECORDED main=DENY  branch=DENY
pushd-popd           truth=RECORDED main=DENY  branch=DENY
hookcwd-sub-up       truth=RECORDED main=DENY  branch=DENY
include              truth=RECORDED main=DENY  branch=DENY
cd-home              truth=RECORDED main=DENY  branch=DENY
cd-sub-plain         truth=RECORDED main=DENY  branch=DENY
cd-missing-staged    truth=RECORDED main=DENY  branch=DENY
add-untracked        truth=RECORDED main=allow branch=DENY   (N246, fixed)
add-semi             truth=RECORDED main=allow branch=DENY   (fixed)
add-force-ignored    truth=RECORDED main=allow branch=DENY   (fixed)
add-ignored-noforce  truth=absent   main=allow branch=allow
add-A                truth=RECORDED main=allow branch=DENY   (fixed)
add-dot              truth=RECORDED main=allow branch=DENY   (fixed)
add-u-tracked        truth=RECORDED main=allow branch=DENY   (fixed)
add-u-untracked      truth=absent   main=allow branch=allow
add-multi            truth=RECORDED main=allow branch=DENY   (fixed)
add-other-file       truth=absent   main=allow branch=allow
add-glob             truth=RECORDED main=allow branch=DENY   (fixed)
add-var              truth=RECORDED main=allow branch=DENY   (fixed, add -A fallback)
add-cd               truth=RECORDED main=allow branch=DENY   (fixed)
add-cd-wrong         truth=absent   main=allow branch=allow
add-C                truth=RECORDED main=allow branch=DENY   (fixed)
add-pathspec-commit  truth=RECORDED main=allow branch=DENY   (fixed)
add-then-commit-a    truth=RECORDED main=allow branch=DENY   (fixed)
add-after-commit     truth=absent   main=allow branch=allow
add-between-commits  truth=RECORDED main=allow branch=DENY   (fixed)
add-nosuch           truth=absent   main=allow branch=allow
second-pathspec      truth=RECORDED main=allow branch=DENY   (N307, fixed)
second-commit-a      truth=RECORDED main=DENY  branch=DENY
second-own-dir       truth=RECORDED main=allow branch=DENY   (N307, fixed)
two-commits-unrelated truth=absent  main=DENY  branch=allow  (false positive removed)
cd-or-cd-first       truth=RECORDED main=allow branch=DENY   (N306, fixed)
cd-or-cd-second      truth=absent   main=allow branch=DENY   (new fail-closed false positive, see above)
cd-or-cd-and         truth=RECORDED main=allow branch=DENY   (N306, fixed)
cd-or-cd-hook-dir    truth=absent   main=DENY  branch=DENY   (not new)
cd-or-cd-x           truth=RECORDED main=allow branch=DENY   (N306, fixed)
```

## Ledger

N246, N306 and N307 in `CLAUDE/Plan/00474-niggles-ledger-seventeen/NIGGLES.md` and N61 in
`CLAUDE/Plan/00483-threat-model-conformance-audit/TRIAGE-ledger-466.md` are marked Fixed on the branch, not
yet merged.
