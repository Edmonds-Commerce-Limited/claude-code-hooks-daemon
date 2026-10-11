# Batch F report: message guards (N404, N405, N406)

Branch agent-a2f6348f56d8df606-7aed436a. Fix commit 25b9ae109; ledger status commit d2a461bba.

## N404 git_message_backtick

- Root cause: the double-quoted `-m` regex ran over the raw command, so the `$(cat <<'EOF' ... EOF)` body (literal) and a `-m "..."` inside a single-quoted message were read as live double-quoted messages.
- Fix: `src/claude_code_hooks_daemon/handlers/pre_tool_use/git_message_backtick.py` `matches()` scans `strip_message_bodies(command)`, which blanks single-quoted values and the quoted-delimiter heredoc idiom but keeps any value that can substitute.
- Tests (tests/unit/handlers/pre_tool_use/test_git_message_backtick.py, class TestQuoteContextOfTheMessageValue): heredoc commit and tag allow, `-m "..."` inside single quotes allows; unquoted heredoc delimiter and plain double-quoted backtick still deny. Gate rows n404-\* in tests/fixtures/ordinary_command_corpus.yaml.

## N405 ancestry_preserving_merge

- Root cause: the patterns ran with `search` over the whole raw command string.
- Fix: `ancestry_preserving_merge.py` `_executable_segments` = `command_position_segments(strip_inert_spans(command))`; `_match_label` and `_match_rule_id` match per segment. Acceptance DENY commands are now unwrapped (an echo is deliberately allowed); warn-mode ones use a nonexistent branch/PR.
- Tests (test_ancestry_preserving_merge.py, TestMentionsAreDataNotCommands): 9 mention shapes allow (message, grep, echo, quoted heredoc, `-F -` heredoc, heredoc idiom); real commands, chains and `bash <<'EOF'` still deny. Old echo-wrapped "must match" tests removed as they asserted the defect. Gate rows n405-\*.

## N406 github_auto_close_keywords

- Root cause: the git/gh token was found anywhere in a piece, including inside an echo's quoted text and a non-git heredoc body.
- Fix: `github_auto_close_keywords.py` `_GIT_COMMAND_START`/`_GH_COMMAND_START` require command position (start, newline, pipe, group, sudo/env prefix, assignments); `_without_foreign_heredoc_bodies` blanks heredoc bodies whose opener line names no git/gh message command. gh issue/pr comment bodies were not covered before and are not added.
- Tests (test_github_auto_close_keywords.py, TestPrintedKeywordsAreNotMessages): echo and python3/cat heredoc printing a keyword allow; commit -m, heredoc idiom, `-F -` heredoc, chained commit and gh pr create still deny. Gate rows n406-\*.

## QA

Red-before-green was not demonstrated against a pre-fix tree (the worktree venv guard blocked running tests against a HEAD copy); the old behaviour is the ledger evidence.
`llm_qa.py changed --allow-unmapped`: "QA: 36/40 PASSED, 2/40 FAILED, 2/40 NOT MEANINGFUL (detector failed: docs_qa, plan_qa)". format, lint, type_check, pyright, magic_values, error_hiding all 0; changed_tests 2644 passed, 0 failed, 5 skipped; project_handlers 238 passed. docs_qa (12 findings) and plan_qa (6) are advise-only (0 block) pointer-resolves findings on links to the archived plan 00483, in files this batch did not touch except NIGGLES.md's existing links; they are what mark the two test rows NOT MEANINGFUL.
Also: ordinary_command_regression_gate n404/n405/n406 rows: 7 passed.
