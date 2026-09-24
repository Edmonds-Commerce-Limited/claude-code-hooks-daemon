# Plan 00464 review: security and code (Opus 5.5)

- **Reviewed head**: `bb74b351` on `worktree-plan-464-commit-gate-repo`. The diff is `main...bb74b351`, with merge base `4583ddee`.
- **Later commits**: `8062f244` ("resolver seam for same-command staging") landed while this review ran. It is NOT reviewed.
- **Reading at the pinned commit**: every probe below was re-run against the `bb74b351` blobs. They were imported in memory from `git show`, not from the moving working tree.
- **Line numbers** are at `bb74b351`.
- **Method**: I read the code. Then I probed live with `resolve_git_targets` and `SensitiveContentHandler._compute_scan`, against the real main checkout and this worktree (payload `cwd=/workspace`).
- **Tests**: I ran only the targeted tests, `tests/unit/utils/test_git_command_target.py` and `tests/unit/handlers/pre_tool_use/test_commit_gates_judge_the_command_checkout.py`. All 128 passed.

**Counts: 0 blocker, 6 major, 13 minor.**

## What holds up

- **Duplication is gone.** The three byte-identical `_is_foreign_repo` copies in `plan_qa_commit_gate`, `docs_qa_commit_gate` and `staged_lint_gate` are removed, and so is `sensitive_content._commit_repo_root`. Two copies remain, in `post_tool_use/merge_qa_report.py` and `daemon_sync_after_merge.py`, and they are out of scope (see m9).
- **The fail-closed wiring is right for each gate**:
  - `plan_qa` denies in `block` mode (`plan_qa_commit_gate.py:125`).
  - `docs_qa` denies when the gate mode or any `check_modes` entry is `block`.
  - `staged_lint` denies in `block` mode.
  - `remote_docs` always denies (`remote_docs_commit_gate.py:127`).
  - `guard_config` gives an advisory, which is correct for a gate that only reports.
  - `sensitive_content` denies under the new rule, with the reasons redacted.
- **These resolve correctly**:
  - literal `cd`, `cd a; cd b`, `cd -`, `pushd >/dev/null`;
  - stacked `git -C a -C b`, `\git`, `/usr/bin/git`, `command git`, `exec git`, `time git`;
  - `env GIT_DIR=… GIT_WORK_TREE=…`, and `--git-dir`/`--work-tree` in both the `=` and the separate spellings;
  - `export GIT_DIR=…` (unresolved), `env -C`/`--chdir` (unresolved), `cd "$WT"` and `cd ~/x` (unresolved).
- **Merge intake parsing is sound.** `merge_intake` never lets a value or a `-`-prefixed word become a revision. So there is no way to inject an argument into `git diff`. `--continue` scans the index, and `--abort`/`--quit` scan nothing.
- **Exclusion anchoring is right.** Judging a worktree's paths against the PROJECT root (`_anchor`) is correct. Without it, a `untracked/**` exclusion would have exempted every worktree path.

## Findings

### Major

**M1. A `cd` the resolver does not see at a stage head is dropped silently. The commit is then judged against the starting checkout, and it is not failed closed.**
`utils/git_command_target.py:200-208`, `:406-411`.

`git` is found in ANY word position of a stage. Navigation is applied only when `cd`/`pushd`/`popd` is the head word after `builtin`/`command`. Every probe below returned `roots=['/workspace'], unresolved=0`, while the commit really runs in the worktree:

- `out=$(cd $WT && git commit -m x)` and `echo $(cd $WT && git commit -m x)`. `_strip_grouping` only strips a segment that STARTS with `$(`.
- `if cd $WT; then git commit -m x; fi`
- `{ cd $WT; git commit -m x; }`
- `for d in $WT; do cd $d; git commit -m x; done`. The `$d` expansion is never examined, so this does not even fail closed.
- `! cd $WT; git commit`, and `sleep 0 & cd $WT && git commit`. `&` is not a chain separator.

