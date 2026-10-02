# N241 / N200 review (Opus): branch `worktree-n241-stash` @ 300eb70ed

## Verdict

**MERGE-WITH-FIXES.** The direction is right and the prose cases are fixed. The
N200 per-segment judgement and the N85 single-quote fix are correct. But the
branch adds new fail-opens on ordinary literal shapes that main denies. It also
removes the only layer that stopped the acceptance suite running real
destructive commands. Fixes M1-M4 must land before merge.

Evidence: scripts and JSON outputs are in `untracked/scratch/n241-review/`
(`probe.py`, `cases*.py`, `main.json`, `branch.json`, `more_*.json`,
`safe_branch.json`, `merged.json`, `run_corpus.py`). Each handler was built the
way its unit tests build it, `Handler().matches({"tool_name": "Bash", ...})`,
after `reset_data_layer()`. The probe was run with main's src and then the
branch's src first on `sys.path`.

## 1. Fail-open probe: main verdict compared with the branch verdict

`S` = git_stash.matches, `D` = destructive_git.matches (True = deny).

### Regressions (main denies, branch allows)

| Command                                             | main S/D | branch S/D | In scope?                                     |
| --------------------------------------------------- | -------- | ---------- | --------------------------------------------- |
| `echo 'git reset --hard' 2>&1 \| bash`              | F/T      | F/F        | YES: ordinary literal pipe to a shell         |
| `echo 'git stash' 2>&1 \| bash`                     | T/F      | F/F        | YES                                           |
| `echo 'git reset --hard' >&2 \| bash`               | F/T      | F/F        | yes (bash receives nothing, harmless)         |
| `echo 'git stash' &>/dev/null \| bash`              | T/F      | F/F        | harmless (stdout discarded)                   |
| `echo 'git reset --hard' \| (bash)`                 | F/T      | F/F        | YES                                           |
| `echo 'git reset --hard' \| fish`                   | F/T      | F/F        | YES: literal body piped to a shell            |
| `echo 'git reset --hard' \| busybox sh`             | F/T      | F/F        | YES                                           |
| `echo 'git reset --hard' \| su -c bash`             | F/T      | F/F        | YES                                           |
| `echo 'git reset --hard' \| docker exec -i box sh`  | F/T      | F/F        | yes (runs in a container)                     |
| `echo 'git reset --hard' \| kubectl exec -i p -- sh`| F/T      | F/F        | yes (remote)                                  |
| `echo 'git reset --hard' \| ssh host`               | F/T      | F/F        | yes (remote host)                             |
| `echo 'git reset --hard' \| at now`                 | F/T      | F/F        | YES: deferred, but runs here                  |
| `echo 'git stash' \| parallel`                      | T/F      | F/F        | YES: parallel runs each line                  |
| `echo 'git reset --hard' \| tee >(bash)`            | F/T      | F/F        | yes (one level of process substitution)       |
| `echo 'git reset --hard' \| python3`                | F/T      | F/F        | no: not Python, never runs                    |
| `rg --pre 'git stash' x`                            | T/F      | F/F        | marginal: `--pre` RUNS its value              |
| `echo 'git stash' > s.sh && bash s.sh`              | T/F      | F/F        | OUT (file-run, threat model 1); noted only    |
| `printf … \| while read -r l; do $l; done`          | T/F      | F/F        | OUT (variable); noted only                    |

### Held (identical deny on both)

Each of these is denied by the same handler on main and on the branch:

- `echo x && <cmd>`, `echo $(...)`, `printf … | sh`, `echo "x" > f; <cmd>`
- `grep x f || git clean -fd`, `rg x; git push --force`
- `echo HEAD | xargs git reset --hard`, `echo … | xargs -I{} sh -c '{}'`
- `bash -c "…"` (double-quoted), `sh -c`, `bash -lc`, `bash -o pipefail -c`
- `git -C dir …`, `cd d && …`, newline-separated segments
- `time`, `sudo`, `env X=1`, `nohup`, `timeout 5`, `exec`, `command`, `watch`
- `( … )`, `{ …; }`, `(echo hi; …)`
- `$(…)`, backticks, `$(echo git stash)`, `` `echo git stash` ``
- `find -exec`, `xargs git stash`
- `| tee log | bash`, `| sudo bash`, `| sudo -u bob bash`, `| timeout 5 bash`,
  `| nice bash`, `| nohup bash`, `| exec bash`, `| command bash`, `| zsh`,
  `| bash -s`, `| /bin/bash`, `| { bash; }`, `|& bash`, `| eval`
