# Plan 00464 security re-review (Opus 5.5)

- **Reviewed head**: `69a094d8` on `worktree-plan-464-commit-gate-repo`. It is `b4597938` plus one test-only commit, and the working tree was clean.
- **First review**: `260924-plan464-review-opus-5-5.md` (6 major, 13 minor).
- **Method**: I read the code. I then drove `SensitiveContentHandler.matches`/`handle` and `StagedLintGateHandler` against real temporary git repos, each with a main checkout and a linked worktree, using a synthetic word-list term. Every probe that returned ALLOW was then **run for real with bash**, and the term was confirmed in `git log --all -p` (or in a tag). Regression claims were checked by running the same probe under main's `src/`.
- **Probe scripts**: `untracked/scratch/probe_464r2_{harness,a..i,perf}.py`, with outputs in `probe_464r2_*.out`.
- **Tests**: I ran only the targeted suites: `test_shell_lexer`, `test_git_command_target`, `test_git_commit_parsing`, `test_commit_gates_judge_the_command_checkout` and `test_sensitive_content_revision_scan`. **626 passed.**

**Counts: 1 blocker, 3 major, 8 minor, 5 nits.**

## 1. First-review findings: verification

| ID  | Status      | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| --- | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| M1  | verified    | Resolver probes (probe A/H) are all right. `x=$(cd WT && git commit)`, `echo $(…)`, backticks and `time (cd WT && …)` are placed in WT. `if cd`, `{ cd; }`, `for d in $WT; do cd $d; …`, `! cd` and a function body are unresolved. `sleep 0 & cd WT && git commit` is placed in WT. One variant is still hidden, but the cause is the front-door detector, not the resolver: the quoted `echo "$(cd WT && git commit)"`. It is filed as S2. |
| M2  | verified    | `cd A \|\| cd B; git commit` and `false && cd WT; git commit` are both unresolved and DENIED. The reason text for the first is misleading (N1).                                                                                                                                                                                                                                                                                              |
| M3  | verified    | Each of these is DENIED as unread: `BR=…; git merge "$BR"`, `git merge $(git rev-parse …)`, and a bare `git merge` with no upstream. `--allow-unrelated-histories` is scanned and denied on the term.                                                                                                                                                                                                                                        |
| M4  | verified    | `cd WT && git merge -F <wt file>` and `cd WT && git tag -a -F <wt file>` both read the worktree file and DENY.                                                                                                                                                                                                                                                                                                                               |
| M5  | verified    | `git pull . b`, `git fetch . a:b` and `git push . a:b` are scanned and DENY. `AsymmetricSiblingProtection.md:517-545` now separates the three kinds of route: judged, denied, and outside the contract. S10 questions where that boundary sits.                                                                                                                                                                                              |
| M6  | **partial** | `xargs`, `find -execdir` and `sudo -D` are now unresolved. But `git -C <missing>` still means "nowhere" whenever the directory is created EARLIER in the same command. git then discovers the enclosing repository and commits its index unscanned. Verified leak: S6.                                                                                                                                                                       |
| m1  | verified    | `(cd WT) && git commit` is placed in the start directory.                                                                                                                                                                                                                                                                                                                                                                                    |
| m2  | verified    | Code only. `realpath` is used for `git -C` (`git_command_target.py:1114`) and `cd -P` (`:975`).                                                                                                                                                                                                                                                                                                                                              |
| m3  | verified    | `builtin export` goes through `_head_index` (`:1049-1060`), and `source`/`.`/`eval` are unresolved. New gaps in the same area are S5.                                                                                                                                                                                                                                                                                                        |
| m4  | verified    | Only "not a git repository" means "not a checkout" (`:908-912`).                                                                                                                                                                                                                                                                                                                                                                             |
| m5  | verified    | `_armed()` (`sensitive_content.py:1348-1355`) gates every unplaced or unread deny.                                                                                                                                                                                                                                                                                                                                                           |
| m6  | verified    | One `_Budget` is shared per Bash call, and the merge bound is documented. A stand-down is still a silent pass (S11).                                                                                                                                                                                                                                                                                                                         |
| m7  | verified    | `-s ours` allows, and `--cleanup scissors` no longer turns its value into a revision.                                                                                                                                                                                                                                                                                                                                                        |
| m8  | verified    | Merge content is labelled "incoming".                                                                                                                                                                                                                                                                                                                                                                                                        |
| m9  | verified    | `grep` finds no `_is_foreign_repo` in `src/`, and no stale "Mirrors" docstring.                                                                                                                                                                                                                                                                                                                                                              |
| m10 | verified    | Aliases, `bash -c` and earlier-call state are listed in `AsymmetricSiblingProtection.md:503-507`.                                                                                                                                                                                                                                                                                                                                            |
| m11 | verified    | Identities are memoised for 2 s. Each gate still re-walks the command, which is pure parsing. `_bash_scan` now walks EVERY Bash command twice, whether or not it runs git (S8).                                                                                                                                                                                                                                                              |
| m12 | partial     | Documented. The live check belongs to Task 2.2 and has not been run.                                                                                                                                                                                                                                                                                                                                                                         |
| m13 | verified    | `TestEveryCommitReaderIsFoundByWhatItDoes` (test file `:318`) enumerates handlers by behaviour. It cannot catch S1 or S2, because it sends one canonical `git commit` string.                                                                                                                                                                                                                                                                |

