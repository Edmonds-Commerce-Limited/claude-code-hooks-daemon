# N130 / N348: a capped walk whose cost does not track tree size

**Author**: design sub-agent (Opus), read-only, against main at 96113ed27 (da7d33ca3 checked out).
**Scope**: ledger 00483 N130 (D2), ledger 00474 N348. No source file was changed. Timing scripts:
`untracked/scratch/n130_walk_timing.py`, `untracked/scratch/n130_synth_timing.py` (counts and timings only),
synthetic tree at `untracked/scratch/n130-synth/` (300k files, can be deleted).

## Recommendation

Fail closed past the cap: every past-cap or past-deadline answer raises and is denied as
`R-SECRET-SCAN-INCOMPLETE`. Bring the number of commands that reach the cap close to zero by doing three things:

1. **Ask git for the file list wherever the search tool follows git's rules.** `git grep` reads exactly
   `git ls-files --cached`. `rg`, `ag` and (if confirmed) the Grep tool read a subset of
   `git ls-files -co --exclude-standard`. Both listings are written in C. They cost 0.04 s and 0.11 s for 200k files.
   This is NOT an optimisation: without it, the fail-closed fix denies every `rg x` at this repository's root (see F4).
2. **Walk only where the tool really reads everything** (`grep -r`, `ack`, `rg -uu`/`--no-ignore`, and git
   failures). Use `os.scandir` with a literal screen in front of the glob matcher, which cuts per-entry cost about 7x.
3. **Raise the caps to measured values.** The tree walk goes from 5000 files to 250k entries. The bare-glob
   expansion goes from 5000 to 100k paths. The existing 5 s scan deadline stays as a backstop and is now passed to
   the walk.

The past-cap verdict is **deny, `R-SECRET-SCAN-INCOMPLETE`**, for all four call sites, including the quarantine
guard, which needs its own incomplete route. Option (b), a cached per-root index validated by directory mtimes, is
the only option whose steady-state cost is bounded by directories rather than files. I evaluated it and deferred
it. Fund it only if real clients still hit the raised cap.

## Facts established

### Code (main)

- `directory_contains_protected` (`utils/secret_file_matching.py:2707`) walks with `os.walk`. It calls
  `path_matches_globs` once per file per pattern and returns `None` after `DIRECTORY_SCAN_MAX_ENTRIES = 5000`
  files. Callers read `None` as allow. This is N130.

- It has **four** hook-path call sites, not three:

  - `secret_file_guard.py:1536` (Grep tool)
  - `recursive_search.protected_reached_by_search` (`recursive_search.py:327`), reached from `secret_file_guard._search_reach`
  - `quarantine_artefact_read_guard.py:303` (Grep tool)
  - `quarantine_artefact_read_guard.py:332` (Bash, through `protected_reached_by_search`)

  `secret_file_hygiene_checker.py:441` reuses the constant at SessionStart, which is not on the hook path.

- `recursive_search._tracked_protected` (`recursive_search.py:521`) has **a second instance of the N130 hole**.
  It cuts the `git ls-files` listing at `DIRECTORY_SCAN_MAX_ENTRIES` and answers on the first 5000 tracked files
  only. A tracked protected file listed after position 5000 is allowed under `git grep`. The cut buys nothing,
  because `protected_among` already screens a repository-sized list cheaply (N289b).

- For ignore-aware tools (rg/ag), the walk still visits every non-hidden entry, ignored directories included. It then
  spends one `git check-ignore` subprocess per protected hit to excuse ignored files (`_also_git_ignored`).
  The cost is therefore set by the ignored bulk (node_modules, venvs, worktrees), which the tool itself never reads.

- `_search_reach` (`secret_file_guard.py:1550`) is not given the Bash branch's `deadline`. The Grep-tool branch
  creates none. The walk can therefore run past `SCAN_DEADLINE_SECONDS` unobserved.

- `_bare_glob_mention` (`secret_file_matching.py:1447`) goes through `_expand_glob_token`, which runs
  `first_matching_glob` on every examined path. Past `_MAX_BARE_GLOB_FS_EXPANSIONS = 5000` it raises
  `TooManyToEnumerateError`. The guard's wrapper (`secret_file_guard.py:1409`) maps that and `TimeoutError` to
  `R-SECRET-SCAN-INCOMPLETE` (merge 8ab562afb).

