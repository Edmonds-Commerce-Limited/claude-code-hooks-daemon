# GitHub #68 / ledger N293: absolute glob under a literal prefix

Branch `worktree-gh68-glob-prefix`. Addresses #68.

## Root causes

**Main route (both guards).** `bounded_recursive_glob`,
`src/claude_code_hooks_daemon/utils/shell_expansion.py` (the `is_root` block).
`_expand_glob_token` (`utils/secret_file_matching.py`, the absolute-token branch
building `search_specs`) splits an absolute token into `(anchor, rest)`, so the
walk base is `/`. The refusal counted wildcard segments over the whole pattern
and ignored the literal directory in front of them.

**`"$x"$F/*/*`.** `_tokenise` (`secret_file_matching.py:429-443`,
`_TOKEN_PATTERN` at 446) splits on quotes and `$`, so `"$x"/tmp/F/*/*` yields the
fragment `/tmp/F/*/*`, a root-absolute token. The issue calls that a path the
shell never touches; that is wrong. If `$x` is empty or unset the word really is
`/tmp/F/*/*`, so the absolute token is reachable. The decoded-word stream
(`iter_normalised_shell_words`, collapsing `"$x"` to `*`) separately yields
`*/tmp/F/*/*`, relative to the payload cwd, which is the strict reading. Both
are judged. Nothing in the tokeniser needed changing; once the prefix walk is
cheap, both forms are judged on what they reach. Placing the verdict on one
reading only would drop the other, so the deny stays possible for both (pinned
by tests below).

**Comment route 1 (written script content).** Not reproducible on this branch.
I ran the issue's seven table lines through `SecretFileGuardHandler` as `Write`
and `Edit`, for `.bash`, `.sh` and extension-less shebang files, with and
without a payload cwd, and process cwd `/`: all 48 combinations allowed on
unmodified main (`untracked/scratch/route1b.py`). I found no use of the process
cwd (`getcwd`, `Path.cwd`, `abspath`) in `secret_file_matching.py`,
`shell_expansion.py`, or either guard; `_expand_glob_token`'s docstring and
bases (lines 2349-2394) already exclude it since b39b8f8fc. The comment was
written against 3.67.0. Regression tests pin all 7 lines x 3 file names x
Write/Edit x cwd/no-cwd, plus the same lines as Bash commands.

**Comment route 2 (grep regex).** Allowed on main for both guards. Regression
test added.

**PermissionError on an unreadable sibling.** `cat $F/*/x`: `_select_wildcard`
descends into each directory sibling, `_select_literal` runs `lstat` on
`sibling/x`, which raises EACCES for a directory without search permission;
`_record` collects it and `_expand_glob_token` raises it (the N101 round 9
contract), denying. The container runs as root, so the tests inject EACCES at
`Path.stat`/`Path.lstat`.

## Fixes

1. `bounded_recursive_glob`: when the base is the root and an existing literal
   prefix precedes a wildcard, the walk is rebased onto that prefix and the
   root refusal does not apply. The prefix is judged by `os.path.realpath`: one
   that resolves back to `/` (`/usr/..`, a symlink to `/`) narrows nothing and
   is refused as before. `**` is unchanged (still refused at an unnarrowed root,
   still entry-capped under a prefix). New helpers `_leading_literal_parts`,
   `_is_filesystem_root`.
2. Shallow prefix cap: none added. A walk below `/usr`, `/home` and similar is
   non-recursive, so its cost is bounded by the per-entry deadline, which the
   walk already checks and which raises `TimeoutError` (fail closed). A `**`
   walk keeps the 2000-entry cap. A second cap would turn `cat /usr/*/*` into a
   deny on every real host without protecting against anything the deadline
   does not.
3. Unreadable sibling: `_select_literal` yields the fully named candidate when
   the lookup fails with EACCES/EPERM, a wildcard chose the directory, and only
   literal components remain. The caller then judges the path by name, exactly
   as for a readable file. A protected name is still denied (test: artefact
   name inside the locked sibling denied through `_expand_glob_token`). Kept as
   errors: a directory that cannot be LISTED (its entry names are unknown, so a
   protected one cannot be ruled out, and a privileged `sh -c` could read it),
   a path the word names outright (pinned by the existing
   `test_permission_denied_directory_in_the_glob_path_denies`), and any other
   errno (EIO, joined-path ENAMETOOLONG). Detection of a readable protected file
   is untouched: it lives in a listable directory.

## Tests (`tests/unit/utils/test_glob_literal_prefix.py`, 129 tests)

Allowed: `cat F/*/*`, `cat F/*/*/*`, `for x in a b; do cat "$x"F/*/*; done`
(quarantine); `ls F/*/*-release` and the loop form (secret); the 7 route-1 lines
(Write/Edit/Bash); the grep regex (both guards); `cat F/*/x` with a locked
sibling (both guards).

Denied: a quarantine artefact in `F/a` via `F/*/*`, two levels down via
`F/*/*/*`, via the `"$x"F/*/*` loop, and via `"$x"a/*` (variable as wildcard
under the payload cwd); a protected file under the prefix through the secret
guard's filesystem route (`_expand_glob_token` and the chain); `cat /*/*`,
`cat /**`, `cat /*/*/*` at the real root; patterns `*/*`, `**`, `*/*/*`,
`**/x` at the root; `usr/../*/*` and a symlink-to-root prefix; an unlistable
directory; EIO; a named path in a locked directory; a protected name in a
locked sibling.

Existing suites: `tests/unit/utils`, the quarantine and secret guard handler
suites: 6331 passed, 1 skipped (non-root permission test).

## Repro script on this branch

Run with the worktree's `src`: every case in `gh68_repro.py` is `allow` for
both guards, including the three that denied on main (`cat $F/*/*`,
`ls $F/*/*-release`, `for x in a b; do cat "$x"$F/*/*; done`).

## QA

black (py311), ruff, mypy on the two touched files clean. pyright on the test
file reports only an unresolvable `pytest` import (the worktree's pyright cannot
find the venv; unrelated to the change). `llm_qa.py changed`: 36 of 37 pass; the
failure is `docs_qa` with 3 advise-level `duplicate-block` findings between
Plans 00479 and 00480, files this branch does not touch.