**Failure:** a worktree agent commits a staged secret term with `if cd /…/wt; then git commit -m x; fi`. The sensitive-content scan reads main's index, and the term reaches history. This is the fail-open the plan exists to close. It also contradicts `CLAUDE/Security/AsymmetricSiblingProtection.md:478` ("fails CLOSED on … `$(...)`") and the ticked criterion "No blocking gate silently skips a commit it cannot place".

**Fix:**

- Add the shell keywords `if then elif else do while until ! { time` to the transparent head prefixes.
- Treat a word before `$(` (as in `x=$(` or `echo $(`) as opening a subshell.
- Fallback that keeps the gate closed: if any word in a stage reduces (via `command_word`) to `cd`/`pushd`/`popd` anywhere OTHER than a recognised head, set `shell.where` to UNRESOLVED instead of ignoring it.
- Add a test per shape.

**M2. A conditional `cd` is applied as if it always runs.**
`utils/git_command_target.py:197`. `split_unquoted(text, _CHAIN_SEPARATORS)` throws away WHICH separator joined each segment.

- `cd $WT || cd /workspace; git commit` resolves to `/workspace`. The commit really runs in `$WT`, whenever `$WT` exists.
- `false && cd $WT; git commit` resolves to `$WT`. The commit really runs in main, so main's staged content is scanned against the worktree's index and never read.

**Failure:** a fallback idiom such as `cd /wt 2>/dev/null || cd /workspace; git commit` makes every gate judge the wrong checkout.

**Fix:**

- Keep the separators.
- A navigation reached through `||`, or through `&&` after a command that is not a navigation, gives two candidate directories (before and after).
- Judge both when both are this project's checkouts, as the plan's Goals allow. Otherwise mark it UNRESOLVED.

**M3. The merge scan passes, unscanned, any merge whose incoming side it cannot compute.**
`handlers/pre_tool_use/sensitive_content.py:486-503` (`_merge_diffs`), `:1011` and `:1077` (a git failure is logged at debug level and gives nothing), and `utils/git_commit_parsing.py:281-311`.

Probed on `bb74b351` (content haystacks / unplaced):

| Command                                       | Content | Unplaced | Normal case |
| --------------------------------------------- | ------- | -------- | ----------- |
| `git merge --no-ff <branch>`                  | 25      | 0        | yes         |
| `BR=<branch>; git merge --no-ff "$BR"`        | 0       | 0        | no          |
| `git merge` (merges `@{upstream}` by default) | 0       | 0        | no          |
| `git merge $(git rev-parse <branch>)`         | 0       | 0        | no          |

Also silent:

- `--allow-unrelated-histories`: `HEAD...rev` has no merge base, so the diff fails.
- A large range whose `git diff` passes the 5 s `Timeout.GIT_CONTEXT`: `run_git` returns 127.

The fail-closed contract was applied to the DIRECTORY only, never to the revision.

**Fix:**

- A revision word containing a shell-expansion character is unplaced. Apply the same `_expanded` test the resolver uses for directories.
- No revision and no `--continue` means `@{upstream}`, or unplaced.
- For a merge diff, a non-zero git exit means unplaced (deny), not a debug-level log line.

**M4. Merge and tag message files are still read from the payload `cwd`.**
`handlers/pre_tool_use/sensitive_content.py:938`: `bases = [cwd, *(commit targets)]`.

This is the plan's own defect class, left in a sibling surface. Probed:

- `cd $WT && git commit -F <wt-only file>` reads the message file (1 message-file haystack).
- `cd $WT && git merge --no-ff -F <wt-only file> main` reads it 0 times.
- The same holds for `cd $WT && git tag -F <file> t`: `git tag -F` is read only relative to the payload `cwd`, so it is missed the same way.

**Failure:** a term in a worktree-relative merge or tag message reaches history.

