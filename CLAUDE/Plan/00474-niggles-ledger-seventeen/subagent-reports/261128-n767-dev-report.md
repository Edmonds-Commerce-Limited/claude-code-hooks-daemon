# N767 developer report: one `.scratch-keep` rule

Branch `guard-n767-scratch-keep-marker-predicate`, off `520df6557`, pushed. Commits:

- `5fb9cc78f`: fix and tests.
- `a367bc69e`: error_hiding follow-up, NIGGLES, DESIGN.md, release note 129.
- `c1b0f0164`: review minor 1, the agent guard denies mkdir/mkfifo/mknod of the marker.
- A final commit with review minors 2-5 and this report.

No PR opened.

## Defect, as confirmed (worse than reported)

There were three readings of the marker, and they disagreed:

1. **Entry root, `scratch_verdict.has_keep_marker`:** kept only for `NodeKind.FILE`. A symlinked, dangling, looping or directory marker gave UNCERTAIN. On main, `scratch-sweep --apply` ARCHIVED the pinned entry: the end-to-end test was RED for all four shapes.
2. **Session directory at classification, `scratch_sweep._container_holds`:** `os.path.lexists`. Any kind kept, BUT an `lstat` failing other than ENOENT answered False. The session's children were then judged DISPOSABLE, so this check failed open.
3. **Session directory at apply time, `scratch_archive_apply._session_kept`:** `lstat`, with ENOENT read as absent and every other failure read as kept. This one was already correct.

## Fix

- **`scratch_verdict.marker_keeps(kind: NodeKind | None) -> bool`** is THE rule. Any node named `.scratch-keep` keeps, whatever its kind (FILE, SYMLINK, DIRECTORY, SPECIAL, UNREAD). None, meaning nothing of that name, does not keep.

- **`scratch_verdict.keep_marker_present(directory)`** reads the marker with `os.lstat`, never following a link:

  - FileNotFoundError gives `marker_keeps(None)`;
  - any other OSError is logged through `log_and_continue` and read as UNREAD, so it keeps.

  `_container_holds` (in place of `lexists`) and `_session_kept` both use it.

- **`has_keep_marker(stats)`** passes the walked top-level node's kind through `marker_keeps`. A nested marker does not keep.

- **`scratch_walk.kind_of`** is now public, so the walk and the fresh read map an `lstat` mode to a kind the same way.

- **Reason text:** a symlinked marker's target is not read for the reason, so it is reported as "(no reason given)".

**Why `os.lstat` and not `utils.path_predicates`:** those helpers follow links and turn ELOOP into False, so a dangling or looping marker would read as absent. That is now said in the docstring.

## Review round (independent Opus review: APPROVE, 5 minors, all fixed)

1. **The guard allowed an agent's `mkdir`/`mkfifo`/`mknod` of the marker, and a `Write` below a marker directory.** With the any-kind rule, each of these pinned an entry for ever.
   - `_names_marker` now matches the marker in ANY path component.
   - `_creates_marker_node` denies `mkdir`/`mkfifo`/`mknod` whose operands name the marker. It goes through `peeled_statements`, so wrappers, quoting and options are handled, and a `sh -c` body is covered by the existing recursion.
   - 24 RED cases, including option clusters, long options, `--`, `/bin/mkdir`, `sudo`, `timeout`, `$VAR` paths, `sh -c`, mknod `p`/`c`, and Write/Edit/redirect/touch/rm below the marker.
   - New allow cases: a sibling mkdir, `.scratch-keeper`, `ls`/`cat` below the marker, a commit message, and an echo that only names the marker.
2. **Release note 129 and the DESIGN.md bullet** now say that a marker of any kind, a stray empty directory included, keeps its entry until a human removes it and is reported KEPT "(no reason given)".
3. **The `NodeKind.UNREAD` docstring** now also covers an unreadable keep marker.
4. **The equivalent-mutant DIRECTORY guard in `has_keep_marker`** is dropped. Tests stay green.
5. **The `keep_marker_present` docstring** says why `os.lstat` is used rather than `path_predicates`.

## Tests

- **`tests/unit/core/test_scratch_verdict.py`:**
  - `TestKept`: every kind keeps, and a nested marker does not. This replaces `test_only_a_regular_file_at_the_top_counts`, which pinned the bug.
  - `TestOneKeepMarkerRule`, which covers:
    - `marker_keeps` over every NodeKind and over None;
    - the real-filesystem shapes, regular, symlink, dangling, loop, directory and absent;
    - `lstat` raising PermissionError, NotADirectoryError or OSError, each of which keeps (a spy confirms the rule receives UNREAD);
    - the walk and the lstat agreeing.
- **`tests/unit/core/test_scratch_sweep.py` `TestOneKeepMarkerRule`:**
  - each shape at the entry root and at a session directory, and the two checks agreeing;
  - a symlinked marker's reason is not followed;
  - a nested marker does not keep;
  - an unreadable session marker keeps every child.
- **`tests/unit/daemon/test_cli_scratch_apply.py` `TestAnEntryRootMarkerOfAnyShapeIsNeverArchived`:** uses the real parser, sweep, store and tar. The sibling entry is archived as the positive control; the pinned entry is not. RED on main for all four shapes.
- **`tests/unit/handlers/pre_tool_use/test_scratch_keep_marker_guard.py`:** the review-round cases above.

## QA (targeted only)

- **`./scripts/qa/llm_qa.py changed --allow-unmapped`:** 43/43 PASSED before the review round. `--allow-unmapped` is used because the four unmapped files (`core/scratch_archive_apply.py`, `core/scratch_sweep.py`, `core/scratch_walk.py`, `daemon/cli.py`) are all ones the tool marks `[too-broad]`. It was re-run after the review round; the result is in the final reply.
- **Review-round pytest:** 396 passed over the guard, verdict, sweep, walk and CLI-apply test files.

## Notes

- **Worktree setup:** the worktree was made with `git worktree add`, because `setup_worktree.sh` refuses a branch not named `worktree-*`. Its venv was built with the same `ensure_venv` and `uv sync --frozen --all-extras` steps, inside the worktree, so it is reaped with it.
- **Report location:** R-SUBAGENT-CROSS-WORKTREE-WRITE denies a sub-agent's Write into the main tree's session scratch directory, so this report is filed here, as the coordinator asked.
- **Entry marker added after classification:** the review settled this question with probes. The fingerprint and claim chain renames such an entry back, and nothing is lost.
