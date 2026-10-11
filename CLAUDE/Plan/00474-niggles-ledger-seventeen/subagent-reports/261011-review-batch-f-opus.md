STOPPING BECAUSE: review complete; verdict and findings below.

# Review: Plan 00474 batch F (N404–N406), branch tip 773d9103b

**Verdict: CHANGES REQUIRED.** N404 and N405 are sound. N406 now lets through several commands that really publish a closing keyword, all of which `main` denies.

The 187 targeted tests pass. The probe is kept at `/workspace/untracked/scratch/review-n404-406/probe.py`, with output in `branch.txt` and `main.txt` alongside it. Run it as `python -I probe.py <src>` against either tree.

## Required changes

### 1. N406 regression: real commits carrying a closing keyword now pass (confidence 90%)

**Location:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/github_auto_close_keywords.py`, `_COMMAND_START` (~L119) and `_without_foreign_heredoc_bodies` (~L133–154)

`main` denies every shape below. The branch allows them all:

- **Inside an `if`:** `if true; then git commit -m 'fixes #3'; fi` and `if git commit -m '…'; then :; fi`. `_COMMAND_START` does not treat `then`, `do`, `else`, `elif`, `if`, `while` or `!` as the start of a command.
- **Behind a shell:** `bash <<'EOF'\ngit commit -m '…'\nEOF` and `cat <<'EOF' | bash …`. `_without_foreign_heredoc_bodies` blanks any body whose opener line is not a git/gh command, including one fed to a shell that runs it. The shared `strip_quoted_heredoc_bodies` deliberately keeps a `bash <<'EOF'` body. This helper also blanks bodies with an unquoted delimiter, whose `$(…)` really runs.
- **Wrapped:** `bash -c "git commit -m '…'"`, `eval "…"`, `nohup git commit`, `timeout 5 git commit`, `/usr/bin/git commit`, `cd x & git commit`, and ``echo `git commit …` ``.

**Fix:**
- Make command positions match the shared segmenter. Either reuse the segment spans from `utils/command_position` (its `command_position_segments` already splits `then git commit …` and `bash <<'EOF'` bodies correctly, but it redacts the message, so take its positions rather than its text), or add `then|do|else|elif|if|while|until|!|&` and `nohup|timeout N|xargs` to `_COMMAND_START`.
- Blank a heredoc body only when its delimiter is quoted AND its receiver is not a shell (`bash`, `sh`, `zsh`, …) AND no later pipe stage is a shell.
- Add the shapes above to `test_real_message_still_denies` (test file ~L183).

This is also a DRY issue: N406 hand-rolls a third copy of "command position" and "heredoc receiver" logic that already exists in `utils/`, and that duplication is what caused the regression.

### 2. Ancestry DENY acceptance tests now run live merge commands (confidence 75%)

**Location:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/ancestry_preserving_merge.py` ~L379–414

`git merge --squash feature-branch` and `gh pr merge --squash|--rebase 123` are only safe if the handler denies them. If the playbook runs where the handler is disabled, in warn mode, or the daemon is down, it squash-merges a real branch or a real PR #123.

**Fix:** use the `destructive_git.py` precedent (~L1165) and wrap them as `bash -n -c 'git merge --squash no-such-branch-acceptance-test'` and `bash -n -c 'gh pr merge --squash 999999999'`. My probe confirms `bash -c '…'` still denies. Removing the echo wrapper was correct; it just needs this replacement.

## Non-blocking

1. **N405 is clean.** All 30 probed ways of actually running a squash or rebase merge still deny, including `bash -c`, `eval`, `xargs`, `env`, `sudo`, `git -C`, subshells, `$( )`, backticks, `cat <<'EOF' | bash`, `if/then` and `for/do`. No action needed.
2. **Existing gap, not a regression:** `git commit -m"`ls`"` (no space after `-m`) is allowed on both `main` and the branch, because `_DOUBLE_QUOTED_MESSAGE_PATTERN` needs whitespace there. Fix: change it to `\s*` and add a test.
3. **Possible new false positive in N406:** an opener line like `cat <<'EOF' > notes.md && git commit -m wip` keeps its body, and that body then sits in the commit segment and gets scanned. Fix: decide whether a body belongs to the commit from the heredoc's own receiver, not from any git token on the line.
4. **Unit-test gap:** `TestMentionsAreDataNotCommands.test_real_command_still_denies` covers only 5 shapes. Add `bash -c`, `cat <<'EOF' | bash`, `sudo`, `git -C` and `if/then` so the N405 coverage is pinned.
5. **Unclear constant name:** in `github_auto_close_keywords.py`, `_BLANKED_BODY = "HEREDOC_BODY"` looks like a real token in debug output. Fix: use a placeholder like the shared `_MESSAGE_BODY_PLACEHOLDER`, or document why it differs.