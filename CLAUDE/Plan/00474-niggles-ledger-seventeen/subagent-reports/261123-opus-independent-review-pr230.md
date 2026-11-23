# Independent security review: PR #230 (N710, secret guard expands a glob in any path part)

Reviewer: an independent Opus sub-agent, read-only. Branch `fix-n710-secret-guard-glob-later-parts`,
head `636ce6a69`. Only tmp_path dummy fixtures were used. No real protected file, secret word list or
seat store was read.

## Verdict

**Safe to merge on security grounds. The PR improves on main and I found no case it makes worse.
N710 is NOT fully closed.**

- **No security regression.** I ran 332 probe cases. Every one the PR allows, main also allows. The PR
  fails 84 cases and main fails 236; the PR's failures are a strict subset of main's.
- **Fail-closed behaviour holds.** The caps and the error paths deny, as the PR claims.
- **Not fixed.** Several shapes in the same defect class still read a link to a protected dummy, on
  both the Bash route and the Write-script route. They are listed below: findings 1, 2, 3 and 4. All of
  them are pre-existing.
- **Two new non-security costs.** The first is a real false positive in this repository
  (finding 5). Every `CLAUDE/Plan/Completed/*/...` glob is now denied. The second is a roughly 15x
  slowdown on commands with many globbed words (finding 6).
- **Not a merge blocker.** Both costs fail closed, and the workaround is to split the command or name
  paths explicitly. I recommend fixing finding 5 immediately after merge, because it hits routine work
  in this repository.

## Method

- **The PR's own tests pass.** I ran `test_secret_file_guard_glob_later_parts.py`,
  `..._link_resolution.py` and `..._cwd_fail_closed.py` against the PR source: 690 passed,
  11 skipped.
- **Probes.** They live in `untracked/scratch/s-20261121T111743Z-0a12d28f/pr230-review/`, in
  `test_probe_pr230.py`, `test_probe2.py`, `test_probe3.py`, `test_probe4.py` and `test_bashsem.py`.
  - Each ran against the PR source and against main.
  - Each ran in two modes, set through `_snapshots_all_off`:
    - **Conservative** (False).
    - **Defaults certain** (True). This is bash's default globbing, and it is what
      `default_glob_semantics('ls')` answers on this host.
  - Where stated, each also ran with and without the protected-file index.
- **Fixture.** It is the PR's own: `kit/bin/late` is a link to a dummy outside the project. I added:
  - `kit/.hid/late2`, a link in a dot directory;
  - `kit/a/b/late3`, a link two levels down;
  - `kit/dl`, a link to a directory.
- **Real-bash check.** `test_bashsem.py` runs real `bash 5.2.37 --norc` over plain-file copies of
  the tree. It confirms that each reproducer marked "bash-confirmed" really opens the target.

## Findings

### 1. HIGH, pre-existing (same class, not fixed): `nocaseglob` is never modelled

**Cause.** Two things combine:

- `_component_regex` (`secret_file_matching.py:4413`) and `fnmatch` match case-sensitively.
- `default_glob_semantics` (`shell_snapshot.py:61`) only considers `globstar` and `dotglob`. A
  `shopt` in the command makes it answer False, but that only widens dot names and `**`. It never
  widens case.

**Reproducers.** Run from the project root; all are bash-confirmed:

```
shopt -s nocaseglob; cat kit/B?N/late
shopt -s nocaseglob; cat kit/bin/L*
shopt -s nocaseglob; cat kit/[B]in/late
shopt -s nocaseglob; cat K*/bin/late      # glob in the first part
```

**Result.** All are allowed, in both modes:

- on the Bash route, with the index and without it;
- on the Write-script route.

Main allows them too.

**Fix direction.** Use case-insensitive component regexes whenever the command or script can enable
`nocaseglob` (any `shopt`, `-O` or `BASHOPTS`), or whenever bash defaults are uncertain. That change
only widens.

### 2. HIGH, pre-existing (inside the PR's claimed extglob scope): extglob words that are not captured

**Claim tested.** The PR says it reads extglob no narrower than bash. The relevant code is
`_EXTGLOB_WORD` (`:3037`), `_extglob_words` (`:3042`) and `_extglob_regex` (`:4386`).

**Reproducers.** All are bash-confirmed. `shopt -s extglob` is on its own line, because bash parses a
whole line before `shopt` runs, so `;` would be a syntax error. Each command is followed by the word
that `sfm._extglob_words` actually captured:

| Command                                                 | Captured word             |
| ------------------------------------------------------- | ------------------------- |
| `cat "k"it/@(bin\|zz)/late`                             | `"it/@(bin\|zz)/late`     |
| `cat k\it/@(bin\|zz)/late`                              | `t/@(bin\|zz)/late`       |
| `cat kit/@("bin"\|zz)/late`                             | nothing                   |
| `cat kit/@(b@(i)n)/late`                                | `b@(i)n`, the inner group |
| `cat kit/*(@(b)in)/late`                                | `@(b)in`, the inner group |
| `env BASHOPTS=extglob bash -c 'cat kit/@(b@(i)n)/late'` | nothing                   |