## 2. Findings

### Blocker

**S1. When the walk finds no git command, every commit gate passes the commit unjudged. This is a regression against main.**

Where:

- `sensitive_content.py:1487-1490`. Also, identically, `plan_qa_commit_gate.py:116`, `docs_qa_commit_gate.py:113`, `staged_lint_gate.py:171`, `remote_docs_commit_gate.py:120` and `guard_config_commit_gate.py:168`, each followed by `resolve_git_targets`.
- The lexer causes: `shell_lexer.py:124-125`, `:211-217` and `:272`.

Each gate decides "this is a commit" with its own token or regex detector. It then asks the lexer-based resolver where the commit runs. When the lexer does not see the commit, the resolver returns no targets AND no unresolved reasons, and the gate judges nothing. Main judged the payload `cwd` in the same situation, so it denied.

The probe stages a term in main and runs the command from main (`probe_464r2_b.py`):

| Command                                                      | main src | branch               |
| ------------------------------------------------------------ | -------- | -------------------- |
| `git commit -m x`                                            | DENY     | DENY                 |
| `cat <<'EOF' \| bash` / `git commit -m x` / `EOF`            | DENY     | **ALLOW (no match)** |
| `tee /dev/null <<'EOF' \| sh` / `git commit -m x` / `EOF`    | DENY     | **ALLOW**            |
| `echo $'\''; git commit -m 'x'`                              | DENY     | **ALLOW**            |
| `echo 'a'"b"$'c\'d' && git commit -m x`                      | DENY     | **ALLOW**            |
| `cat <<"E O F" >/dev/null` / … / `E O F` / `git commit -m x` | DENY     | **ALLOW**            |

`staged_lint_gate` in block mode, with a broken `.py` staged (`probe_464r2_f.py`): the pipe-to-bash case is DENY on main and **ALLOW** on the branch. The other four gates share the same empty-targets path by reading.

The lexer causes:

1. **ANSI-C quoting is not recognised.** In `$'…\'…'` the escaped quote closes the lexer's single-quoted span early (`:124-125`, `_single_quoted_end`). Everything after it is then mis-quoted, and the git command disappears into a "quoted" word.
2. **A quoted heredoc delimiter containing a blank is read only up to the blank** (`:211-217`). The body never finds its terminator and swallows the rest of the command. The module docstring (`:22-23`) says unreadable text "over-reads rather than hides"; for a heredoc body, over-reading IS hiding.
3. **`_bodies` asks only whether the heredoc's RECEIVER is a data sink** (`:272`). A quoted body fed to `cat`/`tee` and piped on to `bash`/`sh` is dropped as data. `pipe_blocker`'s own guidance says the opposite, and says why: "every stage the body is piped on to".
4. The same class covers `$(cat <<'EOF'` / `git commit …` / `EOF` / `)` in command position, which is not probed live.