- `bash <(echo …)`, `source <(echo …)`, `bash <<<'…'`
- quoted heredoc fed to `bash`, `cat <<'EOF' | bash`
- `if grep …; then …; fi`, `for … do echo $f; …; done`
- `gh pr create -b "$(git stash)"`, `--body="$(…)"`, `gh … -t \`git stash\``,
  `gh release create -n "$(…)"`, `gh … && git reset --hard`
- `eval '…'`
- nested `bash -c 'bash -c "git stash"'`, `sudo bash -c`, `env bash -c`
- `git commit -m "x \`git reset --hard\`"`, `git commit -m "x $(git stash)"`
- `git commit -m 'it'\''s fine'; git reset --hard`
- `git commit -m $'it\'s'; git reset --hard`

### Newly denied (intended)

- `git commit -m 'x\' ; git reset --hard ; echo 'y'` (N85).
- `git stash list; git stash` and the other N200 rows.

### Now allowed (intended prose)

- `git commit -m '… git stash …'`, `grep -n 'git stash' f`,
  `echo 'do not run git reset --hard'`, `echo 'git stash' && git status`,
  `rg 'git push --force' docs`, `echo '…' > notes.md`,
  `cat > notes.md <<'EOF' … EOF`

### Pre-existing behaviour, not a regression

- An UNQUOTED `cat > notes.md <<EOF` body naming `git stash` is still denied,
  because the body lines split as segments. This is a known false positive that
  the branch neither introduced nor fixed.
- `git stash clear` also fires git_stash, as it does on main.

## Must-fix

### M1. The pipeline-receiver check is a DENYLIST (`_EXECUTORS`), so every unlisted runner fails open (CRITICAL, confidence 90)

**Location:** `src/claude_code_hooks_daemon/utils/command_position.py:49` (`_EXECUTORS`)
and `:100-115` (`_pipeline_feeds_executor`).

The module states the rule itself at `DATA_HEADS`: "An ALLOWLIST: a missing
entry costs a false positive, a wrong entry costs a guard." The receiver side
breaks that rule. A follower is treated as harmless unless its head is one of
`bash sh zsh dash ksh xargs eval source . env sudo`. So `fish`, `busybox sh`,
`su -c`, `parallel`, `at`, `ssh`, `docker exec`/`kubectl exec`, and `(bash)` all
fail open. In the last case `_head` returns `bash)`, because only the LEADING
paren is stripped. `tee >(bash)` also fails open, because a follower's own
expansion is never checked.

