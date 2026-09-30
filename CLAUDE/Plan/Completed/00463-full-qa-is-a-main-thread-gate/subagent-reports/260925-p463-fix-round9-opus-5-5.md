# Plan 00463 — review 8 fix round 9 (Opus 5.5)

This round started at `ef7a04bc6` on `worktree-plan-463-full-qa-gate`. The binding
principle for this round: anything the handler cannot fully judge within budget is
denied, and it never narrows or blanks what it reads. Every fix was proven RED
before it was committed, either as a new failing test or by mutating a
`git archive` copy.

No full run was made. Each commit was preceded by targeted tests plus ruff, mypy,
pyright and black on the files it touched, and by a `bin/hooks-daemon restart`
reporting RUNNING.

## One line per review 8 finding

| Finding                                  | State                   | Commit(s)                             | What was done                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| ---------------------------------------- | ----------------------- | ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| B1 (parse budget)                        | FIXED, verified         | `5a86b689a`, `2a183e1a1`              | The call has one `_ParseMeter` in a ContextVar, counted in bytes (96 KiB). It is charged by every parse: the command, each nested `bash -c`, each file and each Python literal. Exhaustion denies as `too-much-code-to-judge`. Tests count parses; no test is timed. The daemon figures are below.                                                                                                                                                                               |
| M1 (Python narrowed to call parentheses) | FIXED                   | `9a1988734`                           | The narrowing is reverted. When code can start a process, every string literal counts, found through the AST: variables, dicts, return values, concatenation, f-strings, `.format`, `" ".join`, and argv lists. The false denies are fixed another way: a literal whose first word Python computes is not a command, and a file run by its path with no execute bit runs nothing. The memo key is argv-aware.                                                                    |
| M2 (a large file was blanked)            | FIXED                   | `f13da02fc`                           | A file too large to parse is scanned raw for a declared name, with comments and strings kept. Stripping is gone from the scan path. A shell file is capped at 32 KiB and Python at the meter. A 32 KiB filler before a runner no longer hides it: the filler draws on the meter, and the runner is still read.                                                                                                                                                                   |
| M3 (allowlist trusted a program name)    | FIXED earlier, VERIFIED | `4b62126e8`                           | All 19 shapes in review 8 section M3 are corpus rows. All 19 are denied, in-process and through the daemon. `completion` counts only as the first word with one shell name after it. A producer named by a path is never trusted.                                                                                                                                                                                                                                                |
| M4a (guidance test)                      | FIXED                   | `8f40d12b1`, `a33b68a84`              | A candidate command ends at a prose connective. `_names_a_full_run` counts only declared pattern ids, so the guard's caution about unseen code in prose does not read as an instruction.                                                                                                                                                                                                                                                                                         |
| M4b (flaky wall-clock test)              | FIXED                   | `2a183e1a1`, `f13da02fc`, `c6ff675c4` | Every wall-clock assert in the blocker tests now counts work instead: parses (`_ParseLedger`), bytes read and stripped (`_ReadLedger`), and brace steps. Three mutations of an archive copy were each RED: the meter never refusing, braces expanded in full, and the scan stripping comments (`untracked/scratch/p463r9_mutate_out.txt`).                                                                                                                                       |
| M4c (median slowdown)                    | FIXED                   | `f13da02fc`                           | Cause: a comment strip ran per file on the scan path, before the cheap substring test. Stripping now happens only for an unset-variable haystack, once per event. Fan-out median: 0.48 s, against 0.876 s at review 8 and 0.27 s at review 7.                                                                                                                                                                                                                                    |
| M4d (pyright FSTRING_MIDDLE)             | FIXED earlier           | `d57036d29`                           | The tokenizer path this came from was removed in `f13da02fc`.                                                                                                                                                                                                                                                                                                                                                                                                                    |
| m1 (substitution residue)                | FIXED                   | `a33b68a84`                           | `$(cat f)` or backticks as the command word read the file as words and as shell code. `which`, `command -v` and `type -P` resolve to the program they print. Any other substitution is opaque: it is judged by the programs it names, and denied as unread code when it names none but reads a file. `bash -c "x=1; $(cat f)"` is denied. `cat "$SCRIPT" \| bash` and `bash "$SCRIPT"` with the variable unset are denied as unseen. `~`, `$HOME` and `$PWD` paths are resolved. |
| m2 (merge-base prefix)                   | FIXED earlier           | `eea933294`                           | The substitution must be exactly one `git merge-base <rev>...` command with no flag. The converse false deny (unquoted) is fixed in `2ef9cfd69`: an unquoted `$(git merge-base A B)` is judged with its substitution put back.                                                                                                                                                                                                                                                   |
| m3 (find `{}` inside a word; narrowing)  | FIXED earlier           | `ef7a04bc6`                           | Pinned by the corpus test (24 find rows).                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| m4 (dropped assertion; global limiter)   | FIXED                   | `d2278898b`, `71239ac43`              | The assertion is restored. The burst limiter now keeps one window per calling site (module and function), under a lock. One handler's burst no longer silences another module's warnings, and the aggregate line names the site.                                                                                                                                                                                                                                                 |
| m5 (release-note numbering)              | FIXED earlier           | `f20de39a3`                           | Renumbered 33-36. The final number at merge is still the coordinator's call.                                                                                                                                                                                                                                                                                                                                                                                                     |
| n1 (strip cost on scan)                  | FIXED                   | `f13da02fc`                           | The scan is raw and linear, cached per path. The only strip left happens once per event, on text the meter has already charged. `_ReadLedger` pins it.                                                                                                                                                                                                                                                                                                                           |
| n2 (memo key)                            | FIXED                   | `1f1d1ab29`                           | The chain key is (path, kind, argv when read, directory, `PYTEST_ADDOPTS`). The verdict key adds the file depth. A file past depth 8 is denied as `code-nested-too-deep`. `PYTEST_ADDOPTS` is read once per file.                                                                                                                                                                                                                                                                |
| n3 (docs vs allowlist)                   | FIXED                   | `42be098d6`, `9c38850ee`              | HANDLER_REFERENCE and release notes 33-36 now describe the current code: the meter and its deny, the raw scan, the depth limit, every Python literal counting, the execute bit, command-word substitutions, the exact environment-setup list, the new launchers, find, merge-base, and paths the code builds.                                                                                                                                                                    |
| n4 (`yield from iter(())`)               | FIXED                   | `b1926471f`                           | A builtin that keeps its argument's items (`iter`, `tuple`, `list`, `set`, `frozenset`, `dict`, `reversed`, `sorted`) around an empty literal is empty, checked recursively. A non-empty constant string does name the failure.                                                                                                                                                                                                                                                  |
| Corpus: 114 false-negative rows          | ALL CORRECT             | `2ef9cfd69`, `5067ff8f6`              | Five rows were still wrong this round. Four were fixed by new launchers: `ssh-agent CMD`, `pyenv exec`, `rbenv exec`, `direnv exec DIR`, and `conda`/`mamba`/`micromamba run`. A launcher with a subcommand runs nothing for any other subcommand. A stdin consumer behind a launcher still reads code. The fifth was the unquoted double merge-base. The corpus is now `test_subagent_full_qa_blocker_corpus.py`, and against `a33b68a84` it fails exactly those 5 rows.        |
| Corpus: 203 everyday commands            | ALL ALLOWED             | `ef7a04bc6`, `5067ff8f6`              | The one false deny review 8 named was `find tests/unit/qa -name 'test_llm_qa*.py' -exec pytest -q {} +`, fixed in `ef7a04bc6`. All 203 are allowed in-process, and through the worktree daemon at HEAD (`untracked/scratch/p463r9_fp_daemon.txt`). Only one command drew a deny, and it came from another handler (`ruff format --check …`).                                                                                                                                     |