The resolver's docstring promises the opposite: "fail CLOSED whenever the walk cannot be CERTAIN where git runs." The branch's own `merge_to_main_approval._merge_placements` (`:334`) already has the right shape, `placements or [Placement(start)]`. None of the commit gates adopted it.

**Fix:**

- **Every gate.** If the gate's detector matched a subcommand and `resolve_git_targets` returns neither a target nor an unresolved reason for it, add an unresolved reason: "the command's `git commit` could not be located". Put this in `resolve_git_targets` behind a flag, or in a small shared helper, rather than in six places.
- **Lexer, three changes:**
  - Read `$'…'` with backslash escapes.
  - Read a quoted delimiter up to its closing quote.
  - Treat a quoted body as `HEREDOC_BODY` when any later pipeline stage is not a data sink.
- **Tests.** Add a differential test over a command corpus: every command a gate's detector calls a commit must yield at least one target or one unresolved reason. That test catches this class and S2 together.

### Major

**S2. The detectors that open the gates are whitespace or shlex tokenisers. They miss commits that the resolver would place correctly.**

Where: `sensitive_content.py:596-628` (`_is_git_commit`, `_invokes_git`), `:1801-1831` (`_writes_git_metadata`, `command.split()`), and the five gate matchers listed in S1.

With a term staged in the worktree and `cwd` = main (probe A), each of these is **ALLOW (no match)**, although the resolver places each one in WT:

- `cd WT&&git commit -m x`
- `cd WT;git commit -m x`
- `(cd WT;git commit -m x)`
- `echo "$(cd WT && git commit -m x)"`

The in-place `true;git commit -m x` and `git add -A;git commit -m x` are also invisible to `sensitive_content`. `staged_lint`'s regex does catch them.

This is **not a regression**: main behaves the same. It is still the front door the whole resolver sits behind. Five different commit detectors now stand in front of one resolver, and every disagreement between them is a silent pass.

**Fix:** make the lexer walk the detector. A commit is present if `find_git_invocations(command, start, COMMIT_SUBCOMMAND)` is non-empty, OR the legacy token detector fires. In the second case only, S1's rule applies. Do the same for `merge`, `tag`, `notes`, `commit-tree` and the other routes. `_writes_git_metadata` should also come from `find_git_commands`, not `command.split()`.

**S3. Message sources that the scan never reads.** Each case below is **ALLOW, and run for real the term is in history** (probes C and I):

| Command                                                     | Why it is missed                                                                      |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `git commit -m "$(cat untracked/notes.txt)"`                | a computed `-m` value is never read or refused                                        |
| `M=$(cat notes); git commit -m "$M"`                        | same                                                                                  |
| `git tag -a v9 -m "$(cat notes)"`                           | same                                                                                  |
| `git commit -Funtracked/notes.txt`                          | `MESSAGE_FILE_PATTERN` (`message_files.py:36-38`) needs whitespace or `=` after `-F`  |
| `git commit -aF notes`, `-sF notes`, `git tag -aF notes t1` | a short cluster ending in `F` is never matched                                        |
| `cat notes \| git commit -F /dev/stdin`                     | `path_is_file` is False for a pipe, so it is skipped silently (`message_files.py:97`) |
| `git commit -F <(cat notes)`                                | the path `<(cat` does not exist, so it is skipped                                     |
| `exec 3<notes; git commit -F - <&3`                         | `<&3` is read as a file named `&3`                                                    |
| `cp notes msg && git commit -F msg`                         | the file does not exist before the command runs, so it is skipped as "git's failure"  |

This is inconsistent with the branch's own stdin rule. That rule denies `-F - <<< "$(…)"` and a piped `-F -` because "the shell computes it". The equivalents above pass.

**Fix:**

- Read message sources from `find_git_commands(...).options` through `_route_words`, which already parses clusters and attached values. Drop the regex.
- A `-m`/`--message` value that contains `$` or a backtick outside single quotes is unread, so deny it. Keep an exemption for the literal `"$(cat <<'EOF' … EOF)"` idiom, whose body is in the command text.
- A `-F` target is unread in these cases:
  - it is not a regular file;
  - it is under `/dev` or `/proc`;
  - it is a process substitution;
  - it is missing while any command precedes the git.