**Fix:** build the bases from the directory of EVERY git metadata-writing invocation, not only `commit`. That covers merge, tag and notes. Resolve each of them with `resolve_git_targets`, or add a subcommand-agnostic `find_git_invocations`.

**M5. The docs claim merge coverage that does not exist, and the `git pull` hole is not stated to the user.**

Where the claims appear:

- Release note 14, lines 26-27: rebase/cherry-pick/`git am` commits "first meet the scan" at a merge.
- `docs/guides/HANDLER_REFERENCE.md:1598-1600`: "a merge is where they all reach the default branch".
- `CLAUDE/core/Worktree.core.md:493`: "wherever those lines were first committed".

What goes uncovered:

- A cherry-pick, rebase, `git am` or `git revert` run ON the receiving branch.
- `git pull`. This includes `git pull . <branch>` and `git pull <path-to-clone>`, which are LOCAL. The JOURNAL's rationale (line 189), "its content is also already on a remote", is false for them.
- A fast-forward with no merge: `git fetch . wt:main`, `git push . wt:main`, `git branch -f main wt`, `git update-ref`.
- `git merge` with no operand (M3).

The `git pull` exclusion appears only in the implementation report and the JOURNAL. No user-facing document says it.

**Fix:**

- List these as uncovered in the release note, `HANDLER_REFERENCE`, `get_claude_md` and the Security doc's blind spots.
- Optionally scan `git pull . <rev>` / `git pull <path> <rev>` through `merge_intake`.
- Optionally treat `fetch|push . <src>:<dst>` refspecs as an intake of `<dst>...<src>`.

**M6. The rule "`git -C <missing>` means nowhere" drops real commits, and the resolver misplaces commands that re-root git.**
`utils/git_command_target.py:507`, `:245`.

- `echo $WT | xargs -I% git -C % commit -m x` gives `roots=[], unresolved=0`, while the matcher is True. Every gate passes it without judging it. `%` is not in `_EXPANDED_ANYWHERE`, so `/workspace/%` is "absent" and git is assumed never to start.
- `find $WT -maxdepth 0 -execdir git commit -m x \;` gives `/workspace`.
- `sudo -D <dir> git commit` gives `cwd`.
- `git worktree add X … && git -C X commit` gives nowhere. This last case is known and belongs to 00465.

Together these falsify the same ticked success criterion as M1.

**Fix:**

- `git` reached as an argument of `xargs`, `find -exec`/`-execdir`, `parallel`, or `sudo -D`/`--chdir` is UNRESOLVED.
- Restrict the "nowhere" answer to a `git` at a command head.

### Minor

**m1. `(cd X) && git commit` is a false deny.**
`git_command_target.py:310-347`. A subshell balanced within one segment is not stripped, so the operand becomes `X)` and is "not a directory yet".
Fix: strip the balanced wrapping parentheses, and do not let the navigation persist.

**m2. `..` is resolved by text, but git resolves it on disk.**
`:394`. `normpath` resolves `link/..` lexically, but `git -C` and `cd -P` use a physical `chdir`. A planted symlink (`git -C untracked/l/.. commit`, with `l` pointing into a worktree) is judged against the lexical parent.
Fix: use `os.path.realpath` for `git -C` and `cd -P`.

**m3. Some ways of setting `GIT_DIR` are missed.**
`:463`. `builtin export GIT_DIR=… GIT_WORK_TREE=…; git commit` resolves to `cwd`, because `exporting` checks `words[0]` before the transparent prefixes. `source env.sh` or `. env.sh` setting `GIT_DIR` is invisible.
Fix: use `words[_head_index(words)]`, and document `source` as a blind spot.

**m4. Any `rev-parse` failure is read as "not a checkout".**
`_identity` (`:285-294`) treats a timeout or a `safe.directory` "dubious ownership" error the same way, and the invocation is dropped (`:245`). If the project's OWN identity fails (`:233`), every target has `in_project=False`, and plan QA, docs QA, lint and remote-docs judge nothing.
Fix: only git's "not a git repository" means not a checkout. Any other failure is UNRESOLVED.

