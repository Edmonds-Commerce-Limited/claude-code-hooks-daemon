NOT READY

# Plan 00466: adversarial review 8 (final) of `worktree-n466-guard-defects`

**Reviewer**: Opus 5.5. **Target**: HEAD `ff071be8d` (range `973c21ec0^..ff071be8d`).
**Blocking findings**: 3 MAJOR (MAJOR-A, MAJOR-B, MAJOR-C below). There are no BLOCKERs.
No tracked file was edited and nothing was committed. No gate was queued. No real
protected file was opened. Every probe judges command text only and carries
`synthetic_source: review-gd8b`.

Probe scripts and raw outputs are in `/workspace/untracked/scratch/rv8/`. The re-runs
of the earlier probes are `/workspace/untracked/scratch/rv8_probe_*.txt`. All probes
were run as `PYTHONPATH=<worktree>/src <worktree venv python> <probe>`.

## 1. Review-7 items against the current code

| Item                                            | Status          | Evidence                                                                                                                                                                                                                                                                                                                             |
| ----------------------------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| MAJOR-1 over-budget fail-open                   | CLOSED          | `probe_gd7_shell`: 62 cases, 0 mismatches. `probe_gd8_failclosed`: the 501-brace-word cap denies, and an expired deadline denies on both the Bash and Write routes (0 mismatches). The flat word cap has been replaced by the deadline. At 1 MB the vocabulary Bash and Write inputs take about 0.5-0.8 s and are allowed correctly. |
| MAJOR-2 `$()` and backtick bodies not re-parsed | **PARTLY OPEN** | `$()` nesting at depths 1-3, quoted `$()`, and mixed `$()`/backtick nesting all deny. **Escaped nested backticks still fail open**: see MAJOR-B.                                                                                                                                                                                     |
| MAJOR-3 wrapper, here-string and `-c` walk gaps | CLOSED          | gd7 rows are 0 mismatches. My own 16-row `probe_rv8_shellopts` also denies every row (`bash -O/+O/-o/--init-file`, `zsh -o`, `-c --`, `su -s X -c`, `sudo -g/-C`, `stdbuf`, `setsid`, `ionice -c`, `chroot`, `unshare`, `busybox sh`). On `main` all 16 fail open.                                                                   |
| MAJOR-4 `file:` URL                             | CLOSED          | gd7 rows. `re.IGNORECASE` is added, and the decoded-word pass reassembles quote-split URLs.                                                                                                                                                                                                                                          |
| MAJOR-5 one-liner exact-match                   | **PARTLY OPEN** | Versioned and absolute interpreters, clustered flags, `-E`, `-p` and `--eval` now deny (gd7). **An interpreter option that takes a separate value still stops the walk**: see MAJOR-C.                                                                                                                                               |
| MINOR-1 `getoutput` and f-string                | CLOSED          | gd7 rows.                                                                                                                                                                                                                                                                                                                            |
| MINOR-2 Ruby bare `system 'x'`                  | CLOSED          | gd7 last row.                                                                                                                                                                                                                                                                                                                        |
| NIT-1 stale comment                             | CLOSED          | The "fails CLOSED (raises)" wording is gone. `shell_expansion.py:538-542` now describes the current behaviour.                                                                                                                                                                                                                       |
| Read-only: regex-fallback parity                | MOSTLY CLOSED   | With unparseable content, the fallback now denies from-imports, aliases and a spaced `shell = True`. Still open: an absolute-path argv interpreter in the fallback (ledger L4).                                                                                                                                                      |
| Read-only: Go/Rust/Java basename                | MOSTLY CLOSED   | `/bin/sh`, `/bin/bash`, `zsh` and Java `Runtime.exec` arrays deny. Still open: an `env bash` argv (ledger L4).                                                                                                                                                                                                                       |

### "Not done" items from review 7

