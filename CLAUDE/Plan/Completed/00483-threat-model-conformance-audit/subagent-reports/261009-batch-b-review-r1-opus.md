STOPPING BECAUSE: the review is complete; the verdict and findings are below.

# Code Review: Plan 00483 Task 3.2 batch (b), round 1 (`destructive_git` / `git_stash`, tip e7d6d5e6e)

## Summary

**Verdict: REQUEST CHANGES.** The narrowing works for the shapes the branch set out to fix, and every wrapped form you listed still denies. But the new step that blanks quoted text for any `git` segment also blanks git subcommands that run their quoted argument. So `git submodule foreach 'git reset --hard'` and three similar forms were denied on `main` and are now allowed.

- **Reviewed:** 9 files, 519 lines added and 21 removed.
- **Findings:** 1 BLOCKER, 3 SHOULD, 4 NIT.
- **Tests:** I ran the branch's targeted tests with the worktree's `src/` first on `PYTHONPATH`, because the worktree has no venv of its own. The branch's own suites gave 2236 passed. A second run over the other git-guard, heredoc, segmentation, acceptance and guidance tests gave 1266 passed. There were no failures.
- **Suppressions:** none. The diff contains no `noqa`, no `type: ignore` and no new allowlist, whitelist or `exclude_paths` entry.

## Probe evidence

These scripts are kept for the plan folder:
- `/workspace/untracked/scratch/00483-review-batch-b-probe.py`: 181 commands, run against `main` and the branch. Outputs are `00483-probe-main.txt` and `00483-probe-branch.txt`.
- `/workspace/untracked/scratch/00483-review-batch-b-probe2.py`: loop statements and git subcommands that run text. Output is `00483-probe2-out.txt`.
- `/workspace/untracked/scratch/00483-review-batch-b-probe3.py`: checks each `a8-*` row against `main`.
- Pytest logs: `/workspace/untracked/scratch/00483-review-b-pytest.txt` and `00483-review-b-pytest2.txt`.

**What still denies on the branch (all 108 cases):** `git reset --hard`, `git clean -fd`, `git checkout -- f`, `git restore f`, `git stash` and `git stash push`, each in these 18 positions:
- alone;
- after `x &&`, `x ;`, `x ||` and `ls |`;
- inside `echo $( )`, `bash -c '…'` and `sh -c "…"`;
- after `cd x &&`, after an env prefix (`GIT_DIR=x …`), and after `xargs`;
- after `git log --grep=x &&` and after `git log --grep='a b' &&`;
- inside a `while read` loop body;
- as the body of `bash <<'EOF'`, `sh <<'EOF'` and `bash -s <<'EOF'`, and of `cat <<'EOF' | bash`.

**Other shapes that deny:**
- `git -C dir …`, including `git -C 'my dir' …`, which `main` allowed (an improvement).
- `git clean -n -f` and `git clean -fn` (deliberately conservative).
- `find … | xargs git clean -fd`.
- `while read l; do $l | eval $l | echo $l | sh | sh -c "$l"; done <<'EOF'`, and a printing loop whose output is piped to `| bash`.
- `gh … <<'EOF' | bash` and an unquoted `gh` heredoc containing `$(git reset --hard)`.
- `awk` calling `system(…)` or using `| "sh"`.
- `git restore -s`, `--staged --worktree`, `-WS` and `-p`.

## BLOCKER

### B1. Quoted command arguments of `git submodule foreach`, `git rebase --exec` and `git bisect run` are now treated as data (confidence 95%)

**Location:** `src/claude_code_hooks_daemon/utils/command_position.py`, in `_TEXT_ARGUMENT_HEADS = {"git", "awk", …}`, `_runnable_text` and `blank_quoted_text_arguments`.

**Problem:** For any segment whose head is `git`, every quoted span that contains a blank is replaced by a placeholder. The only exception is text that starts with `!`. Several git subcommands run their quoted argument as a shell command, so the dangerous command disappears before the guard looks at it.

Probe results (`main` → branch):
```
DENY → ALLOW  git submodule foreach 'git reset --hard'
DENY → ALLOW  git submodule foreach --recursive 'git reset --hard && git clean -fdx'
DENY → ALLOW  git submodule foreach --quiet 'git stash'
DENY → ALLOW  git submodule foreach "git reset --hard"
DENY → ALLOW  git rebase -i --exec 'git clean -fd' HEAD~3
DENY → ALLOW  git rebase -x 'git stash' main
DENY → ALLOW  git bisect run bash -c 'git stash && make'
```

**Why it matters:** `git submodule foreach --recursive 'git reset --hard && git clean -fdx'` is the standard command for resetting every submodule. A careless agent writes it as is. The destructive text is visible in the command, not hidden in a variable, so ARCHITECTURE.md:822-825 does not put it out of scope. It is the same case as `bash -c 'git reset --hard'`, which the branch itself lists under DANGEROUS. This is a real careless invocation that now gets through, and it is a regression from `main`.

**Fix:** Stop blanking every quoted argument of `git`. Blank only the pattern and format values of read-only subcommands:
- Use the existing `git_subcommand_index` (as `secret_file_matching._git_grep_pattern_spans` already does) to find the subcommand.
- Blank only when it is one of `log`, `show`, `grep`, `shortlog`, `rev-list`, `reflog` or `whatchanged`.
- Within those, blank only the values of `--grep`, `-S`, `-G`, `-e`, `--format` and `--pretty`.

Add every row above to the DANGEROUS list in `test_git_guards_command_shapes.py` as red tests first.

## SHOULD

### S1. A git alias quoted as one whole word is now allowed, which contradicts the guidance (confidence 85%)

