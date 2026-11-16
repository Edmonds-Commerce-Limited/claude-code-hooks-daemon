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

## Independent review follow-up (review-614): the design hand-over

The review found no loosening and no fail-open. It did find four in-scope items:

- **F1:** a `cd` inside `( )`, `{ }`, `if`, `$( )`, `bash -c` or `env -C` is not tracked.
- **F2:** a wildcard inside a link's own name (`dl*/*`) escapes the check.
- **F4:** a link-out deny message never names the link.
- **F5:** cost grows with the number of `cd` targets times the number of words.

The agent that produced the design reached its context budget before writing any code.
All four are now closed; see the next section. The design and the list of tests to write first are
in the handoff (untracked, `untracked/scratch/261116-a70d6790445dbefba-handoff.md`).
The design has three main points:

- `recursive_search._reads` has its own sequential `cd` tracking, and that tracking
  needs the F1 fix too.
- A `cd` seen inside a group must add a directory, not replace the current one.
  Otherwise `(cd clean && true); cd inner && cat ilink` becomes a loosening.
- An overflow past the cap must return a positive finding, not raise. Every exception
  ends up as the advisory ALLOW.

### F3 (pre-existing, not fixed here; for separate filing)

These commands read every file under ROOT, protected ones included:

- `find ROOT ... -exec cat {} +`
- `find ROOT -exec head {} +`
- `find ROOT -type f | xargs cat`

All three are ALLOWED on origin/main and on this branch. That holds for a link out of
the project (`find -L dlink`, `find dlink/`) and for an in-project protected file
(`find own -type f -exec cat {} +`).

`recursive_search` treats `find` only as a feeder for a grep-family `-exec` or `xargs`.
A reader that is not grep therefore never reaches `find_under`.

Proposed fix: treat `find ROOT ... -exec|-execdir|-ok <reader>` and
`find ROOT ... | xargs <reader>` as a recursive read of ROOT, judged by `find_under`.
The cost is the false denies `grep -r` already pays. For example,
`find . -name '*.py' -exec wc -l {} +` would be denied in a tree that holds a
protected file.

`scripts/qa/dangerous-invocation-corpus.yaml` has no row for this. File it as F-BYPS
or as UNCOVERED-accepted. It is now Plan 00615.

## Review follow-up implemented: F1, F2, F4, F5 closed

The tests came first (commit f0592eb94, 63 RED). Each fix was then committed green. The
shapes in the handoff's test list all have tests in
`test_secret_file_guard_link_resolution.py`, run with both the worktree and the primary
as the project.

- **F1 (commit 50e598630).** Both cwd trackers changed.
  - `effective_cwds` walks the shell words of each segment and finds a move after
    `( { ! if then else elif do while until time`, after an assignment, or glued to `$(`
    or a backtick. It also walks a quoted `bash -c` or `"$( )"` body (to depth 4) and
    reads `env -C`/`--chdir` and `git -C`.
  - A quoted body that the separator split leaves unbalanced is read without quotes,
    and the project root is added.
  - A relative step is joined to the last directory in the chain. It is also joined to
    every directory already known to exist, and each such join is kept only if it is a
    real directory. That keeps `(cd clean && true); cd inner && cat ilink` and
    `cd clean && (cd x); cd ../inner && cat ilink` denied.
  - In `recursive_search._reads`, a `cd` inside a subshell replaces the directories, as
    it does at the top level. When the subshell closes, its directories are added to
    the outer set rather than dropped. So `(cd clean && grep -r hello .)` and
    `cd clean && grep -r hello .` read `clean` only, and are allowed in a tree whose
    hook cwd would be denied.
  - **Verdict change:** an unplaceable cd (`cd "$D"`, `cd $(pwd)/x`, `cd -`, a bare `cd`)
    now reads from the project root, every named target and the hook cwd. Before, it
    dropped relative roots. Three `test_recursive_search` tests and one anchoring test
    were updated to the fail-closed behaviour. The N465 prefilter test now runs the real
    walker with the gate forced open, so it still pins gate soundness. The gate is
    widened only to `env`+`-C`/`chdir` and `git`+`-C`, which keeps
    `make -C src/module` untokenised.
