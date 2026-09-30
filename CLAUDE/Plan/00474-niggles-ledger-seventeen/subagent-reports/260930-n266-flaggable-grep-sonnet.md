# N266 report: flaggable_content_channel_guard and grep

**Branch**: `worktree-n266-flaggable-grep`

## Cause

The two reported commands could not be reproduced. On current code neither is denied, and neither is any variant I tried that names only paths off `tests/fixtures/cyber-flag/` (a file under `.github/`, `src/.../utils/*.py`, a scratch file, a quoted regex). The match is a text match on the command through `secret_file_matching.find_protected_mention`; the handler never models where a search descends. The likely cause is the quoted-regex-as-glob defect N269 (`e9281dfda`), which judged a grep pattern's glob-like text as a path. That is not proven: the original patterns were not recorded.

Testing found the opposite gap. A recursive `grep -r`, `rg` or `git grep` rooted at `.`, at `tests/` or with no path was not denied at all.

## Change

`flaggable_content_channel_guard.py` now resolves the roots of each recursive grep-family search (`grep -r`/`-R`/`--recursive`/`-d recurse`, `rg`, `git grep`) against the payload cwd and the project root. It denies when a root is an ancestor of, or inside, a flaggable glob's literal directory, or cannot be placed (shell expansion, unparseable quoting, relative path with no cwd). A no-path `rg` fed by a pipe reads stdin and is allowed. The existing text-mention path is unchanged.

An unanchored glob such as `*.rules` has no literal directory, so any recursive search under the project is denied for it.

## Tests

`tests/unit/handlers/pre_tool_use/test_flaggable_content_channel_guard.py`: 80 pass, 25 of the new cases failed first. With `test_flaggable_work_advisor.py`, 107 pass. ruff, black and mypy are clean on both touched files; `audit_error_hiding.py` and `check_input_contract.py` pass.

## Not verified

- The original two denials; the N269 link is a judgement.
- pyright: the worktree has no `untracked/` venv, so it could not import pytest in the test file; no source-file error was reported.
- The live daemon was not restarted, so the dogfood config was not exercised end to end.
- `grep`/`rg` option parsing is a short list of value-taking options; an option outside it could make a value read as a root (a false deny, not a false allow).