**S4. `git commit --pathspec-from-file=<f>` records working-tree content that is never scanned.**

Where: `git_commit_parsing.py:1040-1080` and `sensitive_content.py:660-673`.

This is the exact sibling of this branch's own pathspec fix. `extract_commit_pathspecs` treats `--pathspec-from-file=f` as a boolean, so only `--cached` is diffed.

Probe C, with the term as an UNSTAGED edit to tracked `tracked.txt` and `list.txt` naming it: **ALLOW**, and the term is committed. The control, `git commit -m x tracked.txt`, is DENIED.

**Fix:** when `--pathspec-from-file` is present (either spelling, and with `--pathspec-file-nul`), diff HEAD for every path. Reading a literal list file and narrowing is optional. Add a class test for the pathspec arms: every option that makes a commit record working-tree content must produce a HEAD diff.

### Minor

**S5. The walk does not see some ways of setting the repository environment.**

Where: `git_command_target.py:1049-1060` (`_repository_assignments` requires `NAME=`).

Each case is **ALLOW, and leaks for real** (probe C):

- `printf -v GIT_DIR %s <main>/.git/worktrees/wt; export GIT_DIR; git commit -m x` commits the WORKTREE index from main.
- `for GIT_DIR in …; do export GIT_DIR; done; git commit -m x`
- `read -r GIT_INDEX_FILE <<< …; export GIT_INDEX_FILE; git commit -m x`

`export NAME` with no `=` is not recognised.

**Fix:** any word equal to a repository variable name after an exporting builtin, and any `printf -v`, `read`, `mapfile` or `declare -n` targeting one, sets `shell.environment`.

**S6. `git -C <dir>` still means "nowhere" when an earlier command creates `<dir>`.** This is M6 carried over.

Where: `git_command_target.py:976-977` and `:831-832` (the silent `continue`).

Probe: `mkdir -p untracked/newdir && git -C untracked/newdir commit -m x` is **ALLOW, and leaks**. git discovers main from the new subdirectory and commits main's staged term.

The docstring's premise, "git refuses to start there", holds only when nothing runs before git.

**Fix:** "nowhere" only for a git that is the first command of the whole call. Anything else is unresolved. The same applies to `identity is None` (`:836-838`) when an earlier command could run `git init`/`clone`/`worktree add`. The 00465 `preceding` seam already has the data to decide this.

**S7. The `git am` route reads only transfer-encoded text.**

Where: `sensitive_content.py:790-806`.

A mailbox with `Content-Transfer-Encoding: base64` or `quoted-printable` is **ALLOW, and `git am` commits the decoded term** (probe G). RFC 2047-encoded headers are missed the same way.

**Fix:** decode with the `email` package, or run `git mailsplit` + `git mailinfo` into a temp dir. Failing that, deny any mailbox whose encoding is not 7bit/8bit as unread.

**S8. Crafted commands can crash or hang the walk, and a crash fails open in client projects.** Measured in `probe_464r2_perf.out`:

- **RecursionError** from `find_git_invocations` at 400 nested `$(` (a 1.2 KB command).
- **RecursionError from `lex` itself** at 1000 unclosed `echo "$(`. That is 8 KB, caused by the mutual recursion between `_double_quoted_end` and `_matching_paren` (`shell_lexer.py:323-367`).
- **Quadratic time on nested `(`**: 8,000 takes 6.2 s and 32,000 (a 64 KB command) takes **129 s**. The cause is `_effective_where`/`_conditional` scanning `self._scopes` on every command (`git_command_target.py:692-697`, `:734`).
- `GitTarget.preceding` slices are O(n²) in memory (`:849`).
- `_bash_scan` runs `find_git_commands` (`:1463`) and a full two-pass `_carries_content` walk (`:1506`) on EVERY Bash command, git or not.

Here `strict_mode: true` turns a crash into a deny. The default is `strict_mode: False` (`config/models.py:1666-1669`), and `chain.py:512-516` then logs the crash and CONTINUES. So in a client project, every gate on the resolver is skipped for that command.

