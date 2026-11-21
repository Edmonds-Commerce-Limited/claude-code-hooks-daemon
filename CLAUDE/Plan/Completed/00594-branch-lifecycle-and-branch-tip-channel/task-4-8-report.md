# Task 4.8 report: branch practice written down, with advisories

Branch `plan-00594-task-4-8-branch-practice`.

## What changed

- Practice, written once: new "Branch Practice" section in
  `CLAUDE/core/Worktree.core.md` (and its install template copy, which must
  stay identical). Chosen over `CLAUDE/Worktree.md` because the core doc is the
  client-facing, shipped one; `Worktree.md` is this repo's own addendum and says
  never to copy core content. `CLAUDE/Worktree.md` gets one pointer (in "Dropping
  is a deletion", where it said "keep no archive branches"), not a copy.
- Detection lives in the existing `branch_creation_guard` (it already parses
  every creating git command, including `worktree add`). No new handler.
  `WorktreeCreate` cannot nest (it anchors to the main checkout), so nothing
  was added there.
- New `core/branch_practice.py`: `recovery_copy_advisory(name)` and
  `nested_worktree_advisory(directory, target)` (real `git worktree list`).
  Patterns are the named constant `RECOVERY_COPY_PATTERNS` in
  `constants/branch_guard.py`. New `worktree_add_path()` in
  `utils/git_branch_creation.py`. Advice is added to the ALLOW context only;
  a cap deny is unchanged. `get_claude_md` updated.
- Release note `043-branch-practice-advisories.md`.

## TDD

Each test was written first and seen failing before its fix: the
`worktree_add_path` tests (ImportError), `test_branch_practice.py`
(ImportError), and the guard tests (3 failed, 32 passed, before the handler
change; 35 passed after).

## Verification

Separate pytest runs: tests/unit/core 4164 passed; unit/daemon 3331 passed
and the 2 known `test_paths_diagnose_venv_start` failures; unit/scripts 614
passed; handlers/pre_tool_use 12132 passed and 1 failure,
`test_project_containment.py::TestProjectRootDoublePatchDoesNotLeakAcrossFiles`
(a child pytest exits 3; the same child's tests pass when run directly, 42
passed, and it touches none of my files, so I believe it is the PYTHONPATH
artefact, but I did not run it on main to prove it); session_start,
post_tool_use and worktree_create 2002 passed; the three named integration
files 414 passed. Autofix run; format, lint, type_check, error_hiding,
magic_values, semgrep, plan_qa, docs_qa all pass (semgrep first flagged
`is_relative_to`; fixed with `path_is_relative_to`).
