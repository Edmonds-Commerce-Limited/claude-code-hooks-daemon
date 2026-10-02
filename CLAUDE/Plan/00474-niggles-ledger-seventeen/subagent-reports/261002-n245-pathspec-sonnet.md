# N245: every commit gate judges the tree a pathspec commit records

Branch `worktree-n245-pathspec`. N246 is NOT done; see the last section.

## Git semantics, checked against real git (not from memory)

Throwaway repos, and the differential tests below, which make the real commit
and compare. With a file staged AND edited again on disk:

- `git commit <paths>` (default `--only`) records HEAD with the named paths'
  WORKING-TREE content. The index is ignored for them, and every other staged
  change is left out of the commit. A named path the working tree deleted is
  removed. A named path the working tree put back to HEAD records HEAD's content.
- `git commit --include <paths>` records the index, with the named paths'
  working-tree content laid over it (same three cases for named paths).
- A bare commit records the index.

## Root cause and what each gate judged before

All the names in the carried text (`recorded_content`, `reads_index`,
`includes_index`, `judged_views`) are absent on main, as N244 said. The real
shapes on main:

| Gate                          | Before, for `git commit <paths>`                                                                                                                        |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sensitive_content`           | scanned `git diff --cached`: the whole index. Missed a term in a named file's UNSTAGED edit (a real hole), and denied a staged term in an unnamed file. |
| `staged_lint_gate`            | listed `git diff --cached` names, linted the disk: wrong file set both ways.                                                                            |
| `remote_docs_commit_gate`     | same list as lint, same wrong set.                                                                                                                      |
| plan QA (`staged_context`)    | `committed_from=None if pathspecs`: read the DISK tree. Saw untracked folders the commit does not hold.                                                 |
| docs QA (`staged_context`)    | correct for `--only` (diff HEAD plus disk text), wrong for `--include`.                                                                                 |
| `guard_config_commit_gate`    | correct for `--only`; `--include` of an unrelated path skipped a staged config.                                                                         |
| `conflict_marker_commit_gate` | already handles pathspec and `--include` (the union form). Not touched.                                                                                 |

## What changed

- `utils/git_commit_parsing.py`: `CommitForm(pathspecs, include, pathspec_from_file)`,
  `extract_commit_form`, `commit_includes_index` (reads `-i`, `--include` and
  unambiguous abbreviations; a value or a name after `--` is not the flag).
- `utils/git_facts.py` (the N244 machinery): `GitFactsBase(..., include=)`.
  `index_listing` and `index_texts` now answer for the form: a listing value
  `WORKING_TREE` means "the commit takes this path from the disk", and
  `index_texts` reads it there. New `named_paths()` (what the pathspecs select),
  `recorded_text(path)`, and `staged_changes()` under `--include` (unnamed staged
  changes plus named working-tree changes). An unreadable repository is `None`,
  never an empty tree.
- plan QA `staged_context(include=)` always builds the committed view from the
  facts, so one reading serves bare, pathspec and include. Disk fallback remains
  when git cannot list.
- docs QA `staged_context(include=)` reads each document with `recorded_text`.
- `staged_lint_gate`, `remote_docs_commit_gate`: the file set comes from the
  facts. (`remote_docs_commit_gate.staged_reader` now takes the `CommitForm`.)
- `sensitive_content`: `_recorded_passes` decides the questions put to git.
  Bare: index. `-a`: working tree. Pathspec: working tree against HEAD for the
  named paths only, asked from the command's directory. `--include`: index with the
  named paths skipped, plus that pass. `--pathspec-from-file`: index AND working
  tree, each over everything (a superset, since the file cannot be read). A
  pathspec git cannot answer for, or one matching nothing, is scanned as the
  index, so a word misread as a path never leaves a commit unscanned.
- `guard_config_commit_gate`: `--include` with an unrelated pathspec reads the index.
- Removed the now-stale `docs_qa/context.py` `silent-fallback` entry from
  `scripts/qa/error_hiding_exclusions.json` (the audit flagged it stale after the
  try/except went away). No entry was added.

## TDD: failures seen first

- `test_git_commit_parsing.py`: `ImportError: cannot import name 'CommitForm'`.
- `test_git_facts.py`: first run, `1 failed, 29 passed`
  (`test_pathspec_commit_is_head_with_the_named_working_tree_content`).
- `plan_qa/test_context.py`: 4 failed (untracked folder seen, staged folder seen,
  `include` kwarg, unnamed document read from the index).
- `test_remote_docs_commit_gate.py`: 11 failed, among them
  `test_a_pathspec_commit_does_not_record_an_unnamed_staged_document`.
- `test_staged_lint_gate.py`: 3 failed (all new `TestEachCommitFormLintsWhatItRecords`).
- `test_guard_config_commit_gate.py`: 1 failed (`--include` unrelated path).
- `test_sensitive_content.py -k EachCommitForm`: 9 failed, 5 passed. The failures
  include `test_pathspec_commit_denies_a_term_in_a_named_files_unstaged_edit`
  and the public-pattern twin: on main those commits passed with the term in them.
- Docs QA tests were written together with the code and the `include` kwarg;
  their red run was not captured separately (the kwarg alone would raise `TypeError`).

Differential tests (`TestTheRecordedTreeOfEachCommitForm`) build an index, a
working tree and HEAD that disagree on seven files, predict the recorded tree,
make the real commit and compare, for bare, `--only` (file and directory
pathspecs), `--include` and an unnamed-change case.

## Each security claim, proved

`TestEachCommitFormScansWhatItRecords` (real git, secret word list):

- bare: staged term denied;
- pathspec: term in a named file's unstaged edit denied (public pattern too);
  term staged new in a named file denied; directory pathspec denied; pathspec
  relative to a subdirectory cwd denied; staged term in an unnamed file allowed;
  staged term the disk repaired allowed;
- include: unnamed staged term denied; named unstaged term denied; repaired term allowed;
- `--pathspec-from-file`: a staged term denied, and an unstaged tracked term denied;
- a pathspec matching nothing: scanned as the index, denied;
- `-a`: unchanged, denied.

## QA (targeted)

- `ruff check` on `src` and the touched test directories: clean.
- `black --check --target-version py311` on `src` and `tests/unit`: clean.
- `mypy` on the 10 changed source files: clean.
- `audit_error_hiding.py`: clean (after removing the stale entry).
- `check_input_contract.py`: clean.
- `run_pyright_check.py --json`: 0 errors. The first run found 1: an existing test
  (`tests/unit/handlers/test_unstattable_caller_paths.py`) passed `_lintable_files`
  a string; it passes a list now.
- pytest: 4141 passed over `tests/unit/plan_qa`, `docs_qa`, `qa`, the git utils
  tests, the six gates, the evasion tests, `test_unstattable_caller_paths`,
  `test_pretooluse_fail_closed_tagging`, `test_merge_qa_report` and `test_cli_plan_qa`.
  The full suite was not run.

## Not covered

- `git commit -a` in plan and docs QA: they read the index. (`sensitive_content`
  and `guard_config_commit_gate` already handle `-a`.) Recorded tree for `-a` is
  `--only` with the pathspec `.`, so it is a small follow-up.
- An unborn HEAD with a pathspec: `git diff HEAD` fails, the facts return nothing,
  so lint and remote-docs check nothing (`sensitive_content` falls back to the index).
- Bare commit in `remote_docs_commit_gate`: it lists the index but reads the disk
  for content. The same class as N244, for a bare commit, not a pathspec one.
- `staged_lint_gate` lints the disk file, not the index blob, for a bare commit.
- `--diff-filter=ACM` drops a staged rename with edits in `sensitive_content`
  and the lint gate. This was already so.
- The checks that open files themselves (N244's list) still read the disk.
- Each `--include` pass in `sensitive_content` bounds its own bytes, so a worst
  case holds two bounds' worth.

## N246: what it still needs

The overlay is now available (`include=True` plus a pathspec list gives index plus
the named paths' working tree). Not done, because three pieces do not exist:

1. Reading the same-command `git add X` (and `rm`, `mv`, `reset`, `restore --staged`)
   in front of the commit. `git_invocations` returns them in order with their
   directories, but every gate here finds only the first commit with
   `extract_commit_form`. The form needs the preceding mutations, and each of the
   gates must call the walker, which is a change in six places. `-A`, `-u`, `.`,
   `-f`, `-N`, `-p` and `--pathspec-from-file` each change what the add records.
2. Untracked files. `git add X` adds an untracked path; `--include` refuses one. The
   facts would need `ls-files --others --exclude-standard` as a source of
   `WORKING_TREE` entries and of `named_paths()`.
3. `sensitive_content` reads `git diff` output, and a diff cannot show an
   untracked file's lines. It would need to read those files directly, with the
   same bounds and the same protected-path skip.

## Round 2 (review by Opus, threat-model re-grade)

Rule applied: a gate narrows to the pathspec view only when the reading is
certain; on every other shape it judges the index PLUS the named paths' working
tree, never less than main's whole-index read. Branch merged with origin/main
first (plan docs took main's version; they carry only ledger bookkeeping).

### What changed, per finding

- **B1/B2 (one shared test, three gates).** `git_commit_parsing.read_commit_form`
  returns a `CommitReading(form, certain)`. Certain means: exactly one
  `git commit` found by `git_invocations`, no `cd`/`pushd`/subshell-cd before
  it, no `-C`/`--git-dir`/`--work-tree` global option, no `GIT_*` assignment on
  it, and no pathspec word carrying `$`, a backtick, `{` or `~`.
  `git_facts.commit_facts(reading, repo_root, cwd)` is the one factory all three
  gates call: narrowed facts only when certain AND `every_pathspec_matches()`
  (each pathspec selects something, git answered); otherwise
  `GitFactsBase(..., union=True)`, whose `staged_changes()` is the named paths'
  changes against HEAD plus every staged change. `sensitive_content` uses the
  same facts: a union is `[index pass, working-tree pass over the pathspecs
  from the repo root]`. A git that cannot diff HEAD (fresh repository) falls
  back to the index in `staged_changes()` instead of reporting nothing.
  `remote_docs_commit_gate` and `staged_lint_gate` now resolve pathspecs from
  the hook's cwd (when inside the project root), as `sensitive_content` does,
  and read files from the project root.
  `remote_docs_commit_gate.staged_reader` now takes `(CommitReading, cwd)`.
- **B3.** `NO_RELATIVE` (`--no-relative`) is on every `git diff` in
  `GitFactsBase` (pathspec, `--cached`, `--name-only`) and on both
  `sensitive_content` calls (`--numstat` and the patch call). `ls-files` has no
  `--no-relative` option and ignores `diff.relative`, but it reports
  cwd-relative paths by default (verified: `q` vs `sub/q` from `sub/`), so the
  pathspec-bearing call keeps `--full-name`, and every other `ls-files`/`ls-tree`
  call runs from the repo root (`_git_output(..., in_directory=True)` is the
  only way to run from the command's directory).
- **S1.** Verified with real git (`untracked/scratch/s1/verify.py`): after
  `git rm --cached p; echo X >> p`, `git diff HEAD` says `D p` and
  `git commit -m x p` records `p` WITH the edit. `GitFactsBase.resurrected_paths()`
  names such paths (status D, file on disk); `staged_changes()` reads them as
  `M`, `_recorded_listing` maps them to `WORKING_TREE`, and `sensitive_content`
  scans the whole file (`_resurrected_haystacks`, same exclusions and per-file
  bound). The extra spawn happens only when the pathspec diff shows a `D`.
- **S2.** Real-git tests per gate, reusing the reviewer's cases: `cd`, `-C`,
  subshell `cd`, `pushd`, a second commit, `$F`, `$(...)`, `{a,b}`, a pathspec
  that matches nothing (alone and among others), `diff.relative` from a
  subdirectory (staged and unstaged), and the `rm --cached` edit; each also has
  a counter-test that a certain reading still narrows. Plus unit tests for
  `read_commit_form` and `commit_facts`.

### Red evidence (on 6daf719cf, new tests only)

`pytest` over the three new classes: `30 failed, 2 passed` (the two passes are
the "a certain reading still narrows" counter-tests). Per gate: sensitive_content
12 failed (4 cd/-C/subshell/pushd, second commit, 3 shell-built pathspecs,
unmatched-among-others, 2 diff.relative, rm --cached), remote_docs 9 failed (7
uncertain shapes, diff.relative, rm --cached), staged_lint 9 failed (7, diff.relative,
rm --cached). Output kept in `untracked/scratch/red.txt` of the worktree.

### QA (targeted)

ruff, black --check --target-version py311, mypy on the 10 changed files: clean.
`audit_error_hiding.py`, `check_input_contract.py`, `run_pyright_check.py --json`:
exit 0. pytest: the three gate test files, `tests/unit/utils`, `tests/unit/docs_qa`,
`tests/unit/plan_qa`, the docs/plan/guard-config commit-gate tests and
`test_qa_package_dependency_direction.py`: all pass (one memoisation test in
`plan_qa/test_gitfacts.py` caught an extra spawn, fixed by resolving
resurrection only when the diff shows a `D`).

### Not done

The docs_qa, plan_qa and guard_config gates still read `extract_commit_form`
directly, so they keep round 1's narrowing on the uncertain shapes; they were
outside this round's three-gate scope.