**m5. `R-SENSITIVE-UNPLACED-GIT-WRITE` fires even when the scanner has nothing to find.**
`sensitive_content.py:1265` (and `matches` at `:771`). It fires with no `public_patterns` and an empty or missing word list, which the docs call "silently inert". A client project gets a deny from a scanner that could not have found anything.
Fix: deny an unplaced commit only when at least one pattern or term is loaded.

**m6. The merge bounds are per diff, not per command.**

- Each `_Diff` gets its own 4 MiB budget (`sensitive_content.py:193` and `_scan_staged_paths`). An octopus merge of N heads, or a commit plus a merge in one command, can hold N×4 MiB.
- Standing down on a big merge is logged only, so a long-lived branch is scanned for its first 4 MiB and then passed. The documented "a commit past 4 MiB in total" does not describe merges.

Fix: one byte budget across `_bash_scan`, and document the merge bound.

**m7. Two small merge-parsing gaps.**

- `merge_intake` lacks `--cleanup` in `_MERGE_LONG_FLAGS_WITH_VALUE` (`git_commit_parsing.py:110`), so `--cleanup scissors` makes `scissors` a revision. That is harmless, just a failed diff.
- `-s ours` is scanned although nothing comes in, which can falsely deny.

Fix: add `--cleanup`; treat `-s ours` / `--strategy=ours` as an empty intake.

**m8. A merge deny is labelled "staged content of <path>".**
`sensitive_content.py:1107`. The label is wrong for merge intake.
Fix: carry a subject prefix on `_Diff`, such as "incoming content of".

**m9. A dangling cross-reference, and two copies left.**
`merge_qa_report.py:270` still says "Mirrors `staged_lint_gate._is_foreign_repo`", which no longer exists. `daemon_sync_after_merge.py:187` mirrors `merge_qa_report`: two copies of the old `cwd` logic remain. The follow-up that moves four more handlers should delete both and fix the docstring.

**m10. Git aliases and `sh -c` are invisible, and only half of that is documented.**
`git ci`, `git -c alias.x=commit x`, `bash -c`/`sh -c` and `eval` are seen by no matcher. The `bash -c` part is recorded only in the implementation report; aliases are recorded nowhere.
Fix: add both to the Security blind spots and the release note. Optionally resolve `alias.<sub>` with `git config --get` in the target directory.

**m11. Each commit costs 12-15 extra git subprocesses.**
Each of the six gates calls `resolve_git_targets` on its own, and `sensitive_content` calls it for both commit and merge. That is one `rev-parse` for the project plus one per invocation, each time.
Fix: memoise per `(command, cwd, subcommand)` for one dispatch.

**m12. The payload `cwd` is trusted as the shell's starting directory.**
For a bare `git commit` after a `cd` made in an EARLIER Bash call, a harness that keeps the shell's directory but reports a stale `cwd` would still be judged against main. The plan saw a stale `cwd` for in-process teammates.
Fix: check this in Task 2.2's live check, and state the assumption in `Worktree.core.md`.

**m13. The class test finds gates by source text.**
It enumerates commit gates by string fragments (`_COMMIT_DETECTORS`). A new gate that detects a commit via `git_subcommand_index(...) == COMMIT_SUBCOMMAND`, without those fragments, is not enumerated. The `reaches` rows also prove only that a gate calls the resolver, which the report acknowledges.
Fix: enumerate by behaviour. Instantiate every PreToolUse handler, send it a canonical `git commit` payload, and require each one whose `matches()` is True to be in the matrix.

## Suggested priority

1. M1 and M2: the resolver's control-flow model. One change can cover both: keep separators, add keywords, and make an unrecognised `cd` UNRESOLVED.
2. M3 and M6: fail closed on revisions and on commands that re-root git.
3. M4: message-file bases.
4. M5: docs.

m5 is worth doing before release, because it is a client-visible false deny.
