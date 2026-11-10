STOPPING BECAUSE: review complete. Verdict is REQUEST CHANGES, on one Important finding.

**Counts:** Critical 0, Important 1, Suggestion 3. **Not approved.**

**1. Probe re-run on HEAD.** The saved set has 99 cases (85 in `cases.json` plus 14 in `c2.json`), not 103. No errors. Every case not targeted by this commit keeps its verdict against the previous commit 2a4e8e8a1, and the saved `head.json`/`h2.json` match 2a4e8e8a1 exactly. All the suggestion cases now deny: `sh < s.sh`, `bash -s <`, `cat s.sh | sh`, the literal form, and the `printf -v` forms.

**Important 1: a shell is treated as reading the written file on stdin when it is not** (confidence 75; new in this commit; under the threat model this is a false positive the fix itself adds).
- **Where:** `command_position.py`, in `_runs_written_script`, plus `_reads_shell_input`.
- **Cause, part 1:** once any segment `cat`s a written path, `fed` stays set for every later segment, across `;` and `&&` as well as `|`.
- **Cause, part 2:** `_reads_shell_input` returns True for `bash build.sh`, which takes a script operand and does not read stdin.
- **Reproduction:** `echo '<reset text>' > notes.txt; cat notes.txt && bash scripts/qa.sh` and `…; cat s.sh; sh other.sh`. Both ALLOW on origin/main and DENY on HEAD. The same cause makes `bash -n < s.sh` (a syntax check only) and an unused `printf -v x '<reset text>'` newly DENY, which are minor.
- **Fix:** set `fed` only for the segment directly after a `|`. Make `_reads_shell_input` return False when the shell has a non-option operand other than `/dev/stdin` or `-`, or when it has `-n`. Add these three commands as allow-tests.

**2. Variants still allowed on HEAD that origin/main denied (substitution form):** `sh 0< s.sh`, `< s.sh sh`, `sh<s.sh`, `cp s.sh t.sh; sh < t.sh`, `exec|env|command sh < s.sh`. The literal-echo form of each already ALLOWs on main, so these are gaps that already existed, at the level of the previous Suggestion 1.
- **Suggestion 1:** in `_stdin_paths`, accept an `N<` prefix and a word that only contains `<`. Strip `exec`, `env` and `command` before the head test.
- Covered already: `sh <s.sh`, `sh < ./s.sh`, `cat s.sh - | bash`, `bash /dev/stdin < s.sh`, `cat < s.sh | sh`, `dash`, `-x`, `-e`, `-s --`, and `tee <<<` then `sh <`.

**3. `printf -v` spellings.**
- **Suggestion 2:** `printf -vn` and `builtin printf -v n` still ALLOW, while `printf -v "n"` correctly denies. `_assigns_variable` only matches the exact word `-v` and a head of `printf`. Fix: test `word.startswith("-v")` and skip a leading `builtin` or `command`.

**4. Over-tightening against origin/main.** These all stay ALLOW: `sh < s.sh` and `bash < setup.sh` with no write, `cat notes.md | less`, `cat s.sh | sh`, harmless written scripts, and `cat`, `wc`, `shellcheck`, `sha256sum` or `less` over a written file. The only new DENYs are the ones in Important 1.

- **Suggestion 3:** add tests that pin these allows, especially `cat X; bash other.sh`.

The two temporary worktrees were removed with plain `git worktree remove`. Probe inputs and outputs are in `/workspace/untracked/scratch/rv596out/` (`v.json`/`vh.json`/`vm.json` for the variants, `w.json`/`wh.json`/`wm.json` for the over-tightening cases).