## B1 through the daemon (HEAD, `untracked/scratch/p463r9_b1_out2.txt`)

The worst case denies in 3.90 s, well within the 30 s timeout. Nothing timed out.

| Case                                                               | Daemon        | Verdict |
| ------------------------------------------------------------------ | ------------- | ------- |
| 200 references to a 32 KiB script that reads `"$1"`, each argv new | 1.16 s        | DENY    |
| same, with a 32 KiB heredoc-opener script                          | 3.90 s        | DENY    |
| `cd30` / `cd60`                                                    | 0.43 / 0.64 s | DENY    |
| 200 references to a 32 KiB script that never reads its argv        | 0.90 s        | ALLOW   |
| the same, then `pytest tests`                                      | 1.22 s        | DENY    |

The last-but-one row is allowed by design. It is not a gap. Since M1's argv-aware
key, a file whose judgement never reads its argv is parsed once, so the whole file
is judged within budget. The review 8 probe's argv-blind files therefore get a
full judgement and are allowed. The meter still has to deny when every reference
needs a new parse, and the argv-reading variants show that it does.

## Open: not fixed this round (the lead has to decide)

1. **A script whose path is built at run time is still treated as absent.** Examples:
   `bash "$(dirname "${BASH_SOURCE[0]}")/z.sh"`, a `SCRIPT_DIR` variable, or
   `${BASH_SOURCE[0]%/*}`. Such a script is not read, so a script that runs a
   full-suite script this way is allowed. The binding principle would deny it. I
   tried both directions and measured them:

   - **Fail closed, with no resolution.** 27 of this repo's own scripts, and 30
     of the 203 everyday commands, are denied. Among them are
     `bin/hooks-daemon status`, `./scripts/qa/run_lint.sh` and
     `python3 scripts/qa/check_doc_truth.py`.
   - **Resolve the common idioms.** This covered `$(dirname "${BASH_SOURCE[0]}")`,
     `$(cd DIR && pwd)`, `realpath` and `readlink -f`. It made the deeper
     scripts readable, but those scripts then reached constructs that cannot be
     evaluated without a shell-expansion evaluator: `${VAR%/*/*}`, a variable
     reassigned under `case`, and `$PWD/` after an unresolved `cd`. Four
     everyday commands were still denied (`run_semgrep_check.sh`,
     `run_canonical_callers_check.sh`, `install_version.sh`,
     `dummy-client-repo.sh`).

   I reverted it and committed nothing. The attempt, with its tests, is saved at
   `untracked/scratch/p463r9_script_dir_attempt.patch`. Closing this properly
   needs a bounded evaluator for shell parameter expansion over the file's own
   assignments. That is a feature-sized change, and it should be its own plan
   item.