The same question already has an ALLOWLIST answer in this codebase:
`shell_segmentation._downstream_is_all_data_sinks` / `_stage_is_inert_sink`,
used by the quoted-heredoc exemption ("An unrecognised or unnameable stage
returns False, which withholds the exemption").

**Fix:** blank a data head's arguments only when there are no downstream pipe
stages, or when every downstream stage is a recognised inert sink. Reuse
`_stage_is_inert_sink` and its pipeline split (`_PIPELINE_TERMINATORS`, then
`|`) rather than keeping a second list. That keeps the N241 row
`grep -rn '…' docs/ | wc -l` allowed. Delete `_EXECUTORS`. Add every in-scope
row from the regression table above as a deny test in
`test_git_guards_command_position.py`.

### M2. `&` in SEGMENT_SEPARATORS splits redirect operators (CRITICAL, confidence 95)

**Location:** `command_position.py:39`.

`SEGMENT_SEPARATORS = ("&&", "||", "|", "&", ";", "\n")` is passed to
`split_unquoted_spans`, which knows nothing about redirects. In
`echo '…' 2>&1 | bash`, the `&` of `2>&1` becomes a segment boundary.
`_pipeline_feeds_executor` then reads the text between the echo segment and the
next one as `&`, not `|`, decides the pipeline has ended, and blanks the echo.
The verdict is allow on both guards. Main denies. `2>&1 | bash` is an ordinary
shape.

**Fix:** do not split on an `&` that belongs to `>&`, `<&`, `&>` or `&>>`.
Either recognise those operators before `&`, or check the neighbouring
characters before accepting `&`. Applying M1 with the existing pipeline split
(`_PIPELINE_TERMINATORS` has no bare `&`) removes this route for the receiver
check. The segment splitter used by `command_position_view`/`_segments` still
needs the fix, because `git stash 2>&1 &` style splitting feeds N200.
Regression rows to add: `echo 'git reset --hard' 2>&1 | bash` and
`echo 'git stash' 2>&1 | bash` must deny.

### M3. The acceptance tests now RUN destructive commands, with no non-executing layer (CRITICAL, confidence 90)

**Location:**
- `destructive_git.py` acceptance tests (all `bash -c '…'` rows)
- `git_stash.py:184-245`
- `CLAUDE/AcceptanceTests/GENERATING.md:159-176` (unchanged, and now contradicted)

`GENERATING.md` prescribes triple-layer safety, and Layer 1 is "Use `echo`
(MANDATORY)". Acceptance tests are run by sub-agents through the real Bash tool.
After this branch, each test's command really executes whenever the guard does
not deny it:

- **git_stash warn-mode tests** (`expected_decision=ALLOW`) run
  `bash -c 'git stash'` and `bash -c "git stash push -m temp-changes"` for real.
  The PASS outcome of these tests stashes the tester's uncommitted work. Their
  `safety_notes` say "the guard denies it before it executes", which is false
  for an ALLOW test.
- `bash -c 'git stash clear'` and `bash -c 'git commit --amend'` have no
  Layer-3 fail-safe argument. A regression, which is exactly what acceptance
  testing exists to catch, would destroy every stash or rewrite HEAD.
- The `git tag -f … NONEXISTENT_SAFE_TEST_SHA` ALLOW test carries the same false
  "guard denies it" safety note. It is harmless only because of the bad SHA.

**Fix:** use a form the guard judges as a command but that cannot run anything.
Verified on the branch (`safe_branch.json`):
- `bash -n -c '<cmd>'`: bash parses and never executes. Both guards deny every
  row: `git stash`, `git stash push -m temp-changes`, `git stash clear`,
  `git commit --amend`, and `-nc` clustered.
- `bash -c 'git -C /nonexistent/safe/test <cmd>'`: the guards deny it, and if
  it ever ran, git would fail before touching anything. This could be layered
  on top of `-n`.

Apply this to every acceptance command in both handlers, including the
warn-mode ALLOW rows. Correct the `safety_notes`. Update `GENERATING.md`
Layer 1 (and the `GENERATING.md:351` example), which still mandates `echo`.
That example is now wrong for these two guards, and an agent following it will
write acceptance tests that can never deny.

### M4. `TestTheGuardHasTeeth` no longer tests what it says (IMPORTANT, confidence 85)

**Location:** `tests/integration/test_handlers_do_not_match_prose.py:315-329`
(branch).

`test_a_deliberate_text_matcher_really_does_fire_on_text` exists to prove the
prose guard would catch an over-matching handler, using a DELIBERATE text
matcher. The branch removes DestructiveGitHandler from `_DELIBERATE_TEXT_MATCHERS`
but keeps it as the subject. It also changes the input to
`bash -c 'git reset --hard HEAD~1'`, which is a real command, not text. The
docstring ("must still match a dangerous command inside a string … the
acceptance suite depends on exactly this behaviour") is now false. Separately,
the `SedBlockerHandler` exemption reason in the same dict still reads "Same
rationale as destructive_git", which now points at a rationale that was
deliberately removed.

**Fix:** retarget the teeth test at a handler that is still exempt
(`SedBlockerHandler` with an `echo "sed -i …"` input). Move the
`bash -c` destructive_git assertion into `test_git_guards_command_position.py`,
where it already exists. Restate the SedBlocker reason in its own words.

## Should-fix (non-blocking; file as plan tasks)

- **S1** `command_position.py:43` `DATA_HEADS` includes `rg`. `rg --pre CMD`
  runs CMD for each file, so `rg` with `--pre`/`--pre=` is not a data head.
  Either treat an `rg` segment carrying `--pre` as non-data, or drop `rg`.
  Confidence 70.
- **S2** `command_position.py:95` `_head` strips a leading `(`/`{` (through
  `_resolved_segment_words`) but not a trailing `)`. Any receiver written
  `(cmd)` resolves to `cmd)`. M1's allowlist makes this fail closed, but
  `_head` should still strip the closer for correct naming. Confidence 75.
- **S3** `docs/guides/HANDLER_REFERENCE.md:805` still describes destructive_git
  as "full-command-string matching". The backtick case it relies on still
  denies (verified), but the wording is now inaccurate. Reword it to "command
  position, including substitutions". Confidence 70.

## Q2: `_MESSAGE_BODY_PATTERN` and other callers

The change from `'(?:[^'\\]|\\.)*'` to `'[^']*'` matches bash: a backslash is
literal inside single quotes. The value can only get SHORTER, so less text is
blanked. Every caller of `strip_message_bodies`/`strip_inert_spans` can
therefore only see more text, which may add a false positive but never a
bypass. `$'…'` ANSI-C values are unaffected, because they start with `$` and
take the bare-word alternative, exactly as before.

I ran 100 test files on the branch, with the branch src first on `sys.path`
(`untracked/scratch/n241-review/testlist.txt`). They cover:

- every `test_shell_segmentation*`, `test_quoted_spans`, `test_message_files`
- `test_sed_blocker`, all `test_pipe_blocker*`, `test_sensitive_content`
- all `test_destructive_git*`, `test_git_stash`, the new tests, and the prose
  integration test
- the test files of every other `strip_inert_spans` user (`daemon_location_guard`,
  `plan_number_helper`, `worktree_file_copy`, `subagent_full_qa_blocker`,
  `upgrade_approval_guard`, `merge_to_main_approval`,
  `reference_repo_freshness`, `bash_file_writes`, `secret_file_matching`)

Result: **8801 passed, 1 skipped, 1 failed.** The failure was
`test_safety_handlers_hostile_input_performance.py::…[quotes]` with a
ZeroDivisionError in the timing baseline (a load flake). Re-run alone it
passed twice (41/41). That test also shows the new view stays linear on
hostile input. The dangerous-invocation corpus check passes on the branch
(29 rows: 8 covered, 9 open, 12 accepted).

## Q3: redirects and heredocs

- Blanking a data head swallows its redirect target too
  (`echo 'git reset --hard' > notes.md` becomes ` echo _ `). That is correct,
  since nothing runs.
- File-then-run (`echo '…' > s.sh && bash s.sh`) is now allowed. It is out of
  scope (threat model 1). Note it, and add an `UNCOVERED-accepted` corpus row
  per the ARCHITECTURE.md procedure.
- Quoted heredocs to sinks are blanked by the existing `strip_inert_spans`.
  Heredocs into `bash` still deny, as do `cat <<'EOF' | bash` and `bash <<<`.
- The redirect interaction that DOES bite is M2 (`2>&1`, `>&2`, `&>`).

## Q4: test quality

- The flipped assertions are what the behaviour change requires and are not
  weakened: `test_matches_comment_mentioning_git_returns_false` and the
  `echo` → `bash -c` rows in `test_blocks_all_creation_variants`.
- Removing both exemptions from the prose guard STRENGTHENS coverage, because
  every `_NON_EXECUTING_TEXT` row now applies to these two guards.
- The `bash -c` acceptance commands do still exercise the deny. Every one is
  denied in-process on the branch.
- The problems are M3 (they now execute) and M4 (the teeth test is hollow).
- The deny-side test list misses every M1/M2 shape. It has only `| bash` and
  `| sh`, so the denylist design was never challenged.

## Q5: interaction with main (N245)

`git merge-tree --write-tree main origin/worktree-n241-stash` is clean
(tree b2c14725). Since the merge base, main touched only `git_commit_parsing.py`
of the files involved. I exported the merged tree and re-ran the full probe:
verdicts are identical to the branch's. The targeted tests on the merged tree
(new tests, git_stash, destructive_git, sensitive_content, git_commit_parsing,
shell_segmentation) gave 1213 passed. The only errors were 26
prose-integration setup errors, caused by `.claude/` config not being in the
exported tree. That is an environment artefact; the same file passed on the
branch checkout.

## Positive observations

- N200 is fixed in the right way: per-segment judgement after narrowing, so a
  `bash -c` body is split too.
- The fail-closed defaults are sound: an unreadable segment, an expansion in a
  data head, or a non-literal `-c` body is left as written.
- The N85 regex fix is minimal, and its comment explains the bash rule.
- Gh prose blanking resolves words first, so a substituting `-b "$(…)"` is
  never blanked (verified).
