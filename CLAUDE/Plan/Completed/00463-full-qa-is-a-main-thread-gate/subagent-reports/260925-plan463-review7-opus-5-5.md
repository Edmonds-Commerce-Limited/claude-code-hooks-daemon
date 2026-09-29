# Plan 00463 seventh review: verification of the review 6 fixes (Opus 5.5)

**Scope.** Branch `worktree-plan-463-full-qa-gate` at `700f0d34`. The fixes are in `5d2b62e4`;
`700f0d34` is an empty commit that corrects its message. I read review 6, the implementation
report's "Review 6 fixes" section and `git diff 01f9ef51..700f0d34`, checked every review 6 item,
judged the five design choices I was asked about, then attacked the new code. The review was
read-only. Nothing tracked was edited or committed, and `git status` in the worktree is clean.
This report is the only new file, and it is uncommitted. One gitignored file changed as a side
effect: a whole-repository `audit_error_hiding` run rewrote the worktree's
`untracked/qa/error_hiding.json` (it now holds the HEAD detector's result, 0 violations).

**How it was probed.** Every probe is under `/workspace/untracked/scratch/probe_463v7_*`.
Hand-built payloads carry `synthetic_source: review-463-v7`.

- `probe_463v7_rerun_463v5_*.txt` and `probe_463v7_rerun_463v6_*.txt`: review 5's and review 6's
  own probes, re-run against HEAD.
- `probe_463v7_r6items.py` and `_out.txt`: review 6's reproducers, item by item (55 rows).
- `probe_463v7_blocker.py` and `_out.txt`: a NEW corpus of 239 rows, none of them in the v5 or v6
  corpora, through the configured handler with a sub-agent event. The fixtures are built in
  `probe_463v7_fx/`.
- `probe_463v7_filebomb.py`, `_out.txt` and `probe_463v7_m1long_*.txt`: the cost of the code-file
  reader at or under the parse cap.
- `probe_463v7_exec_scan.py`, `probe_463v7_qa_scripts_out.txt`, `probe_463v7_exec_why_out.txt` and
  `probe_463v7_fx2_out.txt`: the repository's own scripts run by their paths.
- `probe_463v7_proc.py` and `_out.txt`: `/proc` files, whose `st_size` is 0.
- `probe_463v7_find_exec_out.txt`: `find -exec`.
- `probe_463v7_m4b.py`, `probe_463v7_m5.py` and their `_out.txt`: the glob-reader guard, run in a
  fresh clone (`probe_463v7_repo`, left clean) and in-process.
- `probe_463v7_{n2,n2b,finish,fences,loop,n2_attack,n2_attack2}*`: N2 end to end in a fresh clone of
  HEAD (`probe_463v7_n2repo`, with `main` in `probe_463v7_n2repo_m`). Tools are faked by
  `probe_463v7_n2_fake_run.py`; `main-moved`, `--start`, `--advance` and `--finish` are the
  clone's real code.
- `probe_463v7_audit*`, `probe_463v7_pathexists*`: the `audit_error_hiding` change and
  `path_exists(unreadable_means=False)`.
- `probe_463v7_chain_timing_out.txt`: whole-chain time at 32 KiB and 94 KiB (review 6's script).

**Targeted tests (no full suite):** 1323 passed, 0 failed (`probe_463v7_targeted_pytest.txt`).
The files were the blocker test, shell segmentation, `test_audit_error_hiding.py`,
`test_glob_readers_are_declared.py`, `test_llm_qa_main_moved.py`, and the two process-probe test
files that use the shared peel. `ruff check`, `black --check` and mypy are clean on the 9 changed
Python files (`probe_463v7_qa_tools.txt`).

**Counts.**

- Review 6 findings: every one is fixed for the shape review 6 reported, except **M1, which is not
  fixed**. Its 64 KiB fixtures are now only scanned (0.00 to 0.03 s), but a file under the parse
  cap is parsed again at every reference (Major M1 below). Review 6's 279-row corpus gives 0 false
  denies and 2 false allows, both the documented limit. Review 5's 266-row corpus gives 0 false
  allows; its 2 "false denies" are its old expectations for a bare `| xargs pytest` and a lone
  `$(git diff ...)`, which review 6 M2 made denies. All 55 of review 6's reproducers give the
  verdict review 6 asked for.

- New findings: **0 blocker, 2 major, 5 minor, 6 nit.** One major is review 6 M1, re-opened.

- The new corpus has 239 rows (103 expect deny, 136 expect allow):

  - 0 untagged false denies;
  - 5 false allows (minor m1);
  - 22 tagged denies. 11 follow from a design choice I was asked to judge (below), and 11 fail
    closed on something the handler cannot see, of which 2 are realistic (minor m3);
  - 8 tagged allows, all deliberate obfuscation.

  On its 54 realistic targeted commands, **no false deny that is not explained**. There are 2
  denies: `pytest --reuse-db tests/unit/qa` (an unknown plugin flag before the path; the reference
  documents this at :1464) and `eval "$(pyenv init -)"; pytest tests/unit/qa` (the stdin-producer
  choice).

- A separate count, which the corpus above does not show: **6 of the 31 `scripts/qa/*.py`
  scripts, run as their own docstrings say (`python scripts/qa/X.py`), are denied.** Among them are
  `run_changed_tests.py`, the targeted runner, and `check_repo_hygiene.py` (Major M2).

---

## Review 6, finding by finding

| #   | Verdict           | Evidence                                                                                                                                                                                                                                                                                                                                                   |
| --- | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| M1  | **NOT FIXED**     | The review 6 fixtures take 0.00 to 0.03 s (`probe_463v7_rerun_463v6_filebomb.txt`). But the memo holds a file's TEXT, not its verdict, and the parse budget is charged only on the first read. A 58-byte command takes 75.8 s, and a 13 KB one 150.6 s (Major M1).                                                                                         |
| M2  | FIXED             | All 8 review 6 rows are right. In the new corpus, 46 listing rows give 0 false allows. `xargs -L1`/`-n1`/`-0` without `-r` are denied, and `xargs -I{}`, which runs nothing on empty input (checked with GNU xargs), is allowed. HANDLER_REFERENCE.md:1432 shows `xargs -r`. Residual: `$(git merge-base main HEAD)` in the listing is refused (minor m3). |
| m1  | FIXED             | `llm_qa.py tests` from `.claude/hooks/handlers/pre_tool_use`, with `cd`, with `python3` and with the event `cwd` there: all denied. `pytest tests` there stays targeted, as review 6 said it should.                                                                                                                                                       |
| m2  | FIXED, residual   | All 15 of review 6's rows are denied, 8 of them with `JUDGED UNSEEN`. A path this command writes is unseen. Residual: `$(cat f)` is read in 2 positions but not in 4 others, a producer path held in a variable is "absent", and `bash -s -- args` reads its first argument as the script (minor m1).                                                      |
| m3  | FIXED             | All 9 rows are denied. The 24 new Python rows (flag clusters, `-X`/`-W` values, `import ... as`, `from ... import main as`, `_pytest`, `py.test`) are all right.                                                                                                                                                                                           |
| m4  | FIXED             | `PYTEST_ADDOPTS=tests`, inline and exported, and `@args.txt` are denied. `PYTEST_ADDOPTS='-x -q' pytest tests/unit/qa` is allowed.                                                                                                                                                                                                                         |
| m5  | FIXED, residual   | Load-bearing: review 5's reproduction goes RED with the guard (1 failed, 33 passed) and GREEN with the pattern check removed (26 passed). All 15 scanner spellings are seen, and the 4 named spellings of the new directory are caught. Residual: 7 of 16 further spellings pass (nit n4).                                                                 |
| m6  | FIXED             | All 6 rows are allowed.                                                                                                                                                                                                                                                                                                                                    |
| m7  | FIXED             | `{t..t}ests`, `a{l..l}l` and `RUNNER=${RUNNER:-pytest}; $RUNNER` are denied, and `T=${T:-tests/unit/qa}; pytest $T` is allowed.                                                                                                                                                                                                                            |
| m8  | FIXED             | L3 and S10 now give the main-moved verdict and then only `--advance`. A2 and A3 (one and two merges of `main`) reach `unmoved` with one recheck each. Residual: the printed recheck range can be stale (minor m5).                                                                                                                                         |
| n1  | FIXED             | A 300-character component is allowed and nothing raises. Each lookup logs a WARNING (nit n5).                                                                                                                                                                                                                                                              |
| n2  | FIXED             | Every fail-closed deny I met in the corpora carries `JUDGED UNSEEN`. The brace cap is at HANDLER_REFERENCE.md:1429.                                                                                                                                                                                                                                        |
| n3  | FIXED (tightened) | `--finish` now refuses a same-tree non-merge child, a grandchild, an octopus, an unrelated same-tree merge, `merge(X, C)` with X not an ancestor, and `-p C -p C`. The certified head, and a same-tree merge with it as either parent, are accepted.                                                                                                       |
| n4  | FIXED             | GNU `timeout 5 -- echo hi` fails with "failed to run command '--'", so allowing `timeout 60 -- pytest tests` is right. `timeout -- 60 pytest tests` is denied.                                                                                                                                                                                             |
| n5  | FIXED             | `alias` under `expand_aliases`, `hash -p`, `coproc` and nested `env -C` are denied. Both named-from-pieces limits remain, as documented.                                                                                                                                                                                                                   |
| n6  | Outside 463       | The quoted-heredoc chain row is the same as before (Timing).                                                                                                                                                                                                                                                                                               |
| n7  | FIXED             | HANDLER_REFERENCE.md:1462 names `tests/unit/qa/test_llm_qa*.py`, which is allowed.                                                                                                                                                                                                                                                                         |

---

## The design choices

1. **`bash -c "$(cat f)"` reads `f`: sound.** `bash -c` runs exactly the text the substitution
   prints, apart from trailing newlines, so reading `f` is the same judgement as `cat f | bash`. A
   write to `f` in the same command makes it unseen, which is right. The gap is consistency: the
   same `$(cat f)` is not read in the other positions where its output becomes code (minor m1).

2. **Under `option_grammar`, a positional word is a target: sound.** pytest aborts before
   collecting anything when an argument names nothing, so a word that is not a path runs nothing.
   `cd tests/unit && pytest tests` and `pytest nonexistent_dir` are allowed, and
   `pytest tests/unit/qa -- tests` is denied. What makes a full run look targeted is not this rule
   but its neighbour, a flag's optional value. That is handled: `pytest --cov tests/unit/qa` is
   denied, and it really does collect the whole suite with pytest-cov 7.1 (checked in
   `probe_463v7_pyt`, where `--cov tests/a` collected `tests/b` too). `pytest ""` is also full,
   checked the same way, and is denied. The cost is an unknown boolean plugin flag before the path
   (nit n1), which the reference documents.

3. **A `--pyargs` module not found is unseen: sound.** A package installed elsewhere can hold the
   project's tests, so it is a real unseen case. It costs one rare false deny
   (`pytest --pyargs claude_code_hooks_daemon.utils`, a package with no tests).
   `--pyargs tests.unit.qa` is allowed and `--pyargs tests` denied.

4. **An unknown stdin producer is denied: right for project files, wrong for environment setup.**
   Refusing `cat f g | bash`, `awk ... | bash` and `git show main:x.sh | bash` is the review 6
   direction, and it holds. But the rule is unconditional. It also denies commands that have no
   QA in them and, unlike an installer, have no escape: `eval "$(ssh-agent -s)"`,
   `eval "$(pyenv init -)"` and `source <(kubectl completion bash)` set up the shell for the
   commands after them. The Bash tool keeps no shell state between calls, so they cannot be moved
   to a separate call. `curl ... | sh` can be (download it, then `bash file` in a second call, which
   is read). In this repository, `install.sh` and `scripts/install/prerequisites.sh` are denied by
   this rule, which is acceptable, since a sub-agent should not be installing. See minor m2.

5. **`git log` and `git show` are not listings: sound.** Both print commit messages unless
   steered, and once steered (`--format=`) the listing rule refuses them anyway. The targeted
   equivalent, `git diff --name-only HEAD~1 -- tests | xargs -r pytest`, is allowed, so the cost is
   one respelling. `git diff-tree --name-only` and `git ls-files -m` are refused too. Both could be
   listings, but they are rare, so this is not worth a finding.

---

## Blockers

None.

## Major

### M1. Review 6 M1 is not fixed: a file under the parse cap is parsed again at every reference

**Where:** `subagent_full_qa_blocker.py`:

- `_read_code` (:3438-3459) caches the file's TEXT per path;
- `_read_new` (:3485-3487) charges `parse_budget` only on the first read;
- `_full_run_in_code_file` (:3401-3409) calls `_invocations` on the cached text at EVERY reference,
  with no memo of the verdict;
- `files_deep >= _MAX_NESTING` (:3394) bounds the depth, but not the number of references at each
  level.

So a file of k lines that each feed the file itself is parsed 1 + k + k² times, each parse costing
O(k). The HEAD handler alone, each case in its own process (`probe_463v7_filebomb_out.txt`,
`probe_463v7_m1long_*.txt`):

| Command                                                            | Length | Handler     |
| ------------------------------------------------------------------ | ------ | ----------- |
| `bash self10.sh` (10 lines of `bash self10.sh`)                    | 58     | 0.41 s      |
| `bash self30.sh`                                                   | 58     | 10.0 s      |
| `bash self60.sh`                                                   | 58     | **75.8 s**  |
| `bash self100.sh`                                                  | 59     | **494 s**   |
| `cd fx && bash rel60.sh` (the same, named relatively)              | 63     | 21.4 s      |
| `bash a60.sh` (60 feeds of b, each 60 feeds of c)                  | 55     | 9.7 s       |
| `bash a150.sh`                                                     | 55     | over 60 s   |
| `bash words32k.sh; ` × 200 (a 32 KiB file of `echo a b c d e f g`) | 12,400 | 45.2 s      |
| `bash heredocs32k.sh; ` × 200 (a 32 KiB file of `cat <<'E'`)       | 13,000 | **150.6 s** |
| 32 KiB of `bash words32k.sh;` (about 500 references)               | 32,757 | 78.8 s      |

`self100` ran beside the chain-timing probe, so its 494 s is somewhat inflated. The growth is
still about cubic: 0.4 s, 10 s, 76 s and 494 s for 10, 30, 60 and 100 lines. A single parse of
`heredocs32k.sh` takes 1.28 s. Named relatively after a `cd`, one 32 KiB command
holds about 2,700 references to it, which is about an hour. A self-feeding file of 4,681 lines of
`bash a` (32 KiB) is parsed about 22 million times. Both are extrapolated, not run.

This is exactly review 6 M1's failure. It runs past the client's 30 s budget, whose timeout ALLOWs
the whole PreToolUse chain (ledger 00466 N25), while the daemon burns CPU. Each fixture takes one
`Write`.

The tests (`test_subagent_full_qa_blocker.py`:1489-1528) pin review 6's 64 KiB fixtures, which the
cap now routes to the scan path. None of them references a file under the cap more than once.

The documentation states the property the code does not have:

- HANDLER_REFERENCE.md:1413 says "one event parses at most 32 KiB of file content in all";
- CLAUDE/QA.md says "within one parse budget per command".

**Direction:**

- Charge `parse_budget` on every PARSE, not only on the first read. Past the budget, take the scan
  path, which is already cached per path (`event.named`).
- Alternatively, memoise the verdict per (path, kind, argv, directory).
- Pin it with a RED test: a self-feeding file under the cap and 200 references to a 32 KiB file
  must each be judged within 1 s.

### M2. Reading a script run by its path denies ordinary scripts: a docstring is parsed as shell, and a comment counts as naming pytest

`5d2b62e4` makes a script run by its path, or by `python3 script.py`, be READ. Two ways of reading
it deny scripts that run no QA at all (`probe_463v7_fx2_out.txt`):

- **Python that starts a process has every string literal parsed as a shell command, docstrings
  included.** In `_python_code_runs` (:2605-2608), any literal with a space goes to `_nested`. An
  apostrophe makes it unparsable, and `_full_run_of` (:3317-3321) then denies it as `_UNPARSED`
  whenever the text names a declared program. This 3-line script is DENIED `JUDGED UNSEEN`:

  ```python
  """Run the linter. Don't run pytest here."""
  import subprocess
  subprocess.run(["ruff", "check"], check=True)
  ```

  The same script without the apostrophe is allowed. So is the same docstring without
  `subprocess`.

- **A file past the parse budget is scanned with its comments.** `_full_run_in_code_file`
  (:3394-3400) runs `_named_pattern` on `content.text`, the raw file. A 39 KB build script whose only
  mention of pytest is `# pytest is run by CI, not here` is DENIED. Without the comment it is
  allowed.

**In this repository** (`probe_463v7_qa_scripts_out.txt`, `probe_463v7_exec_why_out.txt`):

- 6 of the 31 `scripts/qa/*.py` scripts are denied when run the way their own docstrings say
  (`python scripts/qa/X.py`):
  - `run_changed_tests.py` (44 KB), the targeted-test runner;
  - `check_repo_hygiene.py` (43 KB);
  - `check_doc_truth.py`, a Detector named in DOC-CONVENTIONS.md:97;
  - `check_sensitive_content.py`;
  - `check_project_handler_tests.py` (8 KB; its docstring says "pytest's flags");
  - `run_corpus_qa.py`.
- Run by their paths, 10 of the 148 tracked executables are denied `JUDGED UNSEEN`, not counting
  the 3 declared programs. 6 of the 10 are these two mechanisms: both skills' `invoke.sh`,
  `install.py`, `check_doc_truth.py`, `check_repo_hygiene.py` and `run_changed_tests.py`. The
  other 4 are `install.sh` and `scripts/install/prerequisites.sh` (the stdin-producer choice), and
  `scripts/test.bash` and an upgrade `verification.sh`, which name a program or an operand at run
  time.

A sub-agent doing exactly what the handler asks, targeted QA, is told it is running the full
suite.

The reference documents only the size half, and only as "names a declared program"
(HANDLER_REFERENCE.md:1427). Neither the docstring half nor the comment half is documented.

**Direction:**

- Scan `_without_comments(text)` for shell. For Python, scan with docstrings and comments dropped.
- Nest a Python string literal as shell only when it is an argv element or its first word names a
  program. An unparsable prose literal is "no command", not `_UNPARSED`.
- Add RED rows for the 3-line script and the commented 39 KB script, and a test that runs every
  `scripts/qa/*.py` by its documented usage and expects ALLOW.

---

## Minor

### m1. `$(cat f)` and a file's path are read in some positions and not in others

These are ALLOWED, and each runs `pytest tests` (the fixture is `probe_463v7_fx/full.sh` or
`full.py`):

- `python3 -c "$(cat full.py)"`. `bash -c "$(cat full.sh)"` is read, but `_resolve_python`
  (:2661-2663) hands the substitution to `_python_code_runs` as literal code, where `_code_of`
  (:2242) would read it.
- `bash <<< "$(cat full.sh)"`, `$(cat full.sh)` and `` `cat full.sh` `` as the command word, and
  `bash -c "x=1; $(cat full.sh)"`. The substitution's OUTPUT is the command, but only its own words
  are judged (`_resolve_opaque`).
- `F=full.sh; cat $F | bash`. The producer's words in `_code_on_stdin` (:1861-1862) are not
  variable-expanded, so the path `$F` is "absent" (`_read_code` :3449-3454). The same variable IS
  expanded in `F=...; bash -c "$(cat $F)"`, which is denied. `cat "$SCRIPT" | bash` and
  `bash "$SCRIPT"` with an unset variable are allowed for the same reason. That is fail-open for
  code the handler cannot see, which contradicts HANDLER_REFERENCE.md:1421.
- `bash -s -- tests < arg1.sh` (the file is `pytest "$1"`). After `-s`, every word is a positional
  argument, but `_resolve_shell` (:2702-2705) reads `tests` as the script, finds a directory and
  runs nothing. `cat f | bash -s -- tests` goes the same way, because `_reads_code_from_stdin`
  (:1634-1635) stops at the first operand.

HANDLER_REFERENCE.md:1478 says "The one run that is not seen is a program whose NAME is built at
run time from pieces". With these, that is no longer true.

**Direction:**

- Route `-c` for Python, a here-string, and a whole-substitution command word through `_code_of`.
- Expand variables in producer words, and treat a path built at run time as unseen, not absent.
- With `-s`, take no script operand.

### m2. The unknown-producer rule has no escape for environment setup

See design choice 4. Each of these is denied with `JUDGED UNSEEN`:

- `eval "$(ssh-agent -s)" && ssh-add -l`
- `eval "$(pyenv init -)"; pytest tests/unit/qa`
- `source <(kubectl completion bash)`

Nothing about them can be moved to another call, since shell state does not persist between Bash
calls. Their only sign of QA is the word `bash` or `eval`.

**Direction:**

- Keep failing closed for producers that can print project code: file readers (`cat` variants,
  `awk`, `grep`, `tac`, `git show`) and interpreters.
- For `eval`/`source` of a program's output where no file operand is involved, allow a short list
  of environment-setup producers (`ssh-agent`, `pyenv|rbenv|nodenv init`, `direnv export`,
  `conda shell.*`, `brew shellenv`, `* completion *`), or say in the reference that these are
  denied.

### m3. The natural "since the merge base" listing is refused

These are denied `JUDGED UNSEEN`:

- `git diff --name-only "$(git merge-base main HEAD)" -- tests | xargs -r pytest`
- `BASE=$(git merge-base main HEAD); git diff --name-only $BASE -- tests | xargs -r pytest`

`_steers_a_listing` (:1690-1699) refuses any word built at run time, because one could be the
empty tree. `git merge-base` prints a commit, never a tree. `git diff --name-only main...HEAD` means
the same and is allowed, but neither the deny nor the reference says so.

**Direction:** accept a substitution whose code is `git merge-base <rev> <rev>`, or name
`main...HEAD` in HANDLER_REFERENCE.md:1432.

### m4. `find -exec pytest` is not followed

`find tests -name 'test_*.py' -exec pytest {} +` runs every test file and is ALLOWED. So are
`find tests/unit ... -exec pytest -q {} +`, `find . -maxdepth 1 -name tests -exec pytest {} \;` and
`find tests -maxdepth 0 -exec pytest {} \;` (`probe_463v7_find_exec_out.txt`). The `| xargs`
spelling of the first is denied, and the reference documents that deny. `find` is judged as the
program `find`, the "launcher not listed" limit (HANDLER_REFERENCE.md:1475). But `find` is common,
and its `-exec … {} +`/`\;` grammar is small.

**Direction:** follow `-exec`/`-execdir`/`-ok` to `+` or `;`, and judge `{}` as the files `find`
selects. That is its start paths when there is no `-name`/`-path` narrowing below them, and unseen
otherwise.

### m5. N2: after a merge of an older `main`, the printed recheck range is stale

This comes from the N2 run (`probe_463v7_n2_attack2.sh`, section A5c).

The setup: `main` moves a tested doc (M1), which is merged into the head. Then `main` moves code
(M2), which is not merged. The m8 verdict says `targeted` for base..M1 and prints:

1. `git merge --no-edit main`, which pulls in M2;
2. `changed … --range base..M1`.

Followed literally, `--advance` then refuses, because base..M2 is `full-gate`. One recheck is
wasted and the steps mislead. Nothing unsafe lands.

**Where:** `_main_merged_since_certified` (`llm_qa.py`:2005-2017) judges the merge-base, but
`_print_verdict` (:2180-2185) says to merge the tip of `main`.

**Direction:** when `main` is not the merged commit, judge base..main, or drop the merge step and
say that `main` has moved again.

---

## Nit

- **n1.** An unknown plugin flag before a path: `pytest --reuse-db tests/unit/qa` is denied, and
  the deny carries no `JUDGED UNSEEN`. The reference documents this (:1464), with the workaround.
  The converse is allowed: `pytest --reuse-db tests tests/unit/qa`, where pytest-django's boolean
  `--reuse-db` leaves `tests` to run. Reading a consumed word that names the suite as full costs
  nothing.

- **n2.** `audit_error_hiding` (`:201-209`) accepts ANY expression-statement yield before a bare
  `return` as reporting the failure. `yield 0`, `yield None`, a bare `yield` and `yield from ()`
  all pass (`probe_463v7_audit_out.txt`), and the last yields nothing at all. The realistic
  swallowing shape is still flagged: a yield in the `try` body with a bare return in the `except`.
  Across the repository, the change removes exactly one finding, `_code_of` (`probe_463v7_audit_repo_{old,new}.json`),
  which does yield a fail-closed marker. So the fix is sound for its purpose, with a loophole for a
  deliberate writer. Requiring the yielded expression to be a non-constant would close most of it.
  Async functions were never checked; that predates 463.

- **n3.** N2:

  - An empty commit after the gate asks for a full run (A1, A4).
  - The m8 verdict prints `git merge --no-edit main` when `main` is already merged, which is a
    no-op.
  - `--advance` after `main` is rewritten moves the base BACKWARD (A9, `advance_batch`
    :2051-2059). The next verdict covers more, so it is not exploitable.

- **n4.** m5 residual: 7 of 16 further spellings of a new directory in a declared reader pass
  (`probe_463v7_m5_out.txt`). The misses are:

  - `glob.glob(os.path.join(REPO_ROOT, 'CLAUDE', 'Architecture', '*.md'))`;
  - a loop over a tuple of directories;
  - `iterdir` and `os.listdir` of the new directory;
  - a helper function that returns the directory;
  - a `parametrize`d directory;
  - `Path('CLAUDE/Architecture')` relative to the rootdir.

  The scanner sees the reader in each case; only the pattern is not resolved. Reporting an
  unresolvable pattern in a declared reader, rather than passing it, would close the class.

- **n5.** `path_exists(unreadable_means=False)`:

  - Every caller fails closed or harmlessly. `--pyargs` denies. `_is_path_like` leaves the run
    looking bare, which is full. `_repository_root` could step up to an outer repository, but only
    for leaf paths that cannot exist.
  - As root, only ENAMETOOLONG reaches the fallback.
  - The cost is log volume: each lookup logs a WARNING. One 32 KiB command of 115 distinct
    over-long operands writes 230 records (about 200 KB) per event (`probe_463v7_pathexists_out.txt`).

- **n6.** The byte budgets key on `st_size`, which `/proc` reports as 0. What I tried is harmless:

  - `/proc/self/pagemap` raises EINVAL and `/proc/kmsg` EACCES, and the daemon turns each into a
    deny;
  - `/proc/self/maps` is read in 0.12 s (`probe_463v7_proc_out.txt`).

  Counting the bytes actually read, not `st_size`, would make the budget true by construction.

## N2 end to end (fresh clone of `700f0d34`)

This section comes from `probe_463v7_{n2,n2b,finish,fences,loop,n2_attack,n2_attack2}_out.txt`.

- **The v6 scripts re-run** give the same results as v6, except where m8 changes them. S10 and L3
  now get the main-moved verdict with the "HEAD holds main merged in … and nothing else" reason.
  After the recheck they print only `--advance`.

- **The fences run as written.** They exit 1, 7, 0, 7, then 5, 6 and 4. The race lands the
  certified sha, not the branch head.

- **`--finish`:** see n3 in the table. Every refused shape keeps both batch refs.

- **New attacks:**

  - An octopus merge of `main` and a side branch gets `head-moved`, and `--advance` refuses it.
  - A `-s ours` merge of `main`'s code change is refused until a full run (A7).
  - `main` rewritten with nothing merged gives `full-gate` (A9).
  - A dirty tree gives `head-moved` exit 7 (A11).
  - A change injected into the merge commit on a path `main` moved is rechecked by the printed
    targeted command, and it lands only after that passes (A12b, as v6 S8d).

  No attack landed an uncertified change or skipped a gate. Every head ran `llm_qa.py all` at
  most once, except A1 and A4 (nit n3).

## QA exclusions and gate dodges

In `git diff 01f9ef51..700f0d34`:

- No `noqa`, `type: ignore`, `nosec`, `pragma`, skip or xfail is added.
- No exclusions file, `pyproject.toml`, `changed_tests_map.yaml` or invariant-pairs change.
- The only config change is the handler's own options: `full_words: [all, tests]` and
  `value_flags: [--range]`.

Eight assertions were removed from `test_subagent_full_qa_blocker.py`. Each is an intended change
of meaning, and each is re-pinned for a pattern with no grammar or by a stronger assertion
(`match.fail_closed`). The three cases are:

- under the grammar, an absent word is a target;
- braces past the cap read as a glob;
- a file too large to parse fails closed.

The `audit_error_hiding` change is a detector change, made with RED tests (n2). It was needed
because the detector misread a handler that yields its failure. It is not a dodge. Across the
repository, the only finding it removes is `_code_of`. I found no code restructured to satisfy a
gate.

## Timing

**Handler alone.**

- Review 6's filebomb: at most 0.03 s (80 feeds of a 64 KiB file).
- Review 5's timing and scaling probes: slowest row 0.19 s (`parallel --x a x1000`).
- The new corpus: slowest row 78 ms.
- The file reader under the cap is not bounded (Major M1).

**Whole chain, in-process** (`probe_463v7_chain_timing_out.txt`, review 6's script at HEAD). Each
cell is main thread / sub-agent.

| Shape                       | 32 KiB − 1    | 32 KiB + 1    | 94 KiB         |
| --------------------------- | ------------- | ------------- | -------------- |
| pytest path operands        | 0.73 / 0.62 s | 0.48 / 0.34 s | 1.72 / 1.65 s  |
| echo words chained          | 1.85 / 1.74 s | 0.89 / 1.19 s | 4.28 / 2.72 s  |
| brace operands              | 0.64 / 1.05 s | 0.61 / 0.40 s | 1.98 / 1.28 s  |
| double-quoted substitutions | 0.72 / 1.02 s | 0.70 / 0.77 s | 2.02 / 1.96 s  |
| subshell parens             | 0.77 / 0.90 s | 0.70 / 0.74 s | 2.14 / 2.38 s  |
| pytest bare then targeted   | 0.64 / 0.66 s | 0.68 / 0.38 s | 1.95 / 1.39 s  |
| quoted heredoc openers      | 15.5 / 16.1 s | 13.2 / 13.2 s | 101.3 / 95.8 s |

This run shared the host with the `self100` measurement, which inflates the slow row. An earlier
run at the same HEAD, on a quieter host (`probe_463v7_rerun_463v6_chain_timing.txt`), gave the
heredoc row 7.3 / 7.3 s, 6.5 / 7.4 s and 52.2 / 55.6 s. Every other row is at most 4.3 s in both
runs.

The heredoc row is the chain's other handlers, as it is on `main` (review 6 n6, ledger 00466). The
sub-agent chain adds this handler, whose share on these command shapes is within the noise between
runs. File-reading shapes are the exception, and that is M1.

---

## Verdict

**NOT READY.** Two majors, both local to `subagent_full_qa_blocker.py` and its reference page:

- **M1** is review 6 M1 again. The fix bounded the bytes READ, not the bytes PARSED. A 58-byte
  command still takes 76 s, and a 13 KB one 151 s, past the client's 30 s budget, whose timeout
  fails the whole chain open. The fix is small: charge the parse budget on every parse, or memoise
  the verdict. It needs a RED test that references a file under the cap many times.
- **M2** is a new false-deny class from reading scripts run by path. A docstring with an apostrophe
  in a Python script that uses `subprocess`, or a comment in a large shell script, makes a script
  with no QA in it a denied "full run". It denies 6 of the repository's own 31 QA scripts run as
  documented, including the targeted runner `run_changed_tests.py`.

Every other review 6 item is fixed for the shape it reported, and all 55 of its reproducers give
the verdict review 6 asked for. M2 (the listings), the `full_words` split and the N2 machinery,
with the tightened `--finish` and m8, held against everything I tried. Of the design choices, 1, 2,
3 and 5 are sound. Choice 4 is right for project files but should not reach environment-setup
`eval`s (m2). m1 and m4 are each a few lines and worth doing with the majors. m2, m3, m5 and the
nits can go to the ledger.
