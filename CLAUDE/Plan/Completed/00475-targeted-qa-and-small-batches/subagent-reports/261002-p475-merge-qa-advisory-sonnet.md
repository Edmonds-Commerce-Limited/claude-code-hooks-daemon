# Plan 00475 Task 4.2: merge-time advisory for an unrecorded targeted QA pass

Branch `worktree-p475-merge-qa-advisory`. Ledger 00474 N278.

## What already existed

`scripts/qa/llm_qa.py` records, per tool, `{head, tree_digest, passed, exit_code, output_sha256}` in `untracked/qa/provenance.json` (`record_provenance`, written by
`_record_run`). So the commit IS recorded, but under `QA_OUTPUT_DIR = PROJECT_ROOT / untracked/qa`, which is the checkout the run happened in: a branch's worktree. The
coordinator merges from another checkout. It is also per tool, with no marker that
the whole `changed` selection ran.

## Design: where the record lives

A ref, shared by every worktree: `refs/integration/changed-green/<branch>`, holding
the commit a passing run judged. It follows the existing `refs/integration/base|certified/`
refs in `llm_qa.py`. No worktree lookup (`git worktree list`) is needed and a removed
worktree does not lose the record.

- `record_changed_pass(root, judged)`: on a passing run of the whole `CHANGED_TOOL_NAMES`
  set, writes the ref. Raises `MainMovedError` (printed as a NOT RECORDED warning) on a
  detached HEAD, a dirty tree, or a tree that changed since the run judged it.
- `clear_changed_pass(root)`: a failing run of the whole selection drops the branch's
  record. A partial run (a subset of tools) neither records nor clears.
- Wired in `_run_tools` through `_record_changed`, after `_record_run`.

A later commit makes the record stale on its own, because the handler compares the
ref's commit to the branch's current head.

## Handler

`src/claude_code_hooks_daemon/handlers/pre_tool_use/merge_qa_advisor.py`:
`MergeQaAdvisorHandler`, `HandlerID.MERGE_QA_ADVISOR`, `Priority.MERGE_QA_ADVISOR = 56`,
non-terminal, tags ADVISORY/GIT/QA_ENFORCEMENT/WORKFLOW/NON_TERMINAL. Never denies.

- Recognises merges with the shared walker `git_invocations` (wrappers, `eval`, `sh -c`,
  `cd`), places them with `placement_problem` / `invocation_directory` (`-C`, `cd`), and
  skips `--abort`, `--continue`, `--quit`.
- Merged refs are the positional words; the value options `-m -F -s -X` and the long
  forms are skipped, so a `-m` message is not taken for a branch.
- A ref is a work branch when it matches `worktree-*` bare, `refs/heads/`, `origin/` or
  `refs/remotes/origin/` (prefix from `branch_count_advisor.WORK_BRANCH_PREFIX`). It is
  resolved with `git rev-parse --verify --quiet <fully-qualified ref>^{commit}` under
  `Timeout.GIT_CONTEXT`, via `run_git` (never raises).
- Silent when the record equals the head, for a non-work branch, an unresolvable ref, an
  unplaceable directory (`$VAR`, `--git-dir`), and on any git failure (fail open).
- The ref template is duplicated in the handler (`CHANGED_GREEN_REF_TEMPLATE`) because the
  script cannot be imported by the daemon; a test pins it to `llm_qa.changed_green_ref`.

Config: `.claude/hooks-daemon.yaml`, `.claude/hooks-daemon.yaml.example`,
`daemon/init_config.py`, config-changes entry in
`CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.68.0.yaml`, release note
`CLAUDE/UPGRADES/UNRELEASED/release-notes/214-...md`, `.claude/HOOKS-DAEMON.md`
regenerated with `generate-docs` (the table realigned, hence the large diff).
Docs: `CLAUDE/QA.md` ("Before Merging: the Coordinator's Check") and the handler's
`get_claude_md`. Plan 00475 Task 4.2 is 🔄 and N278's status notes the branch.

## Tests

- `tests/unit/handlers/pre_tool_use/test_merge_qa_advisor.py` (31): green record silent;
  missing, older-head and other-branch records advise; `origin/` ref; `-m` message;
  `-C`; leading `cd`; octopus (both, and only the unrecorded one); non-work branch,
  prefix-in-the-middle name, missing ref, non-repository, missing directory, bare
  `git merge`, `$WHERE` directory, git failure (patched `run_git`) all silent;
  `--abort`/`--continue`/`--quit` do not match; non-merge commands and non-Bash do not.
- `tests/unit/qa/test_llm_qa_changed_green.py` (16): record, move on a newer pass, dirty,
  changed-during-run, detached, unreadable tree; clear; `_run_tools` wiring (pass records,
  fail clears, partial records nothing and keeps the old one, dirty warns, read-only).
- `test_blocking_handler_evasion.py`: classified with 11 respellings and 4 must-not-match.

## QA

ruff, black (py311), mypy and pyright (`run_pyright_check.py --json`, 0 errors) clean on
the touched files. See the final run of `./scripts/qa/llm_qa.py changed --allow-unmapped`
in the reply.