The backslashes before `|` in the table only escape the table pipe. The commands themselves contain a
bare `|`, as in the first line of the block below.

```
shopt -s extglob
cat "k"it/@(bin|zz)/late
```

**Result.** All are allowed on both routes, in both modes, without the index. I also checked the
nested form and the `;`-separated spellings with the index, and they are allowed there too. Main
allows all of them.

**Cause, as observed.** `_EXTGLOB_WORD` runs over text produced by `mask_quoted`, and it can begin or
end part-way through a word:

- a quote or backslash earlier in the word yields a truncated, wrong path;
- a quoted alternative yields no capture at all;
- a nested group yields only the inner group, so the "nested group means anything" widening in
  `_extglob_regex` is never reached;
- the `bash -c` body is single-quoted, so it is masked.

**Fix direction.** Fail closed on any unquoted `[?*+@!](`. Take the whole word as the real tokenizer
splits it, dequote it, and widen every extglob component to `.*`. Never use a regex to carve the word
out.

### 3. MEDIUM, pre-existing (same class, not fixed): implicit `dotglob` through GLOBIGNORE or BASHOPTS

**Cause.** `_SWITCHES_OPTIONS` (`shell_snapshot.py:47`) recognises only `shopt` and `-O`/`+O`. It
misses two ways of turning on dot-name matching:

- `GLOBIGNORE=<anything>`, which makes globs match dot names exactly as `dotglob` does;
- `env BASHOPTS=dotglob bash -c ...`.

**Reproducers.** Both are bash-confirmed. `kit/.hid/late2` is a link to the dummy.

```
GLOBIGNORE=zz; cat kit/*/late2
env BASHOPTS=dotglob bash -c 'cat kit/*/late2'
```

**Result, with defaults certain (the normal production state):**

- **Write-script route:** allowed, with the index and without it.
- **Bash route, no index:** allowed. This is the state with a stale or missing index, or a link made
  after indexing.
- **Bash route, fresh index:** denied, but only through the index fallback. The PR's own
  `test_the_bash_route_denies_with_no_index_...` says that fallback must not be relied on.

Main has the same results.

**Not checked in bash.** `env BASHOPTS=globstar bash -c 'cat kit/**/late3'` is allowed by the guard
in the same way, but I did not confirm that bash really reads through it.

**Fix direction.** Make an assignment to `GLOBIGNORE`, or a `BASHOPTS` in the environment, count as
switching options, the same way `shopt` does now.

### 4. MEDIUM, pre-existing (the over-the-cap path brief item): `LinkNames.reaches` misreads `[^...]`

**When this path runs.** `named` (a `LinkNames`) is set only when the project holds more than
`LINK_SCAN_DIRECTORY_CAP` (512) link-holding directories (`scan_project_links`, `:4586`). In that
case only the directory links stay in `_existing`, so after a computed `cd` a word relative to a
link-holding directory is judged by `reaches` alone.

The PR's `crowded` fixture never reaches this path: it asserts `named is None`. I built one that does,
with 520 directories each holding a link, and confirmed `named is not None`.

**Reproducers.** Run after `cd "$D"`, a computed move, with no index:

| Word                                                      | PR    | main  |
| --------------------------------------------------------- | ----- | ----- |
| `b?n/late`, `l?te`, `kit/**/late`                         | DENY  | DENY  |
| `[[:alpha:]]in/late`, `[[:lower:]]ate`, `kit/[^z]in/late` | DENY  | ALLOW |
| `[^z]in/late`, `bin/[^z]ate`, `[^z]ate`                   | ALLOW | ALLOW |

The PR improved the middle row. The last row is still allowed on both routes and in both modes.

**Cause.** `LinkNames._component_matches` uses `fnmatch.fnmatchcase`. Python's fnmatch reads `[^z]` as
"either `^` or `z`", while bash reads it as "not `z`".

I did not run the `[^z]` forms in real bash. The bash manual documents `^` as negation equal to `!`.

**Fix.** Use the PR's own `_component_spells` and `_component_regex` in `LinkNames`. They already
rewrite `[^` to `[!` and widen POSIX classes.

### 5. MEDIUM, new false positive: the listing cap denies ordinary reads in this repository

**Cause.** `expand_word_glob` stops when one step yields more than 512 directories (`:4471`). This
repository has 527 folders under `CLAUDE/Plan/Completed/`.

**Reproducer.** Run in-process with the PR source, from `/workspace`, with real bash defaults:

| Command                                            | PR                                                         | main  |
| -------------------------------------------------- | ---------------------------------------------------------- | ----- |
| `grep -l Complete CLAUDE/Plan/Completed/*/PLAN.md` | DENY: "a globbed word matches more than the guard follows" | ALLOW |
| `ls CLAUDE/Plan/*/PLAN.md`                         | ALLOW                                                      | ALLOW |

The same happens with `**/*.md` from the repository root in conservative mode: the expansion cannot
finish, so the guard denies.

**Why this is a cost, not a hole.** Failing closed is the correct security choice. The problem is that
the cap counts directories that hold no link at all.