1. **FP corpus (2a)**: CLOSED. `probe_gd5_fp` gives 55 cases and 0 FP. `probe_gd6_fp` gives 125 cases and 0 FP. The new `test_review7_false_positive_corpus.py` has 171 commands, all allowed. That is more than 200 commands across the three, but the in-repo corpus alone is 171 and it asserts only `>= 150` (ledger L8).
2. **Timing (2b)**: CLOSED. `vocab_bash`, `vocab_write` and `mention_tail` cost 0.17-0.28 s at 256 KB and 0.5-0.85 s at 1 MB, which is linear. At 2 MB and 3 MB the cost is 1.0 s and 1.35 s, still allowed. For deep nesting, `(` x1000 and `<(` x1000 finish in about 2 ms. `$()`/`eval` at depth 5 or more and `bash -c` at depth 5 or more fail CLOSED as `R-SECRET-EVALUATION-ERROR` (the depth cap), which is the correct direction.
3. **Fail-closed mutants (2c)**: CLOSED. `probe_gd8_failclosed` gives 10/10. The cases are: an expired deadline on Bash and on Write; the decode raising RuntimeError or TimeoutError; the shared decode raising; the grep exemption raising; the brace stream raising; and the brace cap. All of these deny, and both controls allow.
4. **gd5 re-run (2d)**: CLOSED. content, content2, ctxcmp, edge, reads, tools_res and fp show 0 mismatches. `exotic` shows the same 3 baseline mismatches as the earlier run (ledger L6). gd6_shell is 80/0. gd6_shell2 is 80 cases with 4 mismatches, down from 10, and all 4 are the class-(d) residuals: 2 variable indirection, alias, and write-then-run.
5. **QA-integrity diff (2e)**: CLOSED. There are 37 removed test lines. The absolute `< 1.0 s` budgets were replaced by a 100 KB vs 1 MB cost-RATIO check (`_MAX_COST_RATIO = 25`), which the rules allow. The `max_words=10` truncation test now expects a raise, which is the MAJOR-1 fix. The one expected-word list gained a duplicated `hello world` from the extra recursion, and the docstring justifies it. No deny-to-allow expectation flips, no skips or xfails, and no root conditions. `deadline=monotonic()-1` is deterministic.
6. **Targeted pytest (item 4)**: 854 passed in 5.51 s. This covers `test_secret_file_guard.py`, `test_secret_file_matching.py`, `test_shell_expansion.py` and `test_review7_false_positive_corpus.py`. Output: `rv8/pytest.txt`.
7. **Non-Python content routes**: done. `probe_gd6_files` gives 56 cases with 26 fail-opens (review 6 had 43). The classes are in ledger L3.

## 2. Blocking findings

### MAJOR-A: the new grep exemption treats files that grep READS as search patterns (regression against main)

`src/claude_code_hooks_daemon/utils/secret_file_matching.py:2332` puts `-f` and `--file` in `_GREP_PATTERN_VALUE_FLAGS`. It then exempts their values (`:2386-2395`). Every other word starting with `-` is skipped without being inspected (`:2397`). But `grep -f FILE` OPENS and reads FILE. The same applies to `-fFILE`, `--file=FILE` and `--exclude-from=FILE`.

`probe_rv8_grep` gives 23 cases with 11 mismatches. These rows are now ALLOWED:

- `grep -f /root/.ssh/<key> docs/a.md`. **`main` denies this** (`rv8/grep_main.txt`).
- `grep --file=<key> ...`
- `grep -f<key> ...` (attached value)
- `grep --exclude-from=<key> -r x docs`
- `grep -rhf <key> /root/.ssh`, `grep -r -h -f <key> /root/.ssh` and `grep -h -f <key> -r /root`. Each key line matches itself, so these print the whole key.
- `egrep -rh -e <key> -e '' /root/.ssh` and `grep --include=<key> -rh '' /root/.ssh`.