- Latency budget:

  - `SCAN_DEADLINE_SECONDS = 5.0`, per guard call.
  - `CHAIN_DEADLINE_DEFAULT = 20` s for the whole chain. Past it, a SAFETY handler is denied rather than skipped.
  - `REQUEST_DEFAULT`/`HOOK_TOTAL` = 30 s, the client budget. A client timeout fails the whole chain open.
  - `REGISTERED_HOOK_TIMEOUT = 60`.
  - `Timeout.HOOK_DISPATCH = 5_000` is defined but referenced nowhere.

- Pattern shapes: all six shipped defaults are unanchored any-depth name globs. In the `path_exclusion` dialect,
  an unanchored pattern gets a `PREFIX` token and `*` does not cross `/`, so each one matches a final path component
  at any depth. Projects may add anchored (`/x/**`) or directory patterns (D3). In `additive` mode the defaults are
  always present.

### Measurements (this host, 8 cores, warm page cache; the tree is live, so counts drift between runs)

| What                                                                         | Count                    | Time                            |
| ---------------------------------------------------------------------------- | ------------------------ | ------------------------------- |
| `/workspace` scandir, every entry                                            | 1,831,750 entries        | 3.28 s                          |
| `/workspace` scandir, hidden entries skipped (rg view without git)           | 1,164,994 entries        | 2.49 s                          |
| of which under `untracked/` (gitignored)                                     | 1,151,035                | 2.10 s                          |
| `/workspace` minus `.git`, `untracked`: scandir + literal screen             | 32,250 files, 3,796 dirs | 0.12 s                          |
| same tree, `first_matching_glob` per file (today's per-file cost)            | 20,000 files             | 0.56 s (28 µs/file)             |
| synthetic tree: scandir + screen                                             | 303,202 entries          | 0.30-0.43 s                     |
| synthetic tree: `first_matching_glob` per file                               | 50,000 files             | 0.34-0.45 s (7-9 µs/file)       |
| synthetic: `git ls-files -z --cached`                                        | 200,001                  | 0.036-0.045 s                   |
| synthetic: `git ls-files -z -co --exclude-standard`                          | 200,001                  | 0.10-0.11 s                     |
| synthetic: `git ls-files -z -o -i --exclude-standard --directory`            | 1                        | 0.09 s                          |
| synthetic: `stat` every directory                                            | 3,173 dirs               | 0.008 s                         |
| `/workspace`: `git ls-files --cached` / `-co --exclude-standard`             | 4,943 / 4,943            | 0.005 s / 0.03 s                |
| `/workspace`: `-o -i --exclude-standard --directory` / without `--directory` | 231 / 553,112            | 0.025 s / 2.4-2.8 s             |
| `/workspace`: `directory_contains_protected` (cap 5000)                      | found                    | 0.06-0.07 s                     |
| bare glob from `/workspace`, depth 3 (`*/*/*`): expand / expand+match        | 4,567 paths              | 0.036 s / 0.146 s               |
| depth 4 (`*/*/*/*`)                                                          | 18,350 paths             | 0.149 s / 0.317 s (reaches one) |
| depth 5                                                                      | 30,179 paths             | 0.265 s / 0.62 s                |

What the table shows:

- **F1.** The 5000 cap uses about 0.05-0.15 s of the 5 s scan deadline. It is about 30x tighter than the latency
  budget requires.
- **F2.** Per-entry cost is dominated by the glob matcher, not the filesystem. The screened scandir walk costs
  1-2 µs per entry on a dense tree and up to about 4.6 µs on this repository's sparser tree. The matcher costs
  7-28 µs per file.
- **F3.** git's listings cost about 0.5 µs per file and do not see ignored bulk at all. In this repository the
  non-ignored set is 4,943 files out of about 1.8M entries.
- **F4.** Today `rg x` at `/workspace` is allowed only through the N130 hole. The rg-view walk finds the gitignored
  protected file at depth 2 under `untracked/` and excuses it through `check-ignore`. It then walks into
  `untracked/` and stops at 5000 with `None`. If only the fail-closed half of N130 were fixed, every whole-repo `rg`
  here would be denied as incomplete. The rg view has 1.16M entries, which no affordable cap covers. With git's
  listing it has 4,943 entries and is clean.
- **F5.** `*/*/*/*` from this repository's root genuinely reaches a protected path: a fixture under
  `untracked/scratch/`. N348's example is therefore a correct deny today for a second reason, apart from the cap.

## Options

### (a) Enumerate candidates from the patterns instead of walking

**Correctness**: sound only for an anchored pattern whose directory components are literal (`/config/vault.yml`,
`/secrets/**`). Such a pattern can be answered with one `stat`, or with a walk of its own subtree only. An
unanchored name glob, which describes every shipped default, can sit in any directory. Ruling it out requires
listing every directory. In `additive` mode the defaults are always present, so (a) never removes the walk.

**For N348**: the ledger's "check each protected pattern against the glob" cannot bound the default case either.
A glob whose last component is bare (`*`, `?`, `dir/*`) intersects every unanchored name pattern by construction:
a bare `*` matches any name. The text routes already handle every glob that has literal residue.

**Latency**: excellent where it applies. **Complexity**: low.

**Verdict**: not a fix. Possibly a later optimisation for `mode: replace` projects whose patterns are all anchored.

### (b) Cached per-root index of protected files

There are two ways to keep the index fresh:

- **inotify**: Linux only. It needs one watch per directory (244k here) against `max_user_watches`, with FSEvents
  on macOS. Rejected.
- **Directory-mtime validation**: a directory's mtime changes when an entry in it is created, deleted or renamed,
  which are exactly the events that change which names exist. A cached record per directory holds its mtime,
  subdirectory names and protected hits. Revalidation is one `stat` per directory: 8 ms for 3,173 dirs; an
  estimated 0.3-0.6 s for this repository's 244k. Only changed directories are re-listed.

**Correctness**:

- The racy-timestamp case has to be handled the way git's "racy git" rule does: never trust a record whose mtime
  falls within the filesystem's timestamp granularity of the moment it was scanned.
- The cache has to be invalidated when patterns change. Today patterns change only on restart.
- Network and FUSE filesystems with lazy mtimes are a residual.
- A stale record is a silent allow, which is the failure mode the threat model rules out.

**Latency**: steady state is bounded by directories rather than files. A cold build still costs a full walk, which
has to happen off the hook path (a background thread at SessionStart). A call that arrives before the build
finishes still needs a past-cap verdict, so (b) does not remove the decision. It moves it to the cold case.

**Complexity**: high. It needs thread safety under `BoundedDispatcher`, a memory ceiling (tens of MB at 244k
directories), per-view variants (hidden or ignored skipped), and keying by directory so that any root reuses the
records.

**Verdict**: deferred. It is the right step only if the raised cap still produces denies on real client trees.

### (c) `git ls-files` as the oracle for git-shaped tools

**Correctness**:

- `git grep` reads `ls-files --cached`. Using it is exact.
- rg and ag read a subset of `-co --exclude-standard`. Tracked files that match `.gitignore` are listed by git but
  skipped by rg. `.ignore`/`.rgignore` only exclude more. Both tools honour `core.excludesFile` and
  `.git/info/exclude`. The over-approximation can only deny, never allow.
- The listing is the working tree at call time, so nothing goes stale.

Edges that have to be handled:

- A nested repository is listed as `dir/` under `-o`, and a submodule is a gitlink under `-c`. rg descends into
  both, so these entries have to be walked.
- A root that is itself ignored or hidden but named explicitly (`rg x node_modules`) is searched by rg, while git
  lists nothing under it. Fall back to the walk when `git check-ignore -q <root>` succeeds or a root component is
  hidden.
- The hidden-entry and negated-glob skips have to be applied to listed paths component by component below the
  root.
- Outside a repository, on dubious ownership, or when git times out, fall back to the walk. rg outside a
  repository does not apply `.gitignore`, so the walk is the right model.

**For grep -r (ALL view)**: git helps little. `-o -i --directory` collapses ignored directories, but those
directories are where the size is, and grep reads them.

**Latency**: about 0.1 s at 200k files. **Complexity**: moderate. It reuses `run_git` and `protected_among`.

**Verdict**: adopt for TRACKED and UNIGNORED views. It is required by F4.

### (d) scandir walk performance

The screened scandir walk measured 1-2 µs per entry (dense) to 4.6 µs per entry (sparse) on a warm cache. Rough
costs: 50k entries about 0.05-0.25 s; 200k about 0.2-0.9 s; 1M about 1-4.6 s.

A cold cache can be several times slower. That case is the deadline's job: a timeout is denied as incomplete with
"retry" advice, and the retry runs warm.

The literal screen is sound. `literal_screen` answers False only when no pattern can match, it returns `None` when
any pattern has no literal run, and screening the absolute path covers the relative one, because the relative path
is a suffix of it.

**Verdict**: adopt as the ALL-view engine. It replaces `os.walk` plus a per-file matcher.

### (e) Fail closed past a much higher, measured cap

**Correctness**: matches the ruling: "a guard that cannot read what it judges still fails closed". Allowing past
the cap is N130.

**False-positive cost**: once (c) handles the git-shaped tools, the cap is reached only by `grep -r`/`ack`-style
searches over trees above about 250k entries, and by bare globs above 100k paths. Those commands are themselves
slow, and the deny reason offers a better command (`rg`, `--exclude-dir`, a narrower root). The coordinator already
ruled the whole-repo `grep -r` deny at this checkout's root correct (journal 00483, 2026-10-04).

An entry cap gives the same verdict for the same tree. A time-only budget would make the verdict depend on load as
well as on tree size, so the cap stays entry-based, with the deadline as a backstop.

**Verdict**: adopt, together with (c) and (d).

## Recommended design

### New module `utils/protected_tree_scan.py`

Write the test file first: `tests/unit/utils/test_protected_tree_scan.py`.

```python
class TreeView(StrEnum):
    ALL = "all"              # grep -r, ack, rg -uu / --no-ignore, the Grep tool until confirmed otherwise
    UNIGNORED = "unignored"  # rg, ag defaults: git's non-ignored set, then the skip predicate
    TRACKED = "tracked"      # git grep: the index

TREE_SCAN_MAX_ENTRIES: Final[int] = 250_000

def find_protected_in_tree(
    root: str,
    patterns: tuple[str, ...],
    *,
    view: TreeView,
    skip: Callable[[str, bool], bool] | None = None,
    is_exempt: Callable[[str], bool] | None = None,
    deadline: float | None = None,
    max_entries: int = TREE_SCAN_MAX_ENTRIES,
) -> str | None:
    """First protected glob matched under ``root`` as ``view`` reads it, else None.

    None means the whole view was examined and nothing matched. Raises
    shell_expansion.TooManyToEnumerateError past ``max_entries`` and
    TimeoutError past ``deadline``; neither is ever answered as None.
    """
```

**ALL view**:

- Iterative `os.scandir` stack with `follow_symlinks=False`, matching `grep -r` and today's `os.walk`. `-R`
  following symlinks is today's existing residual and is out of scope here.
- Apply `skip` to directories (prune) and to files.
- Count every visited entry, directories included, so that a tree of empty directories cannot run unbounded.
- Check `deadline` every 1024 entries.
- Run `literal_screen(patterns)` on `entry.path` first. Only a screen hit pays for
  `first_matching_glob(path, patterns, project_root=...)`.
- Apply `is_exempt` on a hit, exactly as today.

**TRACKED view**:

- Call `run_git(root, "ls-files", "-z", "--cached", "--", ".", timeout=<remaining deadline>)`.
- Do not truncate. This closes the `_tracked_protected` instance of the hole.
- Apply `skip` component by component, then `protected_among`, then `is_exempt`.
- If git fails: when `root` is not inside a work tree, return None, because `git grep` cannot read there either
  (today's contract). Otherwise, for example on a timeout, raise `TimeoutError`.
- `run_git` reports a timeout as a non-zero returncode, so this view needs a small typed signal from it, such as a
  `timed_out` check on stderr or a sibling helper that raises.

**UNIGNORED view**:

- Return the ALL-view answer instead when `git check-ignore -q root` succeeds, or when a component of `root` below
  the repository top is hidden (both are explicitly named roots that rg reads).
- Otherwise call `run_git(root, "ls-files", "-z", "-co", "--exclude-standard", "--", ".")`.
- Apply `skip` component by component, then `protected_among`.
- Walk each listed entry that is a directory (a nested repository `x/`, or a submodule gitlink) in the UNIGNORED
  fallback mode: today's walk, with `skip` and with `check-ignore` excusing hits. The same cap and deadline apply.
- If git fails, use that fallback walk. It is also the correct model for rg outside a repository.
- Count listed paths against `max_entries` too, so a huge repository still ends in a deterministic incomplete
  rather than a slow allow.

**`directory_contains_protected`**: keep it as a thin wrapper, `view=ALL`, for any caller not migrated. Its
docstring's "best-effort partial enforcement" sentence goes. It never returns None for an incomplete scan. Rename
`DIRECTORY_SCAN_MAX_ENTRIES`, or keep it only for `secret_file_hygiene_checker`, which is not on the hook path and
whose tests patch it.

### Callers

| Caller                                                        | Change                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| ------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `secret_file_guard._evaluate`, Grep branch                    | Create `deadline = time.monotonic() + SCAN_DEADLINE_SECONDS` and call `find_protected_in_tree(path, ..., view=ALL)` until the owner rules on O2. A raise reaches the existing `_matched_pattern_and_route` wrapper and is denied as `R-SECRET-SCAN-INCOMPLETE`.                                                                                                                                                                                                                                 |
| `secret_file_guard._search_reach`                             | Take the Bash branch's `deadline` and pass it through.                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `recursive_search.protected_reached_by_search`                | Gains `deadline`. `_Read` carries a `TreeView` instead of `tracked_only`/`ignore_aware`: `git grep` maps to TRACKED, `git grep --no-index/--untracked` to ALL (`--untracked` is really tracked plus non-ignored untracked, so UNIGNORED would be exact, but ALL is safe), rg/ag with `honour_ignore` to UNIGNORED, everything else to ALL. `_tracked_protected` and `_also_git_ignored` move into the new module. Delete the module-docstring sentence saying the verdict depends on tree size. |
| `quarantine_artefact_read_guard` (Grep at :303, Bash at :332) | Same calls, with a deadline. Catch `TooManyToEnumerateError`/`TimeoutError` and deny on a new incomplete route. That needs a new rule, for example `R-QUARANTINE-SCAN-INCOMPLETE`, since a raise currently lands on the evaluation-error route, whose text calls it a guard bug (the N134 lesson). See O4.                                                                                                                                                                                      |
| `_bare_glob_mention` / `_expand_glob_token` (N348)            | Put the literal screen in front of `first_matching_glob` in `_expand_glob_token`. Raise `_MAX_BARE_GLOB_FS_EXPANSIONS` to 100_000, which measured about 0.3 s per 30k paths including expansion. Keep the both-edges cap at 200: it is a different, heuristic-gated route. The verdict past the cap stays `R-SECRET-SCAN-INCOMPLETE`. Close the "Still Open" bullet with the (a) analysis above.                                                                                                |

### How `R-SECRET-SCAN-INCOMPLETE` is used

There is no new rule for the secret guard. The rule now covers three surfaces: the glob expansion, the tree walk,
and the git listing (timeout). `_incomplete_detail` already distinguishes a cap from the deadline. Extend the
`TooManyToEnumerateError` message to say what ran out ("a recursive search under `<root>` visits more than
250000 entries") without naming any discovered path.

The remedy text should offer the tool-specific way out:

- use `rg`, which skips gitignored trees;
- add `--exclude-dir`;
- search a narrower root.

A real finding keeps `R-SECRET-READ` (Grep tool) or the `search` route.

### Tests (unit unless noted; assert on work done, not wall clock, per the N123 precedent)

**`test_protected_tree_scan.py`**:

1. N130 regression: a tree with 5500 files plus `zdeep/<protected>` is found, with the default cap.
2. With a small cap patched in, the same clean tree raises `TooManyToEnumerateError`. It never returns None.
3. The deadline is checked inside the walk: a monotonic stub past the deadline raises `TimeoutError`.
4. The screened walk agrees with the unscreened matcher on a generated name set. Include a project pattern with no
   literal run, where `literal_screen` returns None and the full matcher is used.
5. TRACKED view: a protected tracked file at listing position 6000 is found. This is the `_tracked_protected`
   truncation hole.
6. UNIGNORED view, in a temporary git repository:
   - an ignored protected file is not reported;
   - a tracked hidden one is skipped when `skip_hidden` applies;
   - a nested repository's protected file is found;
   - a non-repository falls back to the walk;
   - an explicitly named ignored root falls back to the walk and is found.
7. An entry-count seam proves that UNIGNORED does not visit an ignored directory of 50k files.

**`test_recursive_search.py`**: view mapping per tool. `rg x .` in a repository with a large ignored directory and
a clean tracked set is allowed. `grep -r x .` over the same tree, with a cap patched below its size, raises.

**`test_secret_file_guard*.py`**:

- A Grep tool search over a past-cap tree is denied as `R-SECRET-SCAN-INCOMPLETE`, not `R-SECRET-READ`, and not
  allowed.
- A Bash `grep -r` over the same tree is denied the same way.
- A bare glob of about 20k paths with no protected hit is allowed.
- The `_search_reach` deadline is forwarded.

**`test_quarantine_artefact_read_guard.py`**: past the cap, the deny goes through the incomplete rule, not the
evaluation-error route.

**Corpus**: add rows to `scripts/qa/dangerous-invocation-corpus.yaml`:

- `rg needle` at a root with an ignored protected file: ALLOW;
- `grep -r needle .` over a past-cap clean tree: DENY, incomplete;
- `git grep needle` with a tracked protected file listed after position 5000: DENY.

**Docs**:

- Remove the residual-limit wording in `secret_file_guard.py` (the comment at :1531 and the handler guidance it
  feeds) and in `directory_contains_protected`'s docstring.
- In the N130 and N348 rows, record "fixed: fail closed past a measured cap; git listings for git-shaped tools".
- Name the new constants in `docs/guides/HANDLER_REFERENCE.md` if the cap becomes configurable (O1).

## Needs an owner decision

- **O1. The cap values, and whether they are configurable.** The recommended values are 250k entries for the walk
  and 100k paths for the bare glob, as module constants. They could also be a `secret_file_guard` option, which a
  human edits in `.claude/hooks-daemon.yaml`, for monorepos where `grep -r` over 300k+ entries is routine. A higher
  value trades latency (about 1-4.6 µs per entry warm) against fewer incomplete denies.
- **O2. Which view the Grep tool gets.** Claude Code's Grep tool is built on ripgrep. Whether it skips gitignored
  and hidden files with rg's defaults is not established in this repository, and I could not probe it (no Grep tool
  in this agent).
  - If it does, the UNIGNORED view is exact and removes today's deny of a root-level Grep in this repository. That
    deny comes from the gitignored protected file under `untracked/`.
  - The cost is a dependency on upstream behaviour: a Claude Code release that adds `--no-ignore` or `--hidden`
    silently turns this into an allow.
  - Keeping ALL is safe and, in this repository, still denies a root Grep, as a finding today and as incomplete
    after the change. A live probe should come first: put a needle in a gitignored file, then in a hidden one, and
    Grep for it.
- **O3. Accepting the residual deny.** `grep -r`/`ack` over trees above the cap, and bare globs above 100k paths,
  are denied as incomplete (for example `grep -r x .` at this checkout's root, about 1.8M entries). This is the
  ruling applied as written. The alternative is to allow past the cap, which keeps N130 open.
- **O4. The quarantine guard past the cap.** The options are to fail closed with a new
  `R-QUARANTINE-SCAN-INCOMPLETE` (recommended, consistent), or to stay fail-open there on the grounds that DETAIL
  artefacts are flaggable content rather than secrets. It is the owner's call, because it is a different outcome
  class.
- **O5. Whether to fund option (b)**, the mtime-validated directory index, later. Fund it only if the raised cap
  produces incomplete denies on real client trees, and only with the racy-timestamp rule.

## Side observations (not ledger entries yet; coordinator to decide)

- **S1.** `Timeout.HOOK_DISPATCH` (`constants/timeout.py:68`, "max time for single handler") is referenced
  nowhere. The real per-call bound is the guard's own `SCAN_DEADLINE_SECONDS` plus the 20 s chain deadline.
- **S2.** While measuring, the guard denied the command
  `cd untracked; for d in repos/* worktrees/* fd-worktrees/*; do ... git -C "$d" ls-files ...; done` as
  `R-SECRET-BASH-MENTION`, reporting the matched token as a lone `*`. None of the three globs reaches a protected
  file. A lone `*` is probably split out of the loop text and expanded from the `untracked/` cwd, where a protected
  file sits. This looks like a false positive of the bare-glob route on a `for ... in` list, or a tokenisation
  artefact. It is worth a `hooks-daemon probe` reproduction.
- **S3.** Both guards walk the same root for the same Bash command, once each. If a profile shows it matters, a
  per-request memo keyed by `(root, view, skip signature)` that returns the screened candidate list could serve
  both pattern sets. It is not needed for correctness.