**Fix:**

- Walk iteratively, or cap the nesting depth, and treat "too deep" as unresolved.
- Keep counters of open non-subshell scopes and function scopes instead of scanning.
- Skip both walks when the lexed command has no `git` word.

**S9. Directory changes the walk misplaces rather than unresolves.** Each case is **ALLOW, and leaks for real** (probes C and G):

- `CDPATH=<wt>; cd sub && cd .. && git commit -m x`. bash follows `CDPATH` into the worktree; the walk resolves `sub` against the starting directory.
- `c=cd; $c <wt>; git commit -m x`. A computed head word is assumed to have no effect (`_shell_effect`, `:759-773`).
- `for ((i=0; i<0; i++)); do cd <main-side>; done; git commit -m x`. The `((` opens two "subshell" scopes, and closing them pops the `for` block. The body's `cd` is then applied as certain, although the loop never runs.

**Fix:**

- Any assignment to `CDPATH` in the command makes a later relative `cd` unresolved. A `CDPATH` already in the session is a blind spot to document.
- A shell-expanded head word makes the directory unresolved.
- Treat `for ((` as a header opener, so the block is not popped.

**S10. The merge backstop is not applied to the other routes that bring a branch's commits in.**

`git rebase <branch>` run on the receiving branch, `git cherry-pick A..B` and `git reset --hard <branch>` all bring in commits that "never passed the commit gate". That is the stated reason for scanning `git merge` (`AsymmetricSiblingProtection.md:542-545`), yet the doc (`:533-540`) files these as "outside the contract".

**Fix:** either scan them the way `ref_intake` scans `fetch .`, or reword the rationale so it does not claim a property the boundary does not have.

**S11. Hitting the byte budget is a silent pass.**

Where: `sensitive_content.py:1712-1722`, `:1787-1797`, `:865-867`.

A merge whose incoming side is over 4 MiB is scanned for its first 4 MiB and then passed, with an INFO log line only. A patch over the budget passes the same way. It is documented, but the user never sees it.

**Fix:** when armed, add an advisory naming the first unjudged path, or treat the rest as unjudged for merges, where history is the stake.

**S12. Sibling handlers still keep their own directory walkers, and one of them is wrong the same way.** This review hit it directly.

`project_containment._resolve_against_cwd` (`project_containment.py:303-339`) joins a relative redirect target to the payload `cwd` and ignores `cd`. `cd $D/m && … > ../other/f` was denied as a write to `/workspace/../other`, which is a false deny; the reverse shape is a false allow.

`reference_repo_freshness.py:150`/`:323` and `secret_file_matching.py:1043` each keep a private `cd` walker.

**Fix:** move them onto `find_command_directories`/`_walk`. Record `project_containment` in the niggles ledger as an instance of this plan's defect class.

### Nits

- **N1.** `cd A || cd B; git commit` gives the reason "runs only if the commands before it in its chain succeed". That is the wrong wording for `||`: the `uncertain_end` text (`git_command_target.py:633-636`) overwrites the correct "follows `||`" reason.
- **N2.** A quoted heredoc fed to `ssh host` is walked as LOCAL shell (`shell_lexer.py:275-276`). A `cd /x && git commit` in a remote script is placed, or denied, locally.
- **N3.** `editor_is_no_op` counts a non-exported `GIT_EDITOR=true;` as exported (`git_command_target.py:418-420`). Impact is low: git never sees it, and the real editor has no terminal.
- **N4.** Duplication and magic values:
  - duplicated constants: `_PIPES`/`_PIPE_OPERATORS` (`git_command_target.py:86`, `:107`) and `_OPEN_PAREN`/`_SUBSHELL` (`:88`, `:146`);
  - `_unquote` (`:776`) is `git_commit_parsing._unquote_word` (`:957`);
  - two `_REDIRECTION` regexes with different grammars (`git_command_target.py:169`, `git_commit_parsing.py:178`);
  - the literals `"$("` in `shell_lexer.py:168`, `:361` and `:382` despite `_SUBSTITUTION_OPENERS`;
  - the literal `"="` in `git_commit_parsing.py:974`, `:1003` and `:995` despite `_VALUE_SEPARATOR`;
  - `_route_file` swallows `FileNotFoundError` with no log (`sensitive_content.py:869-870`).
