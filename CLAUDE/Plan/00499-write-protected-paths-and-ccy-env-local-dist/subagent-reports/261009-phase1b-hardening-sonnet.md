# Plan 00499 Phase 1b: hardening report (sonnet)

## What was built

- `src/claude_code_hooks_daemon/utils/simple_commands.py` (new): reads a command line as simple commands (verb past
  assignments, absolute command path and wrappers; quote-removed operands), the code a shell is handed
  (`bash -c`, `eval`, `flock -c`, `su -c`), brace spellings and `for`-loop unrolling. It reuses the existing
  `shell_segmentation`, `shell_expansion` (spelling caps) and `command_evasion` helpers.
- `handlers/pre_tool_use/write_protected_paths.py`: the precise scan stays. On top of it, every simple command is
  judged by its verb. A command naming a listed path (the file itself, a wildcard that could reach it, an
  `--opt=VALUE`, a name behind an unresolved expansion) that is on neither `READ_ONLY_VERBS` nor the scan-judged verbs
  is denied. `git` is judged by subcommand. Wrapper tails and absolute-path verbs are re-scanned. `bash -c`, `sh -c`,
  `eval`, `flock -c` and `su -c` bodies are recursed into (`MAX_SHELL_DEPTH` 3; past it the body is judged by name).
- `cd` with a redirect is followed (`_CD_REDIRECT_RE`). `for` bodies are written out per word (32 words, then `*`).

## Decisions worth a reviewer's eye

- Input redirects (`< file`) are not a naming of the file; output redirects are the shared scan's job, whatever
  command carries them.
- An unknown command naming only a directory ABOVE the file is allowed (`ruff check .claude`, `pytest .`); the
  ancestor rule still applies to the scan-judged verbs and to a scan-judged verb behind an unknown command.
- Brace variants: one joined variant plus one per spelling index, so a destination in last position
  (`cp x f.{local,dist}`) is judged. Past the spelling cap the command is judged by `_text_naming`.
- A quoted-delimiter heredoc body fed to a data sink is not read as commands; an UNQUOTED one is, so prose naming the
  path in `cat > n.md <<EOF` can be denied. Guidance says to quote the delimiter.

## Gaps not closed (named in the handler guidance)

- Code inside an interpreter (`python -c "open(...)"`, `perl -e`) and a heredoc fed to one.
- A tool that removes a directory above the file and names only the directory (`find .claude -delete`).
- A group after an unreadable substitution (`rm $(date) x.{a,b}`) is judged by name only, so it is denied only when
  the command text carries the literal file name.
- Cross products of several brace groups for a destination in last position (only aligned spellings are tried).
- Nested `for` loops: the inner loop is kept as written.

## Review round 1 (fixes)

Review: `261009-00499-phase1b-review-r1-opus.md`. Fixed: B1 (assignments carried across a `cd` are a bounded map;
`F=a` repeated 500 times before a `cd` took 22.5 s and takes 0.17 s, 10 KB takes 0.77 s), B2 (nested past the bound: any word
naming the file, its directory or a wildcard/brace group that could reach it is denied, 64 bodies at most), B3 careless
parts (scan-judged verbs are always re-read from their own text; `export/declare/local/readonly/typeset F=P` read as
plain assignments), S2 (`xargs` read as a wrapper), S3 (`read` loops), S5 (`find` with an action), S6 (the file's own
directory as a destination; `cp -r`/`mv -T`), S9 (`--output`, `-o`, `-O`, `--log-file`), S10 (wider read-only
allowlist, `--env-file`/`-f` input options, wording), S11 (the perf sweep configures this handler with `paths`).
Out of scope, listed in the guidance: B4, S1, S4, S7, S8 (hostile respellings). Tests were written before the code, but
I did not capture a red run for this round.

## Review round 2 (fixes)

Review: `261009-00499-phase1b-review-r2-opus.md`. Tests (`TestReviewRound2`) were run BEFORE the code: 22 failed, 19
passed (red: the `test_s1_xargs_input_given_on_the_command_itself_is_judged` cases with `<<<`, `<`, `-a`,
`--arg-file`; `test_s2_a_loop_that_reads_the_file_and_writes_elsewhere_is_allowed` x3;
`test_s3_copying_the_directory_out_is_allowed` x4 and the `--target-directory=` denial;
`test_s4_a_find_whose_name_filter_cannot_match_feeds_xargs_freely` x3; `test_nit_these_readers_are_allowed` x5).
After the code: all 41 pass (585 in the two handler test files). S1 judges xargs's own input, S2 counts a read loop as
a writer only when the variable is a file operand of a non-reader or an output redirect target, S3 judges only the
copy destination (`-t`, `--target-directory`, else the last operand), S4 skips a `find` whose `-name` filter cannot
match; `tree`, `ruff check` / `ruff format --check` and `docker build` are read-only; the `_deep_violation` docstring
is corrected.

## Tests

- `tests/unit/handlers/pre_tool_use/test_write_protected_paths.py`: +about 230 cases (wrappers, read-only allowlist,
  braces, shell strings and absolute paths, cd with redirect, loops, linear-time check, guidance).
- `tests/unit/utils/test_simple_commands.py`: 66 cases for the new module.
- Run: the two named test files, `test_blocking_handler_evasion.py`, `tests/unit/core/`, `test_simple_commands.py`
  (3394 passed); `test_safety_handlers_hostile_input_performance.py` (43 passed); `test_claude_md_guidance_coverage.py`
  (354 passed). ruff, black and mypy clean on the changed files. `llm_qa.py` was not run.
- Tests were run with `-o pythonpath=src` because the shared venv's editable install points at the main checkout.