**Options:**

- apply a cap only to paths that pass through a link, and bound the plain listing by the scan deadline;
- prune with the project link index, so the walk never lists a subtree the index proves holds no link.

**Side effect.** Every such deny also logs a full traceback ("placing the command's words raised;
denying").

### 6. MEDIUM, new: performance, because no directory listing is reused across words

Each globbed word lists every directory it touches again, for every base. Nothing is cached for the
scan. Measured with `wide/` holding 300 subdirectories:

| Words of `wide/*/x<n>*` | PR            | main          |
| ----------------------- | ------------- | ------------- |
| 1                       | 0.01 s, allow | 0.00 s        |
| 100                     | 0.38 s, allow | 0.04 s        |
| 2000                    | 12.7 s, DENY  | 0.85 s, allow |

The 2000-word deny gave this reason: "the scan of this command stopped before it finished (it reached
a size limit or its deadline ...)". So it fails closed, but it is a false positive, and the time is
close to a hook's dispatch budget.

**Fix.** Cache each directory's listing for the duration of one scan, keyed by path. The cap then
counts distinct directories instead of repeated ones.

### 7. LOW, pre-existing and outside the PR's scope: `${var:-word}` and `~`

- **Parameter defaults.** `${var:-word}` defaults are never substituted, so these are allowed on both
  the PR and main:
  - `cat kit/b${x:-i}n/l*`, which is bash-confirmed;
  - `cat kit/b${x-?}n/late`;
  - even the literal `cat kit/bin/${x:-late}`.
- **Tilde.** `_glob_link_mention` skips forms that start with `~` (`:4516`). This currently loses
  nothing: the literal `cat ~/hk/bin/late` is already allowed on both, because HOME is outside the
  project. If links under the home directory are ever brought into scope, `~` will need the same
  expansion.

### 8. INFO: what I checked and found sound

- **Fail-closed bounds.** Each of these makes `Bounded.stopped` → `required()` raise
  `IncompleteScanError`, and the handler denies:

  - passing either cap, `GLOB_WORD_LISTING_CAP` or `GLOB_WORD_MATCH_CAP`;
  - a directory that cannot be listed (EACCES);
  - an entry whose type cannot be read.

  I saw this on a real tree (finding 5) and on the deadline path (finding 6).

- **Symlink loops.** A loop (`ELOOP`) is treated as no match. That is correct, because bash cannot
  open through a loop either. `_globstar` never descends through a link.

- **Names that are too long.** `ENAMETOOLONG` is treated as absent. That is correct for the same
  reason.

- **`..` hops.** All of these are denied:

  - `kit/lib/../b*/late`, `kit/dl/../outside/*` and `src/../kit/*/late`, from the project root;
  - `../*/late`, `../b?n/l*` and `../../kit/*/late`, from inside `kit/bin`.

- **Brace expansion.** `kit/{a..c}in/late`, `kit/{a..c}*/late`, `kit/{b,z}*/late` and
  `kit/{{b,c}?n,z}/late` are all denied.

- **Plain globs that are partly quoted.** `kit/"b"*/late`, `kit/'b'?n/late`, `kit/$'b'*/late` and
  `"kit"/*/late` are all denied.

- **Other shapes.** All of these are denied:

  - redirections, `cat < kit/*/late` and `exec 3< kit/b?n/late`;
  - a directory link followed by a glob, `kit/dl/*` and `kit/d?/*`;
  - `bash -c`, `sh -c` and `eval`;
  - POSIX classes, `[^x]` and `[]b]` in a path from the project root;
  - equivalence classes.

- **TOCTOU.** I did not probe this. The guard judges a command before it runs, so a link the same
  command creates is judged only by its spelling. That limit is the same for literal paths and is
  not introduced by this PR.

- **The two flipped tests.** Both are correctly re-pinned:

  - **`test_secret_file_guard_cwd_fail_closed.py`.** `inner/ilink` links to the protected dummy (`:83`),
    and the command runs from the worktree, which is the project root. `*/*` therefore matches the
    link.
  - **`test_secret_file_guard_link_resolution.py`.** The command always runs from the worktree; the
    test sets the project root to either the worktree or the primary, and the test has no skip.
    From the worktree, `*/*` matches `inner/ilink` (`:90`), which points at the dummy, and also
    `dlink/<dummy>` and `plink/<dummy>`. So DENY is right for both project roots.
  - **Caveat.** `cd clean && cat */*` is denied only because the guard also judges the word from
    where the command started. Under `&&`, `cat` never runs if the `cd` fails, and from `clean` the
    glob `*/*` matches nothing. The literal `cd clean && cat inner/ilink` is already judged the same
    way, so this is a consistent over-deny, not a mis-encoded test.

## Recommendation

1. Merge. On security it is a strict improvement.
2. Record findings 1, 2, 3 and 4 as open follow-ups to N710. They are the same class, each has a
   reproducer above, and each should be fixed by widening, never narrowing.
3. Fix finding 5 next, together with the cache from finding 6. `Completed/` already has more than
   512 folders, so every `Completed/*/...` glob in this repository is now denied.