A caveat on severity: the recursive rows are no worse than the documented residual (`docs/guides/HANDLER_REFERENCE.md:1731-1733`: Bash `grep -r` over an ancestor). `grep -r '' /root/.ssh` is allowed on main too. The non-recursive `-f KEY file` row, however, is a read of a protected file that main denied. It was newly opened by 65121a9be, which is a security exemption, so it blocks.

**Fix direction**: take `-f`/`--file`/`--exclude-from` (and any other file-valued flag) OUT of the pattern set and judge their values as file targets. Also make the exemption refuse (return False) when any flag word carries an attached value that is itself a protected mention (`-fX`, `--x=X`). Add RED tests for the rows above.

### MAJOR-B: escaped nested backticks are never re-parsed (review-7 MAJOR-2 is still open for this shape)

`src/claude_code_hooks_daemon/utils/shell_expansion.py:820-826` and `:847-853` use `text.find("`", i + 1)```  to close a backtick substitution. That call finds the ESCAPED inner `` \ ``` ` first, so the outer body is cut short. The inner body is also never un-escaped (` \` `becomes` ``` ``, ```\\`becomes`\`, `\$` becomes `$`) before the re-parse.

I checked the shape with real bash and a harmless `echo` payload (`rv8/bt_cmd_2.txt` and `bt_cmd_3.txt` both print `MARK-id_rsa`). Bash runs the innermost `bash -c` at depths 2 and 3.

These rows are ALLOWED:

