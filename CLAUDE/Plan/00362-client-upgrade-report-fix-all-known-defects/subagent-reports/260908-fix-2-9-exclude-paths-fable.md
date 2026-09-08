# Task 2.9 report: docs QA and plan QA honour `daemon.exclude_paths`

**Defect**: D18 (Plan 00330 Task 1.4, MEDIUM).
**Branch**: `agent-ae7f5517165088169-4a469448`.
**Commit**: `406cbeef` (implementation, tests, guidance, release-note callout).
**Model**: Fable 5.1.

## What changed

Both QA subsystems now consult the project-wide `daemon.exclude_paths`
through the same `utils/path_exclusion` matcher the twelve content blockers
use. Coordinator decision applied as stated: honour it; a fixture tree that
must keep producing findings is declared explicitly by staying OUT of the
list.

### docs QA

- `DocumentationPolicy.exclude_paths: tuple[str, ...]` (new field) and a
  `policy_from_config(..., exclude_paths=)` keyword. The globs travel WITH
  the policy for the same reason the vendor truth does (Plan 00331): docs
  QA's scope judgement reads the policy, so a value injected only onto the
  handler instance could never reach it.
- `handlers/registry.py` copies `project_exclude_paths` into the policy;
  `cmd_docs_qa` copies `config.daemon.exclude_paths`.
- `corpus.is_project_excluded(rel_path, policy)` (new, public) is consulted
  by `_is_excluded` (so `is_in_scope`, `iter_corpus_paths`, the corpus build
  and every check that uses `is_in_scope`), by `is_lintable_path` BEFORE its
  generated-docs-manifest and module-`CLAUDE.md` arms (which bypass
  `is_in_scope` and would otherwise re-admit an excluded path), by
  `sweep_context`'s shared markdown walk (per-file post-filter) and by
  `staged_context` (an excluded staged path never enters the view).
- Entry points covered: `docs_qa_edit` (matches() is false), the commit
  gate (staged view), the session sweep (corpus + walk), and the CLI in all
  three modes.

### plan QA

- `CheckContext.exclude_paths: tuple[str, ...]` (new field); all three
  context builders take `exclude_paths=`; handlers pass
  `self._project_exclude_paths` (already injected by the registry on every
  handler), `cmd_plan_qa` passes `config.daemon.exclude_paths`.
- `plan_qa.runner.run_stage` is the ONE place the exclusion acts: an EDIT
  whose `file_path` is excluded runs no check at all; otherwise findings
  whose `path` matches are dropped. Findings are not uniform about `path`
  (project-relative for document checks, bare plan-folder name for tree
  checks, absolute at EDIT), so `_excluded` tries each form and re-roots the
  folder-name form under `plan_dir_rel`.
- `plan_qa_edit.matches()` additionally short-circuits via
  `handler_excludes_path`, so an excluded plan file never even reaches the
  would-be-content read.
- **Design decision worth knowing**: the plan tree and README index are NOT
  filtered. A first cut removed excluded folders from `tree.folders`; that
  made `row-folder-bijection` report the still-present README row as "row
  with no folder" (a `path=None` BLOCK finding that no path filter can
  drop), and in a real repo would desynchronise `stats-recount`. Acting on
  findings rather than facts keeps every whole-tree invariant seeing the
  tree as it is. Consequence: a pathless finding that mentions an excluded
  plan only in its message (e.g. a number collision involving it) still
  surfaces — deliberate, since collisions are index-wide facts.

### Guidance

- `docs_qa_sweep.get_claude_md()` and `plan_qa_sweep.get_claude_md()` each
  gained a paragraph stating the exclusion and the "declared by not being
  listed" rule.
- `docs/guides/HANDLER_REFERENCE.md`: Path Exclusion section names the six
  handlers and both CLIs (and warns that the `handler_excludes_path` grep
  hint will not list them); each of the six handler sections' "Fires when"
  says what the exclusion does on that surface.
- Release-note callout
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/13-docs-and-plan-qa-honour-exclude-paths.md`
  (Plan 00362, audience: operators) tells operators to review their list
  before upgrading.

## Tests (written first; RED confirmed for the right reasons, then GREEN)

- `tests/unit/docs_qa/test_policy.py`: default `()`; copied as a tuple.
- `tests/unit/docs_qa/test_corpus.py`: `is_in_scope` (unanchored and
  root-anchored patterns), `iter_corpus_paths`, `is_lintable_path` for
  both wider arms.
- `tests/unit/docs_qa/test_context.py`: sweep walk and staged view.
- `tests/unit/plan_qa/test_context.py`: carried on all three surfaces;
  tree stays complete while sweep findings about the folder disappear.
- `tests/unit/plan_qa/test_runner.py`: relative path, folder-name path,
  pathless kept, EDIT of excluded file runs no check, nothing configured
  changes nothing.
- One handler test each for the six handlers, one registry test (the value
  reaches `_documentation.exclude_paths`), and two CLI tests each for
  `docs-qa` and `plan-qa` (sweep skips; lint of an excluded file).
- Result: 1385 passed across `tests/unit/docs_qa`, `tests/unit/plan_qa`,
  the six handler suites, both CLI suites and `test_registry.py`.

## QA run

- `ruff check` clean, `black --check` clean, `mypy --strict` clean on
  every touched source file (73 modules checked).
- `scripts/qa/llm_qa.py handler_reference doc_truth doc_snippets`: 3/3
  passed. There is no separate plan step in `llm_qa.py`; the plan side is
  the `plan-qa` CLI, which was linted against the ticked Plan 00330 PLAN.md.
- `docs-qa --lint` clean on `HANDLER_REFERENCE.md` and the callout.
- Daemon NOT restarted (as instructed); no `sed`, no stash, no destructive
  git.

## Repo's own `daemon.exclude_paths`

`.claude/hooks-daemon.yaml` declares NO top-level `daemon.exclude_paths`
(only per-handler `exclude_paths` under `sensitive_content` and
`secret_file_guard`, which this change does not read). So no test fixture
had to move and the repo's exclusion did not need narrowing — nothing to
report on that branch of the instructions.

## Incidental findings (not fixed here)

- `cmd_docs_qa --lint` crashes with a `ValueError` at `cli.py:5032`
  (`lint_path.relative_to(project_root)`) when `--project-root` is given
  as a RELATIVE path such as `.`: `resolve_tree_root` returns it
  unresolved while `lint_path` is resolved. `cmd_plan_qa` does not have
  this problem. Pre-existing; an absolute `--project-root` works.
- `scripts/qa/llm_qa.py` hard-codes `untracked/venv/bin/python`, which the
  fingerprint-keyed venv layout (Plan 00358) no longer creates; a symlink
  `untracked/venv -> venv-<fingerprint>` was needed to run it in the
  worktree.
- `./scripts/setup_worktree.sh` CREATES a worktree and cannot be run from
  inside an existing one; the venv was created by calling the same
  `ensure_venv` helper directly and then `uv sync --extra dev`, because
  `ensure_venv` alone installs no dev tools (no pytest/ruff/mypy).
- `ruff format --check` under this venv's ruff 0.15 flags 71 pre-existing
  files (HEAD versions included); the project formats with black, which is
  clean. Not touched.
