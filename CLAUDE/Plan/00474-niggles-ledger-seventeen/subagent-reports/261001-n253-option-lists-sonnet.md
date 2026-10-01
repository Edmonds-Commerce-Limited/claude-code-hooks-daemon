# N253: secret_file_guard exemptions read options from closed lists (Sonnet 5.5)

**Branch:** `worktree-n253-open-option-lists`, cut from main at `3473b263a`.

## Before and after

All in `src/claude_code_hooks_daemon/utils/secret_file_matching.py`.

| Exemption                                          | Exempt before                                                                                                                                        | Not exempt now                                                                                                                                                                                                                        |
| -------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| grep pattern-only (`is_grep_pattern_only_mention`) | any unknown option skipped: `--rege=.`, `--regex=.`, `--and=.`, `-y`, `-X`                                                                           | any long option not named in full on the GNU list, any abbreviation, unknown short letters; a long option's value passed as a separate word (`--max-count 3`); `--include`/`--exclude`/`--exclude-dir` values naming a protected file |
| `git rm --cached` (`_is_git_rm_cached`)            | any global option (`-c core.fsmonitor=...`, `--config-env`, `--git-dir`, `--exec-path`), any rm option incl. abbreviations of `--pathspec-from-file` | everything except `-C <dir>` and 7 harmless flags before `rm`; after `rm` only the closed `_GIT_RM_GRAMMAR`; `--cached=x`                                                                                                             |
| encrypted-target git                               | diff-flag denylist: `--verb`, `--patc`, `--ed` abbreviations passed                                                                                  | per-subcommand closed `_OptionGrammar` (add, commit, status, mv, rm, ls-files, check-ignore)                                                                                                                                          |
| consumers (ansible etc.)                           | `--inventory=<key>`, `-i<key>`; `ansible-vault --output x view`                                                                                      | option words (value after `=`, tail of a short option) are judged; a denied subcommand anywhere voids it                                                                                                                              |

`GIT_CONFIG_*=... git rm --cached` and `env GIT_CONFIG_*=... git ...` were already non-exempt (the head word is not `git`); tests now pin that.

## What stays exempt

The documented shapes: `grep id_rsa file`, `-e`, `--regexp[=]`, `-n -i -rn -A 3 -nC2 -2`, `--color=auto`, `--max-count=3`, `--exclude-dir=.git`; `git rm [-r -f -q -n --ignore-unmatch --dry-run --sparse] --cached [--] <path>`, `git -C <dir> [--no-pager ...] rm --cached`; encrypted-target `git add -f`, `status --short/-sb/--porcelain=v2`, `commit -am/-m/--message=`, `mv -f`, `rm`.

## Behaviour change

`git -c core.pager=cat rm --cached <key>` was an explicitly tested exempt shape (the hygiene checker's remedy with a config global). It is now denied by design; the existing test was flipped.

## Tests

- RED before the fix: 100 failures, including through the handler `grep --rege=. .vault-pass`, `grep --and=. .vault-pass`, `git -c core.fsmonitor=x rm --cached .vault-pass`.
- Prefix coverage: every strict prefix of every GNU grep long option (and of the dangerous ones with `=.` and separate forms) is asserted not exempt.
- GREEN: the three secret-guard test files (`test_secret_file_matching.py`, `test_secret_exemptions_reserved_words.py`, `test_secret_file_guard.py`) all pass (1028).
- black (py311), ruff, mypy, pyright, `audit_error_hiding.py` and `check_input_contract.py` on the touched files: see the final run noted in the commit.

## Not verified

- No differential run against real GNU grep, ugrep or git: the closed lists come from GNU grep 3.8's long-option set and my knowledge of git's options, not from running them. The ugrep arity claims (separate-word values) come from the earlier Opus report.
- Other exemptions still open-ended and out of scope: the plain readers in `_ENCRYPTED_TARGET_COMMANDS` (`wc --files0-from=`, `head`, `ls`, `file -f`) take no option parsing at all.
- `-C <dir>` is accepted without checking that the directory's own repo config is benign.
- The daemon was not restarted and no suite beyond the targeted files was run.