- **F5 (commit 50e598630).**
  - `effective_cwds` returns a `CwdSet` (a tuple subclass). `link_dirs` holds the first
    16 directories that exist, and only those are resolved word by word.
  - Past 16, `CwdSet.could_be_link` lists each directory once. A relative word whose
    first component is `..`, or is or glob-matches a link, is a positive finding. So is
    a deeper word whose real path differs from its spelling. The finding is returned,
    never raised.
  - **Measured by call count, not time:** 200 absent `cd` targets × 3000 words cost no
    more than 3× the lexists calls of a single `cd`. The 3× allows for the scan's own
    deadline fallback, which also runs on main. On the tip it was about 201 calls per
    word.
- **F2 (commit ce62a08db).**
  - `ProtectedFileIndex._wildcard_links` lists the resolved literal parent of the first
    wildcard component once.
  - A matching link that leads out of the project denies.
  - Any other matching link is read again with its real directory substituted, which
    covers the case where the project is the primary and the link sits outside it. A
    search reports that directory as the link spells it.
  - `*/*` stays allowed: a wildcard-only first component is not expanded.
- **F4 (commit 5e7a82a66; the target path was dropped from the message in the follow-up commit).**
  - `_build_deny_result` gets the cause from `ProtectedFileIndex.link_out_of`, the same
    test the decision uses. It applies only when the matched token does not spell a
    protected path.
  - The cause names the link, says the index lists only this project, and says to run
    the command from the checkout that holds the target. On the search route it
    replaces `_SEARCH_REMEDY`.
  - It neither prints the target's absolute path nor suggests the real path. A path
    outside the project is judged by name only, which is the weaker check, and a test
    asserts that the outside directory does not appear in the reason.
  - A deny caused by the F5 overflow gets its own sentence.
  - The decision is unchanged.

Advisor follow-up, fixed in the last commit:

- **Unwrapping could lose a search the tip saw.** `FOO=$(true) grep -r x .`,
  `` D=`pwd` grep -r x . ``, `grep -r foo\(\)` and `grep -r x dir\ \(1\)` placed no root
  after unwrapping. The segment as written is now judged beside its unwrapped form, so
  unwrapping can only add reads. All four are pinned in `test_recursive_search`.
- **Options before `-C` hid the move.** `env -u HOME -C inner cat ilink` and
  `git -c k=v -C inner diff ...` were missed. `-C` is now searched up to the next
  operator.

Evidence:

- **Differential run.** The reviewer's `probe614.py` was run over its six case files
  plus a new `cases614g.json` (25 wrapped and unwrapped search shapes), 216 cases in
  all, comparing e26ca21da with this tip. No case went from DENY to ALLOW, the new tip
  denies 29 more, and no call raised. The runner is `untracked/scratch/diff614.sh` in
  the worktree.

- **CPU time.** The reviewer's `probe614t.py` with 200 distinct `cd` targets and 3000
  words, measured as `process_time` on a host at load average about 9.5:

  | Tree        | CPU time |
  | ----------- | -------- |
  | main        | 5.14 s   |
  | e26ca21da   | 9.64 s   |
  | this branch | 5.11 s   |

  The 2000-word shape: 0.99 s on main, 0.90 s here.

Residue, not fixed:

- `grep -r x *` through a link out is still allowed: a bare wildcard names no place and
  is skipped by design.

- A `cd` inside a shell function body is not tracked by the search route.

- Past the cap, a relative `cd` is joined to only the first 17 existing directories.

- `time -p grep ...` is unjudged by the search route, as it was on the tip (`-p` is
  read as the head).

- `git -C X grep` is still treated as relocated and unjudged by the search route. It
  was the same on main.

- `make -C` is not tracked.

- In overflow, `glob_matches` still scans every lexical base. This is main's baseline
  cost, plus one scandir per existing base for F2.

- A `case` arm `pat)` is stripped like a subshell closer. That can add, but never drop,
  a directory.
