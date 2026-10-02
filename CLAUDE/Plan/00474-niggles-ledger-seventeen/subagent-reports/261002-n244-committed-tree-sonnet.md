# N244: the plan QA commit gate judges the tree the commit records

Branch `worktree-n244-committed-tree`. Scope: the plan QA commit gate only.

## Root cause on main

`plan_qa/context.py` `_tree_and_readme` (def at line 128 on main) built the
tree with `PlanTree.scan` over the disk (`PlanTree.scan(plan_dir, ...)`,
lines ~143-148) and read the README and the archive README with
`readme_path.read_text()` / `archive_path.read_text()` from disk. `PlanTree.scan`
itself (`plan_qa/model.py:605` `root.is_dir()`, `:612` `root.iterdir()`,
`_load_plan_folder` `plan_md.is_file()` / `plan_md.read_text()`,
`_scan_journal` `iterdir`) is disk-only. `row_folder_bijection._link_findings`
(`checks/row_folder_bijection.py:104-105`) tested `target_parent.is_dir()` on
the disk. `staged_context` fed all of that to a commit gate, so after
`git rm -r --cached <plan folder>` the folder stayed on disk, a README row
linking to it resolved, and the gate allowed a commit whose tree has a dangling
row. The write-up's names all exist on main and are accurate.

## Fix

- `utils/git_facts.py` `GitFactsBase` (the existing shared git-facts class; no
  committed-tree helper existed on main, so it was extended, not duplicated):
  `index_listing(prefix)` is one `git ls-files -s -z -- <prefix>` per prefix,
  memoised, gitlinks skipped; `index_texts(listing, paths)` loads every wanted
  blob.
- `utils/git_repo.py` `read_blobs`: one `git cat-file --batch`, read as bytes
  (`run_git` decodes lossily, which would shift the size-prefixed reply after
  any non-UTF-8 byte). Declines the optional index lock like `run_git`. Returns
  `None` for any unreadable state.
- `plan_qa/tree_view.py` (new): `TreeView` protocol (children, is_dir, is_file,
  read_text), `DiskTreeView`, `IndexTreeView`. `IndexTreeView` takes `empty_dirs`
  because git cannot record an empty directory.
- `plan_qa/model.py`: `PlanTree.scan(..., view=)` runs unchanged over either
  view; `PlanTree` carries its `view` (excluded from equality) and exposes
  `is_dir`.
- `plan_qa/context.py`: `staged_context` builds the tree and READMEs (main and
  `Completed/` archive index) from the index for a bare commit. Costs two git
  spawns however many plan folders exist (`ls-files -s`, `cat-file --batch`).
  `sweep_context` and `edit_context` still read the disk.
- `checks/row_folder_bijection.py`: `_link_findings` asks `tree.is_dir`.

Behaviour kept:

- Unreadable states fall back to the disk exactly as before (`index_listing` or
  `index_texts` returns `None`, or the plan dir path is outside the project
  root). Fail-open stays fail-open; `FileNotFoundError` still becomes the
  existing "plan directory does not exist, checks skipped" advisory.
- Archive directories (`Completed/`, `Cancelled/`) that exist on disk but hold
  no tracked file are kept as existing: git cannot record an empty directory,
  and without this every project keeping an empty archive dir would be blocked
  by `structure-archive-dirs` on a state no commit could fix. Found when the
  existing gate tests went red after the switch.
- A pathspec commit (`git commit <paths>`) keeps reading the disk; see below.

## Tests (red first)

`tests/unit/handlers/pre_tool_use/test_plan_qa_commit_gate.py`
`TestJudgesTheCommittedTree`: the reproduction (`git rm -r --cached` plus a
surviving README row) was ALLOW before the fix (red, confirmed), now DENY on
`row-folder-bijection`. Also: an unstaged disk-only README edit does not rescue
it; removing the row in the same commit is allowed even with the row back on
disk unstaged; a folder deleted on disk but still staged is not missing.
Further: `tests/unit/plan_qa/test_tree_view.py` (new), `test_context.py`
`TestStagedContextReadsTheCommittedTree` (index vs disk, staged text, archive
index merge, empty archive dir, pathspec reads disk, plan dir not recorded,
both fallbacks, one listing and one batch read for an 11-folder tree),
`tests/unit/utils/test_git_facts.py` (`TestIndexListing`, `TestIndexTexts`),
`tests/unit/utils/test_git_repo.py` (`TestReadBlobs`). Four existing
`test_context.py` tests and the gate tests that relied on an unstaged scaffold
now commit it first, since the gate reads the index.