- ```` echo `echo \`bash -c 'cat ~/.ssh/id_r""sa'\```  ````
- ```` x=`echo \`eval 'cat ~/.ssh/id_r""sa'\```  ````
- the depth-3, 4, 5 and 8 variants (`nested_extra_shapes.pyprobe bt N`)

The unescaped forms at depth 1 deny, as do `$()` inside backticks and backticks inside `$()`.

**Fix direction**: find the closing backtick by skipping backslash-escaped characters, then un-escape the body with bash's backtick rules before appending it to `substitutions`.

### MAJOR-C: interpreter one-liner option walk stops at a value-taking option (review-7 MAJOR-5 is still open for this shape)

In `src/claude_code_hooks_daemon/handlers/pre_tool_use/secret_file_guard.py:935-951`, `_classify_one_liner_option_word` returns `"stop"` for the first word that does not start with `-`. The VALUE of a preceding option is such a word, so the walk ends before the code flag.

`probe_rv8_oneliner` gives 17 cases with 9 fail-opens:

- `python3 -W ignore -c ...`, `python3 -X dev -c ...` and `python3 --check-hash-based-pycs never -c ...`
- `ruby -r json -e ...` and `ruby -I lib -e ...`
- `perl -I lib -e ...`
- `node --require ./x.js -e ...` and `node -r ./x.js -e ...`
- `php -d display_errors=1 -r ...`

The shell `-c` route handles the same shape correctly (MAJOR-3 above). Wrapper, assignment-prefix and pipeline forms deny.

**Fix direction**: give each family a table of value-taking short and long options (like `_WRAPPER_SHORT_VALUE_FLAGS` in shell_expansion) and skip their value. A safer alternative that fails closed: when an unrecognised word follows an option, keep walking and treat every later code-flag occurrence as a code word.

## 3. New-code checks (item 2)

- **Fail-open on None, empty, exception or timeout**: exceptions and timeouts from the decode, the shared decode, the brace stream and the grep exemption all deny (item 2c above). `bash_route_word_stream` returns `None` only to request a second decode, never to mean "no mention". Its callers handle `None` correctly.
- **Per-request state on singletons**: none found. The new module-level names are `Final` constant tables (`_ONE_LINER_FAMILIES`, `_WRAPPER_*_VALUE_FLAGS`, `_WRAPPER_POSITIONAL_COUNT`, `_GREP_*`). `realpath_cache` is a local dict inside each call.
- **Wall-clock timing asserts**: none. The only timing test uses a scaling ratio. Its name is stale (ledger L9).

## 4. QA on touched files

- ruff: clean.
- mypy on `src/` (the gate scope, `gate-scope.bash:qa_type_paths`): clean (3 files).
- pyright on `src/`: 0 errors.
- black `--check`: **would reformat all 6 touched .py files**. The diffs are real quote and line-length rewrites (`rv8/black_diff.txt`). The gate's `run_format_check.sh` auto-fixes these, so the gate will not fail on them. Ledger L7.
- mypy and pyright on the test files report `os.ScandirIterator` (`test_shell_expansion.py:245,268`) and `guard_module.sfm` not being explicitly exported (`test_secret_file_guard.py:784-836`). These come from earlier branch commits (2743a86b4, d0de526d1). Tests are outside the mypy gate scope. Ledger L7.

## Ledger candidates (non-blocking, with repro)

- **L1: exemptions run without the deadline.** `is_grep_pattern_only_mention`, `is_exempt_invocation` and `is_encrypted_target_invocation` call `iter_protected_mentions(command, patterns)` with no `deadline`, although `_evaluate` has one in scope (`secret_file_guard.py:1227`). `probe_rv8_grep_timing`: `grep <name> ` followed by distinct file words takes 1.13 s at 256 KB and 3.73 s at 1 MB, which is linear but unbounded. At about 15 MB it would reach the 60 s hook timeout (`.claude/settings.json`). Pass the deadline through.

- **L2: documented residual.** A Bash recursive grep over a protected directory (`grep -r '' /root/.ssh`) is allowed on main and on the branch (`HANDLER_REFERENCE.md:1731`). The rules say residuals are not terminal.

- **L3: content-route (Write/Edit) gaps.** `probe_gd6_files` has 26 fail-opens:

  - Python: a variable-held command; a literal past the 500-character span; `.pyw`; an extensionless python-shebang file.
  - Ruby: `spawn`.
  - PHP: `passthru`, `popen`.
  - Perl: bare `exec`, `open -|`, 2-arg pipe `open`, `.pm`.
  - Node: a template-literal `exec`; `spawn('sh',['-c'])`; `execFile('bash',['-c'])`; `.cjs`, `.tsx`, `.mts`; `zx` `$`; `Bun.$`.
  - Kotlin, Swift, Dockerfile `RUN`, justfile, toml tasks, `package.json` scripts, PowerShell.

  Review 6 rated this class minor-2 (Task 4.3 scope).

- **L4: parity gaps.** The Python regex fallback misses an argv `['/bin/bash','-c',...]` (the AST path catches it). Both Python AST and Go miss an argv `env bash -c` (`probe_rv8_content`, `rv8/content2.txt`).

- **L5: gd6_shell2 class-(d) residuals.** 4 remain: `x=...; bash -c "$x"`, `x=...; eval "$x"`, alias, and write-then-`sh`.

- **L6: gd5_exotic baseline.** 3 mismatches, unchanged from the prior run: a trailing `#c` after the key name, backslash-octal in an unquoted word, and a prose FP.

- **L7: QA hygiene.** Black-unformatted committed code in the 6 touched files, plus the test-file mypy/pyright errors in section 4.

- **L8: FP corpus size.** The in-repo corpus holds 171 commands and asserts `>= 150`, while review 7 asked for 200 or more.

- **L9: stale test name.** `test_one_megabyte_bash_command_completes_well_under_a_second` no longer asserts anything about time. Rename it.

## Reproduce

Set `W=/workspace/untracked/worktrees/worktree-n466-guard-defects` and `PY=$W/untracked/venv-*/bin/python`. Then run:

```
cd /workspace/untracked/scratch/rv8
PYTHONPATH=$W/src $PY probe_rv8_grep.pyprobe            # MAJOR-A
PYTHONPATH=/workspace/src $PY probe_rv8_grep_main.pyprobe  # main baseline
PYTHONPATH=$W/src $PY nested_extra_shapes.pyprobe bt 2   # MAJOR-B
PYTHONPATH=$W/src $PY probe_rv8_oneliner.pyprobe         # MAJOR-C
```
