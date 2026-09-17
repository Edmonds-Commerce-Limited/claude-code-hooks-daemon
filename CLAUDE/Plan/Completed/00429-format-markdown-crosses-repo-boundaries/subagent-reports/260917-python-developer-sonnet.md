# Plan 00429 — format-markdown crosses repo boundaries — implementation report

## What changed

`src/claude_code_hooks_daemon/daemon/cli.py`, `cmd_format_markdown`
directory-mode branch:

1. Added `_is_nested_git_repo_root(directory)`: true when `directory / ".git"`
   is a directory (normal checkout) OR a file (worktree — its `.git` points at
   `.git/worktrees/<name>` in the main checkout, not a repo of its own but
   still a boundary the walk must not cross).
2. Added `_iter_markdown_candidates(root, exclude_paths)`, replacing the bare
   `sorted(path.rglob("*"))` walk. It uses `os.walk` with in-place `dirnames`
   pruning: any subdirectory that is itself a git repo root is dropped from
   `dirnames` before the walk descends, so nothing below it is ever visited
   (not just skipped-and-filtered — never opened at all). The walk root
   itself is never checked against `_is_nested_git_repo_root` — only entries
   discovered as children during the walk are, which is what keeps an
   ordinary `format-markdown .` on the caller's own repo unaffected.
3. `daemon.exclude_paths` is applied per candidate file via the existing
   `utils.path_exclusion.is_path_excluded`, reusing the exact mechanism
   `cmd_docs_qa`/`cmd_plan_qa` already thread through (Plan 00362 Task 2.9),
   not a second filter. `project_root` for pattern anchoring is the walk
   root (`path`), matching the `format-markdown .` convention the housekeeping
   skill documents.
4. `cmd_format_markdown` now loads config via
   `Config.load_or_default(path / ".claude" / "hooks-daemon.yaml")` — this
   degrades to defaults (no exclusions) when the target directory carries no
   daemon config, so `format-markdown` still works on an arbitrary directory
   that is not itself a daemon installation.
5. The **file-argument branch is untouched** — Task 1.4's decision is that a
   file the caller names directly is always formatted, exclusions or not,
   because naming it is explicit consent. Only the directory walk filters.
   Pinned by `test_file_argument_named_directly_is_formatted_even_if_excluded`.

