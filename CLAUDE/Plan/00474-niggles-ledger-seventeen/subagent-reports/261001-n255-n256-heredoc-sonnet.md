# N255 and N256 (part 1): heredoc fixes redone against the N101 code (Sonnet 5.5)

Branch `worktree-n255-n256-heredoc`. Python 3.11.2 (the daemon's venv).

## N255: does not reproduce on current main

- **Evidence.** `_expand_glob_token` was run on 3.11.2 over ten token shapes (an over-long component after a wildcard, before one, absolute, relative, after `**`, prose-quoted with spaces), each with and without a hook cwd. None raised ENAMETOOLONG. The commit-message shape (two apostrophes quoting prose that holds `CLAUDE/core/*.core.md` behind a 300-character run) through the handler was allowed.
- **Why.** N101 replaced `Path.glob` with `shell_expansion._GlobWalk`, which reads each lookup itself. `_record` treats ENAMETOOLONG as proof of absence when the component is longer than the filesystem's `PC_NAME_MAX`. A joined path past PATH_MAX is still a deliberate deny (review 8 BLOCKER 1, pinned by existing tests), so I did NOT make every ENAMETOOLONG an absence: that would reopen it.
- **Regression tests added** (all pass on the unchanged source):
  - `tests/unit/utils/test_secret_file_matching.py`: six token shapes through `_expand_glob_token`, and a forced ENAMETOOLONG from `Path.stat` and `Path.lstat` on an over-long name.
  - `tests/unit/handlers/pre_tool_use/test_secret_file_guard_text_fed_heredoc.py`: `TestAGlobBehindAnOverLongNameIsNotAGuardDefect` (the real message shape through `awk 1`, `git commit -F -` and `cat`).

## N256 part 1: reproduced, fixed

- **RED, before the fix** (`untracked/scratch/probe256c.py`, handler `.matches`):
  - a prose mention of a protected name in the body was DENIED for every text-fed shape (`git commit -F -`, `git tag -F -`, `cat`, `tee`, `grep`, `wc`, `sort`, ...);
  - markdown bold walked the tree for non-`DATA_SINKS` readers (`nl`, `fold`, `fmt`, `rev`, `od`, `xxd`, `sha512sum`, `cksum`, `awk`). For `DATA_SINKS` receivers the glob gate already skipped it on main, so those did not walk. I left `nl`/`fold`/... off the list on purpose (see below).
  - New handler tests with the guard call reverted: 11 failed, 27 passed. New unit file: collection ImportError (no `TEXT_READING_SINKS`).
- **GREEN, after:** unit file 68 passed; handler file 38 passed.
- **Change.**
  - `utils/shell_segmentation.py`: `TEXT_READING_SINKS` (cat, tee, sort, uniq, tr, cut, column, head, tail, wc, grep, base64) and `strip_quoted_heredoc_bodies(command, *, text_readers_only=False)`. The default is untouched. In text mode a stage must pass the existing `_stage_is_inert_sink` checks (option allowlists, redirects, fds) AND be a text reader AND carry no `$(`, `<(`, `>(` or backtick. Git qualifies only as `commit`/`tag` with `-F -`, `-F-`, `--file=-` (or `--file -`), no `--pathspec*`, and no unresolved word, after inert global options only. The pipeline check (`_downstream_is_all_data_sinks`) takes the same flag, so `cat <<'EOF' | bash` keeps its body.
  - `handlers/pre_tool_use/secret_file_guard.py`: the Bash route scans `strip_quoted_heredoc_bodies(command, text_readers_only=True)`. Only the body is replaced by a placeholder; the opener line (redirects, command words) and everything after the closer are kept.
- **A receiver that writes a file keeps its body.** The first version blanked `cat > run.sh <<'EOF'` and the existing test `test_heredoc_authoring_a_script_that_expands_to_a_protected_name_still_denies` failed (1 failed, 2586 passed in the targeted run): a body written to a file is a script someone runs later, not text that dies with the command. `_stage_writes_a_file` now withholds the exemption for any redirect that is not an fd duplicate or `/dev/null`/`/dev/stdout`/`/dev/stderr` (including a redirect before the command word), `tee` with any operand, and `sort -o`/`--output`. `&>` is caught on the raw line, because `_receiving_segment` blanks it and would leave its target looking like a `cat` operand. Cost: `cat > notes.md <<'EOF'` prose that names a protected path stays denied, as on main; the lead's brief listed `cat` as a text reader, and this narrows it to `cat` without a file target.
- **Left off `TEXT_READING_SINKS`, with reasons.** `git` except as a stdin message reader (plumbing reads paths and objects), `patch`, `ftp`, `mail`/`mailx`, `xargs`; `jq`/`yq` (can load files by name); `md5sum`/`sha1sum`/`sha256sum` (`-c` opens the files the body names); `less`/`more`/`diff`. The earlier branch's list had `jq`, `yq` and the checksums; I dropped them as the fail-closed direction. They stay denied as before.
- **Still denied (tested at unit and handler level):** `bash <<'EOF'`, `sh -s`, `python3 -`, `cat <<'EOF' | bash`, `tee >(bash)`, `cat <<'EOF' > >(bash)`, `xargs cat`, `git update-index --stdin`, `git cat-file --batch`, `git commit --pathspec-from-file=-` (alone and beside `-F -`), `git commit -m message`, `git -c core.editor=bash commit -F -`, `patch`, `jq`, unquoted `<<EOF` with a substitution, `-m "$(cat <<'EOF' ...)"`. A mention in the command part, in a redirect target, after the closer, or in a second heredoc with its own receiver is still judged.
- **Out of scope, untouched:** the enumeration-cap verdict (TooManyToEnumerateError) and every UNKNOWN verdict.

## Checks

- Targeted tests, all green on the final tree: `tests/unit/utils/test_secret_file_matching.py`, `tests/unit/handlers/pre_tool_use/test_secret_file_guard.py`, `tests/unit/utils/test_secret_exemptions_reserved_words.py`, `tests/unit/handlers/pre_tool_use/test_heredoc_grammar_chain.py`, the two new files, `test_shell_segmentation.py`, `test_shell_segmentation_inert_heads.py`, `test_shell_segmentation_inert_spans.py`, `test_heredoc_operators.py`. Final run: 2606 passed, 1 failed. The failure is `TestAQuotedBraceWordIsNotCounted::test_quoted_brace_words_are_allowed` (the 600-word `echo w0\{a,b} ...` case, no heredoc in it): a `TimeoutError` on the guard's scan deadline while the shared host was loaded. It passes alone (`TestAQuotedBraceWordIsNotCounted`: 7 passed) and passed in the earlier full run; I judge it load-related, not caused by this change.
- ruff, black (py311), mypy, pyright: clean on the touched source. `scripts/qa/audit_error_hiding.py` and `scripts/qa/check_input_contract.py`: exit 0.

## Noticed, not fixed

- `git cat-file --batch` with a body of `HEAD:<protected-at-root>` is allowed: that is ledger N283 (rev:path at the root), not this change. My test uses the plain name instead.

## Not verified

- The full suite (coordinator's gate), and the daemon restart/live behaviour: I did not restart the daemon.
- The earlier branch's 2000-real-commit-message corpus run was not repeated.