2. **A shell file keeps the 32 KiB parse cap** because `strip_quoted_heredoc_bodies`
   in the shared utilities is superlinear in heredoc openers (ledger 00466). The
   worst B1 row (3.90 s) is that function. The cap means a larger shell file is
   raw-scanned rather than parsed, which is fail-closed: it can only false-deny
   when the file mentions a declared program's name.

3. **`run_changed_tests.py` is declared rather than read** (`full_words: []`, in
   the dogfood YAML), so the handler does not look inside it. This is intentional,
   but it relies on that script never running the whole suite.

4. **n4's remaining shape:** `yield from some_helper()` is still presumed to name
   the failure. What an arbitrary call yields cannot be decided statically. Only
   the builtin constructors of an empty iterable are rejected.

## Verification at HEAD

- Targeted tests: 1,639 passed. These cover the blocker, the corpus, the
  setup-worktree guidance, audit_error_hiding, llm_qa_main_moved, path_predicates
  and shell_segmentation. `tests/unit/utils` separately: 2,015 passed. The doc
  checks (handler reference, release-note holding area, CLAUDE.md guidance
  coverage, release slate): 377 passed.
- ruff, black, mypy and pyright are clean on every file touched.
- Daemon: restarted and reported RUNNING before each commit that touched `src`.
