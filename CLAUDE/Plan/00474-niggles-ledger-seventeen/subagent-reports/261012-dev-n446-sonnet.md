# N446 report (GitHub #98): git failure at daemon start labelled as git

Branch `worktree-issue-98-git-error`. See the git log of the branch for the commit hashes (one implementation commit that carries this report).

## Change

- `core/project_context.py`: new `GitContextError(ValueError)`. `_get_git_repo_name` raises it when `rev-parse` fails, when `origin` is missing, and when the origin URL is empty. `_get_git_toplevel` raises it when `rev-parse --show-toplevel` fails. Messages keep "FAIL FAST", name the git command, and carry the exit code and git's stripped stderr ("no error output" when stderr is empty, which covers run_git's timeout and missing-binary results, whose reason is in stderr). The failures are logged at WARNING with the same detail. `initialize` raises `GitContextError` for the two `None` cases (unparseable URL, empty toplevel).
- `daemon/cli.py` `_validate_installation`: `except GitContextError` before the generic `except Exception`; prints the project root, git and the message, suggests checking the repository or git version; no "Invalid configuration" and no "Fix the configuration file"; `sys.exit(1)`.
- Release note 047.

## Red first

- `tests/unit/daemon/test_cli_git_failure_labelling.py`: 2 failed, 2 passed (the passes are the two regression guards that a real config or Pydantic error still says "Invalid configuration"). The real-repository test with `extensions.zzzunknownext` is among the passing-after tests.
- `tests/unit/core/test_project_context.py`: the whole module failed to collect (ImportError on `GitContextError`) before implementation, so every test in it counted as red.

## Tests

- Added: `tests/unit/daemon/test_cli_git_failure_labelling.py` (4 tests), plus in `test_project_context.py`: no-stderr exit code, WARNING log with stderr.
- Changed in `tests/unit/core/test_project_context.py` (old pins no longer hold): `test_initialize_fails_if_not_in_git_repo` (now `GitContextError`, rev-parse and exit 128 in the message), `test_initialize_fails_if_no_git_remote` (matches "no remote 'origin'"), `test_get_git_repo_name_handles_empty_url` (renamed `..._raises_for_empty_url`), `test_get_git_repo_name_handles_timeout` (renamed `..._raises_on_timeout`), `test_get_git_toplevel_handles_timeout` and `..._handles_unexpected_error` (renamed `..._raises_...`).

## QA

- Targeted pytest (project_context, cli_git_failure_labelling, cli_self_install): 54 passed.
- `./scripts/qa/llm_qa.py changed --allow-unmapped`: 40/40 passed. The first run flagged B404 (a `subprocess` import I had added for an annotation; removed by passing returncode and stderr to the helper).

## Deviations

- `llm_qa.py changed` fails on the two edited files as "unmapped (too-broad)" without `--allow-unmapped`; I ran it with that flag. The 100 mapped tests passed in the earlier run.
- The brief said "the existing `_validate_installation` tests"; I put the new CLI tests in a new file rather than `test_cli_self_install.py`, whose autouse fixture mocks the git functions.