## Not covered (residual disk readers, follow-ups)

Checks that open files themselves instead of asking the tree still read the
disk on a commit: `path_existence.py:78`, `plan_doc_size.py:135-140`,
`journal_entry_ordering.py:166-201`, `same_commit_plan_doc.py:85`,
`checks/common.py:127` and `:311-329` (journal day-file lookups). Each is a
smaller gap than the tree/README one but is the same class. Also not handled:
operations earlier in the same Bash command (`git add x && git commit`), which
the gate never sees applied.

## Docs QA (follow-up)

`docs_qa/context.py` builds its staged view from `GitFactsBase.staged_changes()`
and `staged_file_text` (lines 133-154), so changed documents are already read
from the index, but the corpus walk (`docs_qa/corpus.py`, via
`git_visible_paths`, one `ls-files --cached --others` call in
`utils/git_repo.py`) lists disk-visible files, including untracked ones. It
would need: the corpus path set taken from `index_listing`, any existence test
a docs check makes routed through a `TreeView` (`IndexTreeView` is generic, not
plan-specific), and document text from `index_texts`. Which docs checks test
existence on disk was not audited here, and the N53-branch check names in the
write-up (`pointer-resolves`, `quote-drift`, `plan-promotion-disposition`,
`rules-file-orphan-shrink`) were not verified present on main.

## N245 and N246

Neither named function (`judged_views`, `recorded_content`, `reads_index`,
`includes_index`, `staged_lint_gate`) exists on main (grep over src and tests),
so both are written against branch code. What this change gives them:

- N245 (pathspec commit judged on index plus named paths). Under
  `git commit <paths>` git records HEAD with the named paths replaced by their
  working-tree content, ignoring other staged changes. That is a listing
  (`git ls-tree -r HEAD`, minus deleted named paths, plus named paths) and texts
  (named paths from disk, the rest from `read_blobs`), which `IndexTreeView`
  already accepts. Straightforward: one new constructor path in
  `_committed_view`, and `staged_context` stops falling back to the disk for
  pathspecs. On main the pathspec handling is `GitFactsBase.staged_changes`
  (`git diff HEAD -- <paths>`, `utils/git_facts.py:103-112`), already correct.
- N246 (same-command `git add` as two partial trees). The overlay view is again
  `IndexTreeView` over `index_listing` plus the added paths, with the added
  paths' text read from the working tree. The tree half is straightforward; the
  hard half is unchanged: parsing the `git add ... && git commit` command to get
  the added paths, which main has no code for (`extract_commit_pathspecs` only
  parses the commit). Moderate, and only worth doing after N245's overlay.

## QA

Targeted tests (plan_qa, the CLI plan-qa, the gate, git_facts, git_repo): 1009
pass. Black (py311), ruff check, mypy and pyright on every touched `.py` file:
clean. `./scripts/qa/llm_qa.py changed --allow-unmapped`: 35 of 37 pass. The
first run caught three real issues, all fixed: `error_hiding` (two
return-None-on-error shapes, now a precondition check and the `run_git`
convention), `semgrep` `pathlib-quadratic-containment` (now
`path_is_relative_to` / `path_relative_to`), and
`tests/unit/daemon/test_cli_plan_qa.py::TestCheckStaged::test_clean_stage_exits_zero`
(its scaffold was never staged; it now commits it first). The two remaining
failures are in files this branch does not touch: `docs_qa` (3 advise findings
duplicating blocks between plan 00479's PLAN.md and plan 00480's
`ARTEFACT-00479-AS-FILED.md`) and `generated_doc_drift` (378 lines of
`.claude/HOOKS-DAEMON.md`). Four touched modules are `too-broad` to map to tests
(`context.py`, `model.py`, `git_facts.py`, `git_repo.py`), so the coordinator's
full gate must cover them.