Also: moved `Sequence` out of the file's `TYPE_CHECKING`-only import block
into the top-level `collections.abc` import, since `_iter_markdown_candidates`
now uses it in a runtime-evaluated signature — ruff's TC004 flagged the
now-duplicate import (`Sequence` can't be type-checking-only once a function
signature uses it directly without `from __future__ import annotations`,
which this file doesn't declare).

## TDD evidence

Tests added first, confirmed RED, in
`tests/unit/daemon/test_cli_format_markdown.py`:

- `TestCmdFormatMarkdownRepositoryBoundary` (4 tests): a real nested git repo
  (`git init` + commit, via subprocess — same idiom as
  `tests/unit/handlers/utils/test_plan_numbering.py`) below the walk root is
  untouched in both write and `--check` mode; the walk root's OWN repo is
  NOT treated as a boundary; a worktree's `.git` FILE is recognised too.
- `TestCmdFormatMarkdownExcludePaths` (3 tests): `daemon.exclude_paths` is
  honoured in both write and `--check` mode for the directory walk; a file
  argument named directly bypasses it (Task 1.4, pinned rather than left
  implicit).
- Every test in `TestCmdFormatMarkdownRepositoryBoundary` and the write/check
  tests in `TestCmdFormatMarkdownExcludePaths` also asserts a reachable
  "own" file WAS reformatted — the vacuity guard the brief asked for, so a
  walk that silently found nothing cannot pass.

Pre-fix run (`uv`-resolved venv python, `pytest -q`):

```
FAILED ...RepositoryBoundary::test_write_mode_does_not_modify_nested_repo - FileNotFoundError (test bug: fixed by mkdir-ing the tracked file's parent before writing it)
FAILED ...RepositoryBoundary::test_check_mode_does_not_report_nested_repo - FileNotFoundError (same)
FAILED ...RepositoryBoundary::test_worktree_git_file_marks_a_boundary_too - AssertionError: assert '| A         |' not in '# Test\n\n|...| string |\n'
FAILED ...ExcludePaths::test_excluded_directory_is_skipped_in_write_mode - AssertionError: assert '| A         |' not in '# Test\n\n|...| string |\n'
FAILED ...ExcludePaths::test_excluded_directory_is_skipped_in_check_mode - assert 1 == 0
5 failed, 13 passed
```

(The two `FileNotFoundError`s were a test-fixture bug — the helper didn't
`mkdir -p` the tracked file's parent before `git init`; fixed in the same
commit as the RED run, then re-confirmed RED against the real defect before
touching `cli.py`. The remaining 3 failures are the actual defect: the
nested-repo file and the excluded file both got reformatted.)

Post-fix run: **18 passed** in `tests/unit/daemon/test_cli_format_markdown.py`.

## Decision I made without asking (Task 1.4)

Pinned as a test rather than left implicit, per the brief: a file argument
named directly is formatted regardless of `daemon.exclude_paths` and
regardless of whether it happens to sit inside a nested git repo (the latter
isn't explicitly tested but follows the same reasoning and the same code
path — the file branch never calls `_iter_markdown_candidates` at all). I
agree with the brief's ruling here: naming a path is the explicit consent
the safety default and the project preference both exist to require in the
*directory* case.

## QA

Ran `./scripts/qa/llm_qa.py all` from inside the worktree twice (first run
surfaced a `ruff` TC004 warning from the `Sequence` import move, fixed, then
re-ran).

First run: `QA_EXIT=1` — `QA: 29/35 PASSED, 6/35 FAILED` (format 5 files
autofixed by black, lint 1 warning, magic_values 1, pyright 11, tests 10
errored, docs_qa 1).

Fixed the lint warning (moved `Sequence` import), re-ran full QA:

```
QA: 30/35 PASSED, 5/35 FAILED
QA_EXIT=1
```

`format` and `lint` now both pass (0 violations). The `tests` category
showed 18 errored/1 failed here, traced to `STALE DAEMON: the running daemon's loaded code ... does not match the current working tree` — a
smoke_test acceptance probe was judging the daemon process against pre-edit
source. Ran `./bin/hooks-daemon restart`, then re-ran the `tests` and
`smoke_test` categories only:

```
❌ tests: 25080 passed, 1 failed, 23 skipped | coverage: 95.2%
   failed: tests/daemon/test_init_config.py::TestConfigHandlerCoverage::test_all_pre_tool_use_handlers_in_config
✅ smoke_test: 3/3 probes passed
QA: 1/2 PASSED, 1/2 FAILED
QA_EXIT=1
```

**Remaining failures are pre-existing and unrelated to this change** — none
touch `cmd_format_markdown`, `_iter_markdown_candidates`,
`_is_nested_git_repo_root`, or the format-markdown tests:

- `magic_values`: 1 violation in `tests/unit/core/test_chain_handler_scope.py`
  (magic priority `50`) — pre-existing, unrelated file.
- `pyright`: 11 errors, all in `tests/integration/test_handler_scope_defaults.py`
  (`reportAttributeAccessIssue` on an `object`-typed attribute) — pre-existing,
  unrelated file.
- `docs_qa`: 1 advisory — a stale link in
  `CLAUDE/Plan/00388-.../CRONS-AS-FIRST-CLASS.md` pointing at plan 00423's old
  (pre-archive) path — unrelated plan doc.
- `tests`: `test_all_pre_tool_use_handlers_in_config` — a handler-registry
  coverage check with no connection to markdown formatting.

I did not touch any of these files; `git status --short` in the worktree
confirms only `src/.../daemon/cli.py`,
`tests/unit/daemon/test_cli_format_markdown.py`, and the new release-note
file are changes belonging to this plan. Three OTHER files
(`src/claude_code_hooks_daemon/core/handler_scope.py`,
`tests/integration/test_handler_scope_defaults.py`,
`tests/unit/handlers/pre_tool_use/test_subagent_cron_delete_blocker.py`) show
as modified purely because the QA run's `format` check auto-fixed
pre-existing Black drift on `main` (unrelated to issue #47) — left unstaged
per the coordinator's note and excluded from this plan's commit.

## Release note

Added
`CLAUDE/UPGRADES/UNRELEASED/release-notes/07-format-markdown-respects-repository-and-exclusion-boundaries.md`
(audience: operators) describing the behaviour change for the pending-release
holding area.

## Files

- `src/claude_code_hooks_daemon/daemon/cli.py` — the fix
- `tests/unit/daemon/test_cli_format_markdown.py` — regression tests
- `CLAUDE/UPGRADES/UNRELEASED/release-notes/07-format-markdown-respects-repository-and-exclusion-boundaries.md`
  — release note
