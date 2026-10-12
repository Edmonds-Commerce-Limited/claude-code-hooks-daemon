# Plan 00510 (Issue #80): docs QA edit-stage scope, implementation report

## Change

`is_lintable_path` (`src/claude_code_hooks_daemon/docs_qa/corpus.py`) is the one scope check for `docs_qa_edit`, `docs-qa --lint` and the staged view. After the existing exclusion and the three admitting arms, it now drops:

- a path in a nested separate checkout (clone, submodule-style `.git` file, linked worktree of another repository);
- a gitignored path, except `.claude/ccy/CLAUDE.md`, the sweep's one deliberate gitignored inclusion (`_GITIGNORED_MARKDOWN_INCLUDES`).

This repository's own linked worktrees stay in scope. The cheap checks (admitting arms, then nested-checkout test) run before the git spawn, so a non-doc path never spawns git.

## New shared pieces

- `src/claude_code_hooks_daemon/utils/repository_scope.py`: `owning_checkout(abs_path, project_root) -> Path | None` and `outside_this_repository(...)`. The Plan 00509 rule (`nested_git_checkout_root` plus `is_worktree_of_repo`), extracted. The formatter now calls it, so the two surfaces cannot drift.
- `utils/git_repo.py`: `path_is_git_ignored(checkout, abs_path)`, one `git check-ignore -q -- <rel>` via `run_git` (so `Timeout.GIT_CONTEXT`). Fails open (False, debug log) on not-a-repo, git missing, timeout or a path outside the checkout. A tracked file is never reported ignored.

No existing per-path ignore check existed. `git_visible_paths` is an uncached whole-tree `ls-files`, so it was not used. `protected_file_index` and `write_protected_paths` each spawn `check-ignore` inline for their own purposes with no cache.

## Design point worth knowing

The ignore test runs in the OWNING checkout, not always the project root. This repository's worktrees live under `untracked/worktrees/`, which the outer `.gitignore` excludes, so judging a worktree file against the outer repository would wrongly drop every file in an own worktree. `owning_checkout` returns the worktree root for those, and the ignore check runs there (covered by `test_a_module_doc_in_this_repositorys_own_worktree_is_still_linted`).

## Per-call cost (measured, tmp git repo, 50 iterations each)

| Path                                          | `is_lintable_path` total | of which `owning_checkout` |
| --------------------------------------------- | ------------------------ | -------------------------- |
| tracked/untracked-not-ignored `src/CLAUDE.md` | 2.49 ms                  | 0.067 ms                   |
| ignored `ignored/CLAUDE.md`                   | 1.58 ms                  | 0.058 ms                   |

The added cost is essentially the single `git check-ignore` spawn, about 1.5 to 2.5 ms per documentation edit. The nested-checkout probe is filesystem only (about 0.06 ms). The staged view (`staged_context`) also calls `is_lintable_path`, so it pays one spawn per staged `.md` file that passes the cheap arms.

## Tests (RED first: 7 failed before the change, all green after)

- `tests/unit/utils/test_repository_scope.py`: ownership cases and `path_is_git_ignored` (ignored, not ignored, tracked-under-ignore, not a repo, git error, outside checkout).
- `tests/unit/docs_qa/test_corpus_scope.py`: `is_lintable_path` for nested clone, submodule-style, foreign linked worktree, own worktree (stays), gitignored directory, ordinary and tracked module docs (stay), non-git project (stays), gitignored corpus doc (out), ccy `CLAUDE.md` (stays).
- `tests/unit/daemon/test_cli_docs_qa.py::TestLintScope`: `--lint` of an oversize module doc in a nested clone and in an ignored directory exits 2 ("not a documentation file"); an ordinary one is not refused.

Targeted run: repository_scope, `tests/unit/docs_qa`, `test_cli_docs_qa`, the markdown formatter tests, `test_docs_qa_edit`, `tests/integration/test_claude_md_guidance_coverage.py`, `test_handler_reference_check.py` and `test_pending_release_notes_holding_area.py`: 1116 passed. black (py311), ruff and mypy clean on touched files. The full suite was not run.

## Docs

`docs_qa_edit` module docstring and `get_claude_md`, the `docs_qa_edit` entry in `docs/guides/HANDLER_REFERENCE.md`, the `docs-qa --lint` refusal message, and release note `033-docs-qa-edit-lint-skips-nested-checkouts-and-gitignored-files.md` (title starts `# Callout: `). PLAN.md tasks 1.1 to 1.3 ticked.

## Notes for the coordinator

- Behaviour change beyond the issue text: a gitignored doc that is in the corpus trees (for example a gitignored `CLAUDE/Scratch.md`) is also no longer linted at edit time, since the rule is applied to every admitting arm, matching the sweep. Say if you want it limited to the module-doc arm.
- Not committed to the README index or statistics; Phase 2 (merge, close #80) is untouched.
