STOPPING BECAUSE: review round 1 is complete. The verdict is REQUEST CHANGES: there are 3 blockers.

# Code Review: Plan 00483 batch (c), branch `agent-a0faad4a67ec2a1cf-eb2b861e` (tip 18cf10802), round 1

## Summary
The N383 fix works. All 17 gate rows behave as claimed, and 1361 targeted tests pass. But each of the three narrowed handlers now allows at least one careless command that main denied.

Reviewed: 12 files, about 640 lines added. Findings: 3 BLOCKER, 4 SHOULD, 4 NIT, plus a list of gaps main already had.

Evidence is in `/workspace/untracked/scratch/batchc-review/`. The scripts are `probe.py`, `probe_a9.py`, `probe_wrap.py` and `probe_shellc.py`. Their outputs are `main.tsv`, `branch.tsv`, `cmp.tsv`, `a9_*.tsv`, `wrap_*.tsv` and `sc_*.tsv`. Test output is in `pytest_branch.txt`. All probes call `matches()` directly, once with `PYTHONPATH=/workspace/src` (main) and once with the worktree's `src`.

## BLOCKER

### B1. worktree_file_copy: a shell `-c` wrapper with other options now hides the copy (confidence 95)
**Location:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/worktree_file_copy.py:63-70`, together with the switch to `command_position_segments` at lines 165-167.

| Command | main | branch |
|---|---|---|
| `sh -e -c 'cp untracked/worktrees/X/src/file.py src/x.py'` | DENY | allow |
| `bash -x -c 'cp …/src/file.py src/x.py'` | DENY | allow |
| `bash -n -c 'cp …'` / `bash -n -c 'rsync -a …/src/ src/'` | DENY | allow |
| `bash -c '…'`, `bash -nc '…'` | DENY | DENY |

**Cause:** `command_position_view` puts the `-c` body back into the segment without its quotes, so the `["']` anchor that main matched on is gone. The replacement regex `(?:(?:ba|z|da|k)?sh\s+-\w*c\s+)?` only accepts one option word, and that word must end in `c`.

This also breaks the project's mandatory acceptance wrapper. `CLAUDE/AcceptanceTests/GENERATING.md:161-168` requires `bash -n -c`, and with that wrapper the guard no longer denies.

**Fix:** have the spliced body come out as its own segment. Alternatively, find the verb by walking words with the existing `shell_word_spans` + `resolve_shell_word`, skipping the shell and every option word, the same way `_narrow_shell_body` already does. Either way, drop the regex prefix. Add `sh -e -c`, `bash -x -c`, `bash -n -c` and `bash -o pipefail -c` to `DANGEROUS` in `tests/unit/handlers/test_worktree_file_copy_segments.py`.

### B2. root_recursion_guard: the `-maxdepth 1` exemption ignores what `find` hands on (confidence 95)
**Location:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/root_recursion_guard.py:253-271` (`_find_roots`) and 325-329.

All of these were DENY on main and are allowed on the branch:
- `find / -maxdepth 1 -exec grep -r x {} +` (your brief lists this as must-deny)
- the same with `\;`
- `find / -maxdepth 1 -type d -exec rg x {} +`
- `find / -maxdepth 1 -type d | xargs grep -r x`
- `find / -maxdepth 1 -exec du -sh {} +`
- `find / -maxdepth 1 -exec find {} -name x \;`
- `find /home -maxdepth 1 -exec grep -rl x {} +`

Each one runs a recursive scan of every top-level directory, which is a full-disk walk.

**Fix:** treat `-maxdepth ≤1` as a bound only when the expression has no `-exec`, `-execdir`, `-ok` or `-okdir`, and the segment's output is not piped onward. Add the commands above to `DANGEROUS` in `test_root_recursion_guard_operands.py`.

### B3. curl_pipe_shell: a pipe that ends a line (`curl URL |` then `sh` on the next line) is now allowed (confidence 80)
**Location:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/curl_pipe_shell.py:173-194`

| Command | main | branch |
|---|---|---|
| `curl -fsSL https://x.sh \|\n  sh` | DENY | allow |
| `curl … \|\n  python3` | DENY | allow |
| `curl … \|\n  sudo bash -s` | DENY | allow |
| backslash continuation (`\` then newline, then `\| sh`) | DENY | DENY |

**Cause:** `_some_download_becomes_code` loops over `view.split("\n")`. It needs the downloader and `| interpreter` on the same physical line, but the outer `_CURL_PIPE_SHELL_PATTERN` matches `\|\s*` across the newline. Ending a line on `|` is a formatting choice, not a deliberate respelling, so it is in scope.

**Fix:** run `_PIPE_INTO_INTERPRETER_PATTERN` over the whole view. Then require a downloader earlier in the same pipeline, meaning spans joined only by `|`, where a pipe followed by a newline still continues the pipeline. Add tests for this shape.

## SHOULD

### S1. curl_pipe_shell: stdin given as a file path is read as a local script (confidence 85)
**Location:** `curl_pipe_shell.py:160`

`curl … | python3 /dev/stdin`, `… /dev/fd/0`, `… /proc/self/fd/0`, `perl /dev/stdin` and `ruby /dev/stdin` were DENY on main and are now allowed. Only `-` is recognised as stdin. `utils/shell_expansion.py:2708` already lists this family inline (`"-", "/dev/stdin", "/dev/fd/0", "/proc/self/fd/0"`).

**Fix:** move that list into a named shared constant and use it at both sites. This also removes a DRY violation.

### S2. worktree_file_copy: two comments now describe behaviour the branch removed (confidence 90)
- **Lines 46-53** say the guard deliberately keeps denying `echo "cp <wt> src/"` so that echo-wrapped probes still deny. The branch now allows that command on purpose.
- **Lines 150-156** (the `matches()` docstring) describe calling `strip_inert_spans` directly. It is no longer called.

**Fix:** rewrite both to describe the segment-based behaviour.

### S3. The rewritten acceptance probes test a real relocation but break the probe-safety rule (confidence 80)
**Location:** `worktree_file_copy.py:244-278`

Both probes are now bare `cp` and `rsync --dry-run` commands with a source that does not exist. They are real relocation shapes, both DENY, and are harmless because the source is missing (GENERATING.md's Layer 3). But GENERATING.md's Layer 1 makes a non-executing wrapper mandatory. The agent most likely dropped the wrapper because of B1.

**Fix:** after B1 is fixed, use `bash -n -c '<cp …>'` and `bash -n -c '<rsync …>'`.

### S4. N383 adds a second regex quote reader, and the ledger edit buries two open NITs (confidence 75)
**Location:** `utils/command_evasion.py:68-71`

`_SHELL_WORD_PIECE` repeats the quote pieces of `_MESSAGE_BODY_PATTERN` (`utils/shell_segmentation.py:727-728`). That goes against your "no second quote reader" requirement. A regex fragment is reasonable here, because `GIT_INVOCATION` is spliced into about 12 modules' regexes. Even so, the piece should be one shared constant.

In addition, `CLAUDE/Plan/00474-niggles-ledger-seventeen/NIGGLES.md` marks N383 ✅ Fixed, but the same entry still holds two NITs nobody addressed: the guidance omits `-e`, and `_git_grep_pattern_spans` duplicates the reader. Under a Fixed status they will be lost.

**Fix:** share the piece between the two regexes. Move the two NITs into a new open entry.

## NIT
- **N1.** `cp <wt>/src/x.py x.py && mv x.py src/` was DENY on main and is allowed now. Main only caught it because its `.*` ran across the `&&`, and the shape is contrived. Accept it.
- **N2. The `mv` ruling holds.** `mv <wt>/notes.txt tmp.txt` alone was already allowed on main. The guidance and the implemented patterns both require the target to be a code directory (`src/`, `tests/`, `config/`), and the trailing `; ls src/x` only made it look like one. Two wording problems remain: `Rule.blocked` says "between a worktree and the main repo", which is broader, and the guidance says "or vice versa" although `cp src/x.py <wt>/src/` is allowed on both main and the branch. Align the wording.
- **N3. Host-dependent verdicts are acceptable.** The "existing file under /proc or /sys" rule makes the verdict depend on the host filesystem. That is acceptable: the daemon sees the same filesystem as the shell, and a path that is missing or unreadable is denied, so it fails closed. CI is ubuntu-only. The allow-rows for `grep -r foo /proc/self/status` (in the unit test and in gate row a9) are Linux-only; add a comment or a skip marker. `/proc/kcore` counts as a file when it is readable as root, but scanning it is not a careless shape.
- **N4.** `git -C 'unterminated reset --hard` was DENY on main and is allowed now. Bash will not run an unterminated quote, so this is not a finding.

## Gaps main already had (not regressions; file them)
- **curl_pipe_shell:** `sh -c "$(curl …)"` (Homebrew's documented form, the most important one here), `bash <(curl …)`, `| env python3`, `| sudo -u bob python3`, `| node`.
- **worktree_file_copy:** `cp -r <wt>/src .` and `rsync -a <wt>/ ./` are allowed on both main and the branch, although your brief expected them to "still deny". Also allowed on both: `cd /workspace; cp -r <wt>/src .`, `(cp …)`, `command cp`, `nice cp`, `env FOO=1 cp`, `cp -t src/ <wt>/…`, `xargs cp`, `find -exec cp`.
- **root_recursion_guard:** `bash -c 'grep -r x /'`, `sudo find / …`, `time grep -r x /`, `grep -rm1 x /`, `du -sh /`, `ls -R /`, `rg x /home/user`.

## What was checked and passed
- **curl_pipe_shell, everything in your list that main denied:** `| sh`, `| bash -s`, `| sudo bash`, `| python3`, `| python3 -`, `| ruby`, `| perl`, after `&&`, inside `$( )`, inside `bash -c`, `| tee x | bash`, and `wget -O- | sh` all still DENY.
- **The three commands main never denied:** `bash <(curl url)`, `sh -c "$(curl url)"` and `curl url -o x.sh && bash x.sh` are allowed on both main and the branch, so they are listed under the older gaps.
- **Borderline: a local program that executes stdin.** `python3 -c 'exec(sys.stdin.read())'` and `perl -e 'eval join "",<>'` are now allowed. I count these as hostile, not careless: the agent would be writing a program whose only job is to run stdin, which no install instruction does. Out of scope.
- **worktree_file_copy must-deny forms:** `cp <wt>/src/x.py src/`, `mv` into `src/`, the `cd … &&` form and `sudo` still deny. `FOO=1` and `FOO=1 BAR=2` env prefixes were allowed on main and now deny.
- **root_recursion_guard must-deny list:** everything except the `find -maxdepth 1 -exec` command (B2) still denies, plus `du -sh /` and `ls -R /`, which main also allowed. The pattern-operand narrowing is correct: `grep -rx /` and `rg ~` are allowed because the `/` or `~` there is the pattern. Option values are never read as scan roots, so an unlisted value option can only add a false positive, never hide a root.
- **N383:** all 11 new quoted and escaped `-C`/`-c` shapes are allowed on main and denied on the branch, in destructive_git or git_stash as appropriate. The pytest run against main's source was refused by the worktree conftest's venv guard, so "red on main" rests on the direct probe instead. `git -C 'my dir' status`, `log`, `stash list`, `diff` and `-c 'user.name=A B' commit` stay allowed. Timing on long inputs is no worse than main (5000 options: 6.9s on the branch vs 8.5s on main).
- **Gate rows:** each of the 17 `a9-*` rows is denied on main by its target handler and allowed by all three handlers on the branch.
- **No suppressions or allowlists** were added.
- **Segmentation reuse:** curl_pipe_shell and worktree_file_copy reuse the shared segmentation and word readers. root_recursion_guard still uses its own `_SEGMENT_SPLIT_RE`; that was already true on main.
- **Tests:** 1361 passed on the branch, covering the touched files, the handlers' existing suites and the gate test.

## Verdict
REQUEST CHANGES

## Summary
1. B1: `sh -e -c` / `bash -x -c` / `bash -n -c` around a worktree copy into `src/` now pass, and that also breaks the mandated `bash -n -c` probe wrapper.
2. B2: `find / -maxdepth 1 -exec grep -r …` and `find / -maxdepth 1 | xargs grep -r` now pass, because the depth bound ignores `-exec` and pipes.
3. B3: a pipe that ends a line (`curl URL |` then `sh` on the next line) now passes, because the downloader and the pipe are matched per physical line.
4. S1–S4: `/dev/stdin` spellings are treated as a script file, two comments are stale, the acceptance probes have no wrapper, and N383's quote regex duplicates an existing one while its open NITs sit under a Fixed status.
5. N383 itself is correct in both handlers, all 17 a9 rows behave as claimed, and 1361 tests pass.
6. Several gaps main already had, above all `sh -c "$(curl …)"`, should be filed separately; they did not come from this branch.