STOPPING BECAUSE: the round-2 review is finished. Two round-1 blockers were only partly fixed, and those gaps now block the merge.

# Round 2 review: Plan 00483 batch (c), tip 3b20d2edd

**Verdict: CHANGES REQUESTED**

## How this was checked
- **Tests:** 1569 targeted tests passed (curl, root and worktree suites, git guard shapes, command_evasion, shell_segmentation, shell_expansion), and the ordinary-command gate passed 438/438. Output is in `/workspace/untracked/scratch/batchc-review-r2/pytest.txt` and `pytest_gate.txt`.
- **Probe:** `/workspace/untracked/scratch/batchc-review-r2/probe.py` runs each handler's `matches()` on the same commands against main and against the branch. Results are in `main.tsv` and `branch.tsv` in the same folder.

## Round-1 items

- **B1, partly fixed.** `sh -e -c`, `bash -x -c`, `bash -n -c`, `bash -o pipefail -c` and `bash -euo pipefail -c` around a worktree `cp` now deny. Other common shell forms still went from DENY on main to allow on the branch (each probed as `<form> 'cp untracked/worktrees/X/src/file.py src/x.py'`):
  - `sudo bash -c '…'`
  - `/bin/bash -c '…'`
  - `env bash -c '…'`
  - `bash --login -c '…'`
  - `bash --norc -c '…'`

  The fix widened the regex. Round 1 asked for a word walk instead, and the regex still cannot handle `sudo` or a path before the shell name, `env`, or long options.
- **B2, partly fixed.** `-exec` and a plain `| xargs` now deny. Still DENY on main and allow on the branch:
  - `find / -maxdepth 1 -type d |` + newline + `  xargs grep -r x`. This is the same line-end pipe shape as B3. `_SEGMENT_SPLIT_RE` also splits on `\n`, so the stage after the `|` is an empty segment.
  - `find / -maxdepth 1 -type d | sudo xargs grep -r x`. `_is_xargs` only removes `VAR=` prefixes.
  - `| parallel grep -r x` and `| while read d; do grep -r x "$d"; done` also pass. These are less common, so they are a should-fix rather than a blocker.
- **B3, fixed.** `curl … |` + newline + `sh`, `python3`, and `| \n\n sudo bash -s` all deny. Commands that should be allowed still are: `||` + newline + `echo`, and `| jq . |` + newline + `grep`.
- **S1, fixed.** `/dev/stdin`, `/dev/fd/0` and `/proc/self/fd/0` deny for python3, perl and ruby. `STDIN_OPERANDS` is shared by `curl_pipe_shell.py` and `shell_expansion.py:2709`, and the import is not circular (the tests import both).
- **S2, fixed.** Both comments in `worktree_file_copy.py` now describe the segment-based behaviour.
- **S3, fixed.** Both acceptance probes are `bash -n -c '…'` again, and the probe confirms the `cp` form denies.
- **S4, mostly fixed.**
  - `QUOTED_SPAN_REGEX` (`command_evasion.py:80`) is now the one shared piece, used by `_GIT_GLOBAL_OPTION` and `_MESSAGE_BODY_PATTERN`.
  - The `-e` gap in the guidance is fixed (`destructive_git.py:1061`).
  - Still open: the `_git_grep_pattern_spans` duplication is a "Still open" line inside N383's Fixed entry (`NIGGLES.md:1558`), not a new open entry as round 1 asked. Any sweep that skips Fixed entries will miss it. This does not block.
- **NIT N2, fixed.** The Rule text and the guidance now say "from a worktree into the main repo's code dirs" and say the reverse copy is not blocked.

## Blockers left

### R2-B1: worktree_file_copy still misses common shell `-c` wrappers (confidence 90)
**Where:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/worktree_file_copy.py:61-67`, the `(?:(?:ba|z|da|k)?sh\s+(?:…)*?-\w*c\s+)?(?:sudo\s+)?(?:\S*/)?` prefix of `_RELOCATION_VERB_RE`.

**Problem:** The 5 forms listed under B1 were denied on main, because main matched on the opening quote. The branch allows them. `sudo bash -c` and `/bin/bash -c` are ordinary, everyday ways to write this, not deliberate disguises.

**Fix:** do what round 1 suggested. Find the verb by walking words with `shell_word_spans` + `resolve_shell_word`:
- skip `sudo`, `env` and `VAR=` prefixes,
- skip a shell name given with or without a path,
- skip every option word, including `--long` options and `-o value`,
- stop at `-c`.

Then drop the regex prefix. Add the 5 commands to `DANGEROUS` in `tests/unit/handlers/test_worktree_file_copy_segments.py`.

### R2-B2: root_recursion_guard's depth bound ignores `xargs` after a line-end pipe or `sudo` (confidence 80)
**Where:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/root_recursion_guard.py:258-261` (`_is_xargs`) and `:327-336` (the `feeds_xargs` logic).

**Problem:** A pipe at the end of a line is treated as if the pipeline ended there, so the stage that receives the output is an empty segment. `sudo xargs` is not recognised as `xargs`. Both commands are full-disk walks that main denied. Round 1 already ruled that ending a line on `|` is in scope (B3).

**Fix:**
- Treat a `|` followed by a newline as a continuation, either by reusing the same join `curl_pipe_shell` uses or, better, by moving `_PIPE_AT_LINE_END` into a shared utility used by both handlers.
- Have `_is_xargs` skip `sudo`/`env` the way `_segment_is_dangerous` skips wrappers.
- Simplest option: treat a `-maxdepth` bound as a bound only when nothing comes after the `find` in a pipe, except a known data sink (`sort`, `wc`, `head`, `grep`). That also covers `parallel` and `while read`.

Add tests for the line-end pipe, `sudo xargs` and `while read` forms in `tests/unit/handlers/pre_tool_use/test_root_recursion_guard_operands.py`.

## Regression check on the fixes
- The wider B1 regex adds no false positives: `bash -n -c 'echo hi'` and `sh -e -c 'ls src/'` are allowed.
- The B2 change does not catch a `-name` value that merely contains "exec" (`find / -maxdepth 1 -name 'exec*'` is allowed), and `find src -exec grep` stays allowed.
- `_PIPE_AT_LINE_END` leaves `||` and line-end pipes between data commands alone.
- I found nothing else.

## Should-fix (non-blocking, to be filed)
- N383's leftover NIT should get its own open niggle entry: `CLAUDE/Plan/00474-niggles-ledger-seventeen/NIGGLES.md:1558`.
- The `| parallel` and `| while read` forms after a bounded `find`, if R2-B2's fix does not already cover them.