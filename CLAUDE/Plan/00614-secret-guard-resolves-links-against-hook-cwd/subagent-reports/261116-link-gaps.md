# Plan 00614: secret-guard link gaps, test-first fix

Branch `agent-a13d7c8504105d4c9-aeae03b4`. No real protected file was read. Every
fixture is synthetic: a temp primary checkout holding untracked dummy files (content
DUMMY) named like a default protected name, with the name assembled in code; a
registered `git worktree`; relative file links and directory links. The process cwd
is `/`, the payload cwd is the worktree, and the project root is parametrised over
the worktree and the primary. The tests are in
`tests/unit/handlers/pre_tool_use/test_secret_file_guard_link_resolution.py`.

## Commits

- `618cc3f21` is Task 1.1, the RED proof. Before any fix 33 cases failed and 34
  controls passed. The controls passed again after the fix.
- `94a46e5b3` is Task 2.1, gap 1.
- `3e83e7c22` is Tasks 2.2 to 2.4: gaps 2 and 3 and the release note.
- `99d61ac98` merges origin/main, which brings in Plan 00612.
- A follow-up commit adds the exemption fixes, the extra tests and this report.

## Overlap with Plan 00612 (merged to main mid-task)

00612 realpaths a glob's literal directory prefix in `_glob_parts` and lists
symlinked directories for trailing-slash globs. On origin/main alone, the RED file
fails 29 of its cases:

- **gap 1** (16 cases) is fully open;
- **gap 2** (8 cases) is open whenever a link leads out of the project, plus a
  relative Grep `path`;
- **gap 3** (5 cases) is open when the project root is the worktree, so the link
  leads out. 00612 closed gap 3 when the target is inside the project, so
  project = primary.

I kept 00612's `_glob_parts` resolution and dropped my own duplicate in-project
substitution. Only the "link leads out of the project" rule was added, as
`_link_out_directory`, on top of 00612's loops.

## Fixes

### Gap 1: `secret_file_matching.py`

- `_realpath_if_resolvable` now resolves when any component of the path is a link.
  It compares the realpath of the path as spelled with its normpath.
  - It is gated by one `os.path.lexists`, so a word that is not a path costs a
    single call and never raises.
  - A dangling final link is still resolved.
- The new `_link_targets(token, cwds)` places a relative word under each effective
  cwd and still under the process cwd.
- Both callers use it: `_token_mention` and `find_protected_mention_strict`. The
  strict variant now computes cwds even when it has no index.
- The hook cwd is now passed to three exemptions:
  - `is_grep_pattern_only_mention`, which previously exempted `grep <protected-name> link`.
  - `is_exempt_invocation`, which previously let `ansible-playbook --vault-password-file <pw> link1.txt` through.
  - The scan inside `is_encrypted_target_invocation`, which previously let `cat <encrypted-vault> link1.txt` through.
  - Each of the three has a RED test that failed before its fix.
- In `secret_file_guard.py`, a relative Read, Write, Edit or Grep path is also judged
  as placed under the hook cwd.
- The error-hiding exclusion for the removed `except OSError` is deleted.
  `audit_error_hiding.py` passes.

### Gap 2: `protected_file_index.py`, `find_under`

- When a root is inside the project as spelled but its realpath is a directory
  outside it, `find_under` returns `patterns[0]`. This follows the precedent of
  `_is_wildcard_filter_over_foreign_cwd`.
- An unreadable target fails closed.
- A root that is outside the project as spelled is judged as before.

### Gap 3: `glob_matches` and `directories_matching`

- When the directory a glob spells before its first wildcard is a link out of the
  project, `glob_matches` returns `patterns[0]`.
- `directories_matching` hands that link directory to `find_under`, which denies it.
- There is no filesystem expansion, and a glob with no literal directory costs no
  syscall.

### Deny message

The fail-closed denials name `patterns[0]` as the "matched" glob, although no
particular file matched. The release note says so.

## Blast radius and consumers

- The fail-closed rule also covers `quarantine_artefact_read_guard`, which shares
  the index and `recursive_search`. Its suite is green.
- No directory symlink exists in this worktree or in any other worktree up to
  depth 4. `worktree_create` seeds file links only, such as `block-words.secret`
  and `init.sh`, so worktree agents' ordinary `grep -r` and globs are unaffected.
- `cat outlink/*` is denied when the outside directory holds nothing protected. A
  test pins this: it is the intended trade-off.

## Verification

- Targeted pytest ran over:
  - every secret-guard unit suite and the quarantine guard;
  - `protected_file_index`, `recursive_search` and `secret_file_matching` (four files);
  - `exemptions_reserved_words`;
  - the release-note tests (`test_release_notes`, `test_unreleased_manifests`,
    `test_pending_release_notes_holding_area`);
  - the seven integration files that mention the guard.
- The result is recorded in the follow-up commit message.
- ruff, `black --check` and mypy are clean on the three source files and the test file.
- The daemon was not restarted and no live check was run. The coordinator owns the
  merge gate.

## Defence Before Fix

- **Class:** a filesystem query, or an exemption scan, on a relative path while the
  process cwd is not the command's cwd.
- **Sweep:** I read every realpath, is_symlink and lexists site, and every
  mention-scan call that has no cwd, in the three modules. There are 6 instances,
  all fixed here:
  - the two `_realpath_if_resolvable` sites;
  - the handler's relative path route;
  - the three exemption scans.
- **No detector:** whether a string is relative to the hook cwd is a data-flow
  property, and a lexical rule cannot see it. This is recorded as a toolchain gap;
  the RED tests are the net.

## Residuals (deliberately not fixed)

- A plain absolute root in another checkout, with no link involved, is still judged
  against this project's index only.
- `grep -R` or `rg -L` over an in-project tree that contains a link out is not
  covered.
- With no index yet, searches and globs are allowed with the existing advisory.
- `dlink/../*` is placed lexically.
- The unreadable-target arm of `find_under` has no test, because the tests run as
  root.
