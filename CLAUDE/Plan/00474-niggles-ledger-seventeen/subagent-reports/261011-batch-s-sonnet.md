# Batch S: N407 residual false negatives (sonnet)

Scope: `sudo_pip` and `pip_break_system` misses listed under N407 "Residual gaps".

## Changes

- `src/claude_code_hooks_daemon/handlers/pre_tool_use/sudo_pip.py`: the pattern is now local (no longer built on the
  shared `SUDO_INVOCATION`, which `curl_pipe_shell` still uses). It accepts `sudo`/`doas`, sudo options that take a value
  (`-u root`, `-iu root`), an `env [VAR=x]` or `sh/bash/zsh/dash -c '` wrapper, bare `VAR=x`, and versioned `pip3.11` /
  `python3.11 -m pip`.
- `src/claude_code_hooks_daemon/handlers/pre_tool_use/pip_break_system.py`: flag pattern asserts `install` and the flag
  as lookaheads after the binary (covers the flag before the subcommand and versioned binaries); a second pattern
  covers `PIP_BREAK_SYSTEM_PACKAGES=<truthy>` (inline, `env`, `export`, inside `bash -c`). Falsy or empty values allow.
- Matching is still per `command_position_code_segments`.
- Tests: new `tests/unit/handlers/pre_tool_use/test_pip_guards_residual_forms.py` (red first: 52 failed / 46 passed;
  then green). Each deny shape is also checked inside `if...then`, and each is checked as a mention (echo, commit
  message, grep, comment, quoted heredoc) that must allow.
- Corpus: 9 `n407-*` mention rows added to `tests/fixtures/ordinary_command_corpus.yaml`.
- Acceptance tests unchanged (already `bash -n -c '...'` with a nonexistent package).
- Ledger: N407 residuals marked cleared; obfuscation deliberately skipped.

## Round 2 (review FIX FIRST)

- B1: the env var is judged by `_leading_assignment` / `_env_var_governs_pip_install`: a real assignment only (prefix,
  after `env`, after `export`/`declare -x`). `git grep`, `find -name`, `ls`, `docker run -e` allow; tests and corpus rows
  added.
- B2: the value is unquoted before the falsy test; `'0'`, `"false"`, `''` allow.
- N1: a bare `export` no longer denies. It denies only when a truthy assignment governs a pip install (same-command
  prefix, `env`, or an earlier `export` in the line followed by a pip install). `export ...=1; echo pip install x` and
  `; ls` allow; `export ...=1 && pip install x` and `; pip3 install x` deny. A later `=0` export or prefix overrides.
- N2: cleared `sudo --user root`, `sudo -p 'pw: '`, `sudo pip -q install`. Not cleared: `sudo bash -c 'echo hi; pip install x'` (the splitter cuts at `;`); recorded as a residual.
- N3: recorded as a residual, with the comment-splitting quirk found while testing (a `;`/`&&` inside a trailing comment
  splits). The test helper skips the comment mention for compound texts.
- Results: pip guard tests 332 passed; corpus gate and wiring 494 passed; black, ruff, mypy, pyright clean.

## Results (round 1)

- Pip guard tests (4 files): 296 passed. Corpus gate + wiring tests: 488 passed.
- black, ruff, mypy clean on touched files. pyright reports only an environmental
  `Import "pytest" could not be resolved` on the new test (no lsp venv in the worktree), nothing in src.
- Tests run with `PYTHONPATH` set to the worktree `src`, because the shared venv's editable install points at main.