- **N5.** The lexer docstring (`shell_lexer.py:22-23`) and the Security doc (`:484-499`, "Everything else is UNRESOLVED") state a guarantee that S1 falsifies. Correct both when S1 is fixed.

## 3. False denies on this project's workflow

Nothing was staged, so every DENY here would be false (probe E). Each commit-message shape was run with the last **400 real commit messages** of `/workspace`:

| Shape                                          | Denies |
| ---------------------------------------------- | ------ |
| `git commit -m "$(cat <<'EOF' … EOF)"` in main | 0      |
| the same after `cd <wt> &&`                    | 0      |
| the same with `git -C <wt>`                    | 0      |
| `git commit -F - <<'EOF'`                      | 0      |

These single commands were also all allowed:

- `git merge --no-ff wt-branch -m '…'` (flags in either order)
- `cd <wt> && git merge --no-ff main -m …`, the integration-worktree shape
- `GIT_EDITOR=true git merge --continue`
- `git commit --no-edit`
- `git add -A && git commit`
- `git commit -am`
- a commit followed by `git log` or `git branch -d`
- `cd untracked && git commit`
- a `for d in …; do git -C $d status; done` loop before a commit

`mkplan.bash` runs as a script, so no gate sees its git calls. The only deny was the intended one: `WT=…; cd "$WT" && git commit`.

## 4. Code quality

**Parsers in `src/` that do shell work.** They should converge onto `shell_lexer`/`_walk`:

- `shell_segmentation` (`split_unquoted`, `strip_inert_spans`, `command_word`) and `command_evasion` (`git_subcommand_index`, `normalise_line_continuations`). These are the lower layer, and they stay.
- **Commit and merge detectors.** There are five, and they should converge (S1, S2):
  - `sensitive_content._is_git_commit`/`_invokes_git`/`_writes_git_metadata` (shlex, `split()`);
  - `git_commit_parsing.is_git_commit`/`tokenise_command` (shlex, "commit anywhere after git");
  - `staged_lint_gate._is_git_commit_command` (regex);
  - `plan_qa`/`docs_qa` `_is_git_commit(_tokenise)`;
  - `guard_config._commit_subcommand_index`.
- **Directory walkers.** These should converge (S12): `reference_repo_freshness` (its own `cd`/`pushd`/`popd`), `secret_file_matching` (a `cd` prefix strip), and `project_containment` (shlex per segment, no `cd`).
- **Other command shapes.** These are separate concerns; converge them opportunistically: `pipe_blocker`, `destructive_git`, `merge_to_main_approval._segment_tokens`/`merge_target`, `merge_scope`, `verification_result_gate`, `worktree_file_copy`, `root_recursion_guard`, `process_probe`, `bash_flags`, and the `core/utils` shlex helpers.
- **The message-file reader.** `message_files.MESSAGE_FILE_PATTERN` is a regex over the raw command, and it should move onto `find_git_commands` (S3).

**Tests.** The RED-first discipline is visible and the suites are behavioural: real repos, and real `matches`/`handle`. What is missing is the whole class this review found. No test covers any of these:

- `$'…'`;
- a heredoc piped to a shell;
- a spaced heredoc delimiter;
- detector/walker disagreement;
- `-F` clusters, `/dev/stdin` or process substitution;
- `--pathspec-from-file`;
- deep nesting.

The class tests enumerate gates, not command shapes. A differential test (S1's fix) plus a timing or depth bound test (S8) would pin the class, not the instances.

## Suggested order

1. **S1** (blocker, a regression) and **S2** are one change: detect with the lexer, and make "detected but not located" unresolved. Add the three lexer fixes.
2. **S3** and **S4**: the message and pathspec sources, read from `find_git_commands` through `_route_words`.
3. **S8**, before this ships to clients with `strict_mode: false`.
4. The rest.
