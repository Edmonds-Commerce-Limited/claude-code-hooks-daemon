# Batch H: N407 (pip guards) and N408 (gh view comment guards)

Branch `agent-ad9dc30f1ec7d2976-bb392d4f`. Plan folder: 00474-niggles-ledger-seventeen.

## What changed

- `utils/command_position.py`: added `without_comment` and `command_position_code_segments`.
  `command_position_segments` keeps comment text as a command on purpose (conservative reading in the segment
  splitter), so the two pip guards and the gh helper cut a trailing shell comment off each segment before matching.
- `handlers/pre_tool_use/pip_break_system.py`, `sudo_pip.py`: pattern is matched per
  `command_position_code_segments(command)` instead of the raw string. Acceptance commands are now
  `bash -n -c '...'` with `nonexistent-pkg-zz-safe-test`.
- New `utils/gh_view_comments.py` (`uncommented_view_segment`, `suggest_with_comments`): shared by
  `gh_issue_comments.py` and `gh_pr_comments.py`. Reads the view segment per command-position segment, reads flags as
  shell words (so `--json=comments`, `--json=a,comments` and a quoted `--jq '.a | .b'` are right), and splices the
  suggested fix into the real view segment. The handlers lost their private regex/segment code. Acceptance commands
  are `bash -n -c 'gh <noun> view 999999999'`.
- Corpus: `tests/fixtures/ordinary_command_corpus.yaml` rows `n407-*` (8) and `n408-*` (6); 14 pass.
- NIGGLES.md: N407 and N408 flipped to Fixed.

## Tests (TDD)

New: `tests/unit/handlers/pre_tool_use/test_pip_guards_command_position.py`,
`test_gh_view_comments_command_position.py`, `tests/unit/utils/test_gh_view_comments.py`,
`tests/unit/utils/test_command_position_comments.py`.
RED against the unfixed code: 44 failed, 70 passed (mentions denied, `--json=comments`, quoted-jq pipe, echo
acceptance commands). GREEN after the fix: 321 passed across the new and existing pip/gh test files.
Two older tests asserted the mention deny ("better safe than sorry") and were flipped:
`test_matches_echo_mentioning_flag_returns_false` (pip_break_system) and `test_not_matches_echo_with_gh_issue_view`.

Deny shapes pinned: plain, `if...then...fi`, `bash -c` (both quotes), `bash -n -c`, `eval`, `env`, `nohup`,
`timeout`, `&&`, `||`, `;`, pipe, subshell, `$(...)`, backticks, `&`, `!`, `cat <<'EOF' | bash`, `bash <<'EOF'`,
unquoted `bash <<EOF`, newline-joined, mention-then-real. Binary forms: `pip3`, `/usr/bin/pip`, `python -m pip`,
`python3 -m pip`, `uv pip`, `sudo -H`, `sudo /usr/bin/pip`.

## QA

`llm_qa.py changed --allow-unmapped`: 37/40 pass. Format clean, lint, mypy, pyright, handler_reference all pass.
Not mine: `plan_qa` journal freshness for 00495 (known), and
`tests/unit/utils/test_command_position.py::TestGhProse::test_other_gh_subcommands_keep_their_arguments` fails
at the branch base (`strip_inert_spans` now redacts a `gh api --body` value; the test predates it). Left alone.
Environment note: the shared venv is editable-installed to `/workspace/src`, so the worktree QA ran through a copied
venv (`untracked/venv-wt-batchh`, gitignored) whose `.pth` points at the worktree `src`.

## Not covered

The INVENTORY misses in N407 (`pip --break-system-packages install`, the env var, `sudo -u USER pip install`) stay
separate, as the ledger says.
