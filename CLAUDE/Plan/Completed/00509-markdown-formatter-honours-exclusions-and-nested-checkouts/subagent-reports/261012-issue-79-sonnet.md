# Issue #79 implementation report

**Plan**: 00509, Tasks 1.1 to 1.3. Branch `worktree-plan-00509`.

## What changed

- `src/claude_code_hooks_daemon/handlers/post_tool_use/markdown_table_formatter.py`
  - New `_exclude_paths` option attribute (set by the registry's setattr, so config validation accepts the key, as for `lint_on_edit`). `_is_in_scope` combines `handler_excludes_path` (handler option plus injected `_project_exclude_paths`, with the layout) and the nested-checkout boundary. It gates both `matches` and `handle`.
  - Advisory: `_classify_changes` returns `(labels, fully_named)`. A diff chunk counts as named only when a category explains the whole chunk (table rows differing only in padding or delimiter width, ordered-list digits only, a thematic break respelled `---`, escaped asterisks only). Otherwise the advisory reads `Reformatted the whole file (mdformat): <labels>, plus other formatting changes (bullet markers, blank lines, escaping, wrapping)`, or without the labels when none fired. A fully named diff keeps the old message, so the acceptance test pattern still holds. `classify_markdown_changes` keeps its list return.
  - `_ordered_list_renumbered` is now strict: every differing pair must be a digit-only change (it used to accept a chunk if any one pair was).
  - `get_claude_md` states whole-file formatting, `exclude_paths`, the nested-checkout skip, and the new advisory wording.
- `docs/guides/HANDLER_REFERENCE.md`: there was no `markdown_table_formatter` entry at all; added one (after `goal_injection`, by priority).
- `CLAUDE/UPGRADES/UNRELEASED/release-notes/032-...md`: callout, titled `# Callout: `.
- PLAN.md: Tasks 1.1 to 1.3 ticked.
- Tests: `tests/unit/handlers/post_tool_use/test_markdown_table_formatter.py` (`TestExcludePaths`, `TestNestedCheckouts`, `TestAdvisoryNamesEveryChange`; two existing generic-fallback tests updated to the new wording).

## Nested-checkout rule used

Boundary: `core.worktree_paths.nested_git_checkout_root(file, project_root)`, the nearest ancestor below the project root holding a `.git` entry (file or directory). Round 2: the file is skipped unless `utils.git_repo.is_worktree_of_repo(ancestor, project_root)` is true: the ancestor's `.git` is a FILE whose `gitdir:` target is `<common>/worktrees/<name>`, and `<common>` equals the project's own common git dir (its `.git` directory, or, when the project is itself a linked worktree, the same derivation). Paths are resolved; path reads only, no subprocess. A worktree of an unrelated repository is therefore skipped (tested). The paragraph below that says an unrelated worktree is still formatted is superseded.
Round 1 (superseded): the file was skipped unless `is_linked_worktree(ancestor)` held, i.e. the `.git` is a FILE whose `gitdir:` target contains `/worktrees/`. A nested clone (`.git` directory) and a submodule (`gitdir: .../modules/...`) are therefore skipped; a linked worktree is formatted. With no project root (ProjectContext uninitialised) the boundary is not applied.

Difference from the 00429 CLI to flag: `format-markdown`'s walk (`_is_nested_git_repo_root` in `daemon/cli.py`) prunes ANY child with a `.git` file or directory, linked worktrees included. The plan's ruling for the handler is the opposite for linked worktrees, so I did not copy that predicate. `is_linked_worktree` does not check that the worktree belongs to THIS repository, so a linked worktree of an unrelated repository below the project root would still be formatted. Closing that would need comparing the gitdir target with this repository's common git dir; I left it out as beyond the brief.

## Verification

- RED confirmed first (test module failed to import the new names), then GREEN.
- 567 passed across: the handler test file, `tests/unit/config/test_handler_config_options.py`, `test_handler_options_accessor.py`, `tests/unit/core/test_claude_md_injector.py`, `tests/integration/test_claude_md_guidance_coverage.py`, `test_handler_reference_check.py`, `tests/unit/handlers/test_unstattable_caller_paths.py`, `tests/unit/utils/test_markdown_format.py`.
- black (py311), `ruff check --fix` and mypy clean on the two Python files. No QA suppressions. The full suite was not run.
- CLAUDE.md guidance block not regenerated: the handler appears there only as a one-line entry whose heading is unchanged.
