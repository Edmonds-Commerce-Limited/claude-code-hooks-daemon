# Plan 00527 Phase 5 report (tasks 5.1 to 5.6)

## Changes

- 5.1 `strategies/qa_suppression/go_strategy.py`: added pattern `(?://|#)\s*#?\s*nosec` (covers `// nosec`, `//nosec G104`, `// #nosec`, `#nosec`); `gosec` added to tool names. `//nolint` stays blocked with or without a reason (pinned by a test). Handler `get_claude_md` text updated.
- 5.2 `strategies/comments/syntax.py`: new `CommentSyntax.package_clause_prefix` and `GO_SYNTAX` (Go no longer shares `SLASH_SYNTAX`). `strategies/comments/extractor.py` marks a comment span that ends on the line directly above a line starting `package ` as `is_doc`. A blank line detaches it (as `go doc` does). Effects: exempt from `comment_size` and from docs_qa comment finding; `comment_changelog` still scans it (the existing `is_doc` contract). Other Go comments and other languages are unchanged. `comment_size.get_claude_md` updated. Limitation: an `Edit` is judged on `new_string` alone, so a package comment edited without the `package` line in the replaced text is not recognised.
- 5.3 `handlers/stop/auto_continue_stop.py` `_QA_FAILURE_PATTERNS`: `^\s*--- FAIL:` and `^FAIL\b` (matches `FAIL`, `FAIL<TAB>pkg<TAB>time`; not pytest's `FAILED`). A passing `go test -v` run is pinned as not a failure.
- 5.4 `handlers/pre_tool_use/lsp_enforcement.py`: `func` added to `_DEFINITION_KEYWORDS`. Method receiver form `func (r *T) Foo` not added (optional per brief; it contains regex metacharacters).
- 5.6 same file: `_invocation_targets_one_file` takes the search base and returns False for a single target that is an existing directory (`path_is_dir`, EACCES-safe, `unreadable_means=False`). New `_search_base` (hook `cwd`, else project root) is shared with `_searched_directories` (DRY). A bare directory therefore falls to the Phase 1 survey: a YAML-only bare dir is advised, a Python dir is denied. The existing `test_matches_still_fires_for_directory_target` uses `src/` and needed no change; bare-dir, bare-file and survey cases were added.
- 5.5 `guides/llm-command-wrappers.md`: golangci-lint v2 spelling `--output.json.path` (v1 `--out-format json` removed in v2); the wrapper writes JSON to `./var/qa/golangci-cache.json` and discards the text report on stdout. The v2 flag also accepts `stdout`/`stderr` as the path; I chose a file because the default text report also prints to stdout and would corrupt a JSON-on-stdout capture. This spelling is from my knowledge of the v2 docs, not verified against a binary (none installed here). The Go section now says golangci-lint is optional and `gofmt -l`, `go vet`, `go test -json` are the baseline. The summary table row was updated too.
- Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/061-go-smaller-handler-fits.md`. PLAN.md tasks 5.1 to 5.6 ticked.

## Not done (out of scope, noted)

GO-AUDIT.md also lists `//revive:disable` and `//golangci-lint:ignore` as missed suppressions; the brief named only `//nosec`/`#nosec`, so they are left for a later decision.

## TDD note

Tests were written before the source changes, but I did not run them red separately; they were run together with the implementation (2226 tests in the affected test modules pass).

## QA

`llm_qa.py changed --base main`: 39 of 40 checks pass (format, lint, mypy, pyright, error_hiding, docs_qa, plan_qa, project_handlers and the rest). The 40th, `changed_tests`, ran 3740 tests with 0 failures and 5 skipped, but fails the run because three edited handlers (`comment_size.py`, `qa_suppression.py`, `auto_continue_stop.py`) are classed `too-broad`: their reach is wider than the mapper's cap, so the remainder is the coordinator's full gate (`--allow-unmapped`). I did not rerun with `--allow-unmapped` or add a map rule. A second run timed out waiting for the host-wide QA lock (other agents held it). The worktree has no venv, so QA ran with `HOOKS_DAEMON_PYTHON` pointing at the main checkout's venv and `PYTHONPATH` at this worktree's `src`.