**Location:** `command_position.py`, in `_runnable_text`, where git text counts as runnable only if it starts with `!`.

**Evidence:** `git -c 'alias.n=!git reset --hard' n` was DENY on `main` and is ALLOW on the branch. Only the spelling `alias.n='!…'` is caught. The new text in `destructive_git.py` says "a `!` alias definition … still judged", and the threat model counts quoting as an ordinary respelling.

**Fix:** Treat git text as runnable when it contains `=!` or starts with `!`. Fixing B1 with a read-only subcommand allowlist also fixes this, because `-c` comes before the subcommand. Add the row to the test file's list of commands that must stay denied.

### S2. The loop exemption misses a line run inside a printing command's substitution (confidence 75%)

**Location:** `shell_segmentation.py`, `_loop_only_prints_its_input`.

**Evidence:**
- `while read l; do echo "$($l)"; done <<'EOF'⏎git reset --hard⏎EOF` was DENY and is now ALLOW.
- The same loop with `` echo `$l` `` is also now ALLOW.
- `out=$($c)` still denies, as does `do $l`, which the branch tests. So the guard is inconsistent about the same act.

The checks the existing sink path applies (`_stage_is_inert_sink`, whose docstring says "the stage carries no substitution at all") are not applied to the loop prefix. Only `<(` is checked there.

**Fix:** Return False when any loop statement contains `$(` or a backtick. Add both rows as tests.

### S3. A second reader of quoted git arguments was added alongside an existing one (confidence 75%)

**Location:** `command_position.py`, `_blank_spaced_quotes` and `blank_quoted_text_arguments`.

**Problem:**
- `_blank_spaced_quotes` is its own quote scanner, using `word.find(char, …)` with no escape handling. That duplicates `command_evasion._quoted_span_end`.
- The git-pattern logic duplicates `secret_file_matching._git_grep_pattern_spans` together with `git_subcommand_index`, which already places git pattern operands by subcommand and option.

**Answer to your segmentation question:** the segment split itself does reuse the existing segmentation. `command_position_segments`, `shell_word_spans`, `split_unquoted_spans` and `_segment_command_word` are all reused. But the step that decides which quoted text is data is a new, looser parser, and that looseness is the root cause of B1.

**Fix:** Bring it together with the existing git-operand reader as part of the B1 fix.

## NIT

- **N1. A gate row that pins nothing:** `a8-heredoc-cat-mentions-reset-hard` (in `tests/fixtures/ordinary_command_corpus.yaml`) was already ALLOW on `main` (probe3). Drop it, or replace it with a shape this branch actually fixed. The other 11 `a8-*` rows were DENY on `main` and are ALLOW on the branch, so they are sound regression rows. The `set -euo pipefail;` prefixes are correct for the safe-mode-prelude rule.
- **N2. An invented flag in a gate row:** `a8-reset-then-ls-hard` uses `ls --hard`, which is not a real `ls` flag. The mechanism it tests is real, but a corpus of ordinary commands should hold real commands. `git reset HEAD f && grep --hard-links x` or similar would do the same job.
- **N3. A common printing loop is still denied:** `while IFS= read -r c; do echo "$c"; done <<'EOF'` is a false positive, apparently because of the `IFS=` assignment prefix on the `while` statement. Add it as a red test if this batch is meant to cover printing loops.
- **N4. Generated commands piped to a shell:** `git log --format='git reset --hard %H' | sh` went from DENY to ALLOW. Building a command line and piping it to `sh` is unusual for a careless agent, but if the B1 fix keeps blanking `--format`, withhold the blanking when a later pipe stage is a shell.

## Guidance and acceptance tests

- The `destructive_git` and `git_stash` guidance matches the behaviour, apart from the alias claim in S1.
- `git stash --help`/`-h`, `x && git stash`, `git clean -nd build-final/` and the `--staged`/`--source` rules for `git restore` all behave as described.
- No acceptance-test entries were added for the new allow paths, though `test_acceptance_negative_case_requirement` and `test_claude_md_guidance_coverage` pass.
- The new `git restore` regex (case-sensitive `-S`/`-W` via `(?-i:)`) and the `git clean` "flag must start a word" regex are correct. They also close two misses on `main`: `-s` and `--staged --worktree`.

## Positive observations

- Judging each segment on its own is a clean fix that reuses the existing code. `_match_reason`, `_match_rule_id` and `_match_rule_ids` all go through `_segment_matches`, so they cannot disagree.
- The tests are real behaviour tests: each DANGEROUS row is also checked behind 5 lead-ins.
- Commands that hand a heredoc on to something that runs it (`| bash`, `eval`, `$l`, `bash -c`) are tested as denied.

## Summary
1. **Verdict: REQUEST CHANGES.** One BLOCKER, three SHOULD, four NIT.
2. **BLOCKER B1:** `git submodule foreach '<cmd>'`, `rebase --exec/-x` and `bisect run sh -c` went from deny to allow.
3. **Cause:** `blank_quoted_text_arguments` blanks every quoted argument of every `git` segment. It should blank only read-only pattern/format options.
4. **SHOULD:** S1 whole-word-quoted `-c 'alias.n=!…'` is allowed, against the guidance. S2 the loop exemption ignores `$( )`/backticks. S3 a second quoted-argument reader.
5. **What holds:** all 108 wrapped forms of the six commands deny, plus `-C`, `xargs`, the shell heredocs and the `gh`/loop `| bash` forms. No suppressions or allowlists were added.
6. **Tests:** targeted runs gave 2236 and 1266 passed. 11 of the 12 `a8-*` rows are sound; one is redundant and one uses an invented `ls` flag.