# Plan 00614: secret-guard link gaps, test-first fix

Branch `agent-a13d7c8504105d4c9-aeae03b4`. No real protected file was read; every
fixture is synthetic (a temp primary checkout with untracked dummy files named like
a default protected name, assembled in code, content DUMMY; a registered
`git worktree`; relative file and directory links; process cwd `/`; payload cwd the
worktree; project root parametrised over worktree and primary).

## Commits

1. `618cc3f21` Task 1.1 RED: `tests/unit/handlers/pre_tool_use/test_secret_file_guard_link_resolution.py`.
   33 cases failed before any fix (17 closed by the gap 1 fix, including a relative
   Grep `path`; 7 by gap 2; 9 by gap 3, including the fail-closed link-to-clean-outside
   case); 34 controls passed before and after.
2. `94a46e5b3` Task 2.1 (gap 1). Then gaps 2+3 and the release note in a third commit.

## Fixes

- **Gap 1** (`utils/secret_file_matching.py`): `_realpath_if_resolvable` resolves when
  ANY component is a link (realpath of the spelled path vs its normpath), gated by
  one `os.path.lexists` (prose / NUL / over-long words cost one call and never raise;
  a dangling final link is still resolved). New `_link_targets(token, cwds)` places a
  relative word under each `effective_cwds` entry and still the process cwd, so
  nothing judged before is judged less. Both call sites (`_token_mention`,
  `find_protected_mention_strict`) use it; the strict variant now computes cwds even
  without an index. `is_grep_pattern_only_mention` takes `cwd` (else
  `grep <protected-name> link` was exempted as a pattern-only mention). Handler
  (`secret_file_guard.py`): a relative Read/Write/Edit/Grep path is also judged
  placed under the hook cwd, and `_directory_reach` gets the placed path. The
  error-hiding exclusion for the removed `except OSError` was deleted.
- **Gap 2** (`utils/protected_file_index.py` `find_under`): a root lexically inside
  the project whose realpath is a directory outside it answers `patterns[0]`
  (precedent: `_is_wildcard_filter_over_foreign_cwd`). Unreadable target fails
  closed (`path_is_dir(..., unreadable_means=True)`). A root outside the project as
  spelled is unchanged (no new denial of `grep -r x /usr/...`).
- **Gap 3** (`glob_matches`, `directories_matching`): when the glob's own text names
  a directory before its first wildcard, that directory is realpath-ed; inside the
  project the glob is also matched with the link resolved, outside it the glob is
  not vouched for (deny; for a trailing-slash glob the link directory is handed to
  `find_under`, which denies). No filesystem expansion (the index's "no walking"
  rule); a glob with no literal directory (`*.py`) costs no syscall.

## Verification

Targeted pytest over every secret-guard unit suite (10 guard files, secret_file_matching
x4, protected_file_index, recursive_search, exemptions_reserved_words) plus the 7
integration files that mention the guard: 2856 passed, 3 skipped (the 3 are the
new file's primary-root skips). ruff, black --check, mypy clean on the three touched source files.

## Detector (DBF step 2)

No practical code-reading detector: the class is "a filesystem query on a relative
path while the process cwd is not the command's cwd", which depends on data flow
(where a string came from) that a lexical rule cannot see. Recorded as a toolchain gap;
fixed conventionally with the RED tests as the regression net.

## Residuals (deliberately not fixed)

- A plain absolute root in another checkout with no link (`grep -r x /path/to/primary`)
  is judged against this project's index only, as before.
- `grep -R` / `rg -L` over an in-project tree that CONTAINS a link out: the root is
  in-project, so it is not caught here (the filter-relaxation path already denies
  link-following flags for wildcard filters only).
- No index yet (daemon just started): searches and globs are allowed with the
  existing advisory.
- A glob spelled `dlink/../*` is placed lexically (normpath), not physically.
- The new fail-closed rule also denies `cat outlink/*` where the outside directory
  holds nothing protected (pinned by a test; that is the intended trade-off).
