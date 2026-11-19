# Plan 00623: independent adversarial review

Branch `agent-a13d7c8504105d4c9-aeae03b4`. Reviewed tip `6d65b0538`; fixes from this review are in the commit that adds this file. Baseline: a detached worktree of `main` at `ede62dd1d`. Every run printed the `secret_file_matching.__file__` it imported, so each side is known to have run its own tree.

## Verdict

**PASS** on DENY-to-ALLOW, after the fixes below.

- **0 DENY-to-ALLOW against main**, with the link index cold and built, on every corpus and probe set.
- **2 fail-open defects** in the branch's own new code. Neither is a DENY-to-ALLOW against main, because main allows these commands anyway. Both read a protected dummy in real bash while the branch allowed them. Both are fixed here, each with a test written first (RED, then GREEN).
- **1 pre-existing test (Task 5)** is updated to the fail-closed verdict.
- **Usability** holds in the synthetic large project once the index is built. It does **not** hold in this repository, whose index overflows its cap (see "Left").

## Harness

Scripts are in `/workspace/untracked/scratch/00623-review/tools/`, outputs in `out/`. The Plan 00614 review-2 harness was reused, its fixture paths moved, and these were added:

- a link-index mode: `cold` (no build is ever started, so the per-call walk runs) or `built` (a synchronous `build_link_index` before each set);
- `p623.py`: 148 probes for the `~`, `$HOME` and `$TMPDIR` placement, × 4 daemon environments (HOME/TMPDIR outside the project; inside it; through a link into it; relative) × 2 cwds;
- `fharness.py`: the flaggable guard, glob `sec/**`, over the corpus plus grep variants of the p623 probes, with links into `sec/` from inside and outside the project;
- `failclosed.py`: forces every bounded walk to stop early;
- `oracle.py` and `setters.py`: run each allowed probe in real bash against a copy of the fixture and flag any output holding the dummy content.

### Corpus

There are 2,798 distinct commands: the 2,451 from Plan 00614 review 2, plus the string literals of every secret, flaggable and quarantine guard, matching, recursive-search and link-index test file in both trees.

## Task 1: loosening corpus (DENY on main, ALLOW on the branch)

| Set                               | n     | D2A cold | D2A built | A2D cold | A2D built |
| --------------------------------- | ----- | -------- | --------- | -------- | --------- |
| corpus, secret guard, fx          | 2,798 | 0        | 0         | 466      | 466       |
| corpus, secret guard, fxn         | 2,798 | 0        | 0         | 469      | 469       |
| corpus, quarantine guard          | 2,798 | 0        | 0         | 164      | 164       |
| corpus + p623, flaggable guard    | 3,189 | 0        | 0         | 79       | 1         |
| prior probes p1/p2 (fx, fxn, fxl) | 648   | 0        | 0         | –        | –         |
| quarantine probes q1/q2           | 216   | 0        | 0         | 39       | 39        |
| Plan 00614 review-2 new probes    | 217   | 0        | 0         | 167      | 161       |
| extra (top level, /proc, big)     | 152   | 0        | 0         | 108      | 19        |
| p623 placement probes             | 1,184 | 0        | 0         | 1,146    | 1,072     |

The counts are for the tip as reviewed. The re-run on the fixed tree is in the "After the fixes" section.

On the A2D column: main allows almost every computed-move probe, so the branch's denials there are intended tightenings.

**Oracle.** Every p623 probe the branch allows was run in real bash, apart from those that need sudo, make or the network: 12 runs cold, 56 built, **0 read the dummy**.

**Flaggable guard.** Commands nested 5 or more `bash -c` deep raise `TooManyToEnumerateError` out of the handler. This happens on **main and the branch alike** (3 commands cold, 21 built). It is pre-existing and not a loosening, but the exception escapes the guard's fail-closed handler. Left for a ledger entry.

## Task 2: fail-closed (forced early stops)

`failclosed.py` runs 364 probes on `fx` and `fz` (the p1, p2 and p623 sets). It forces each stop below, and for each one looks for a probe that is denied normally and allowed under the stop:

- a re-list cap of 0;
- an expired verify deadline;
- an overflowed index;
- a link-scan cap of 2;
- a link-directory cap of 0;
- a search-directory cap of 1;
- one directory, or every directory, that cannot be listed;
- link kinds that cannot be told;
- a nesting depth of 0;
- an expired scan deadline.

**Before the fixes**, two stop classes opened commands:

### F1 (fixed): a placed `~`, `$HOME` or `$TMPDIR` move waived a stopped scan

`place_outside_project` uses the daemon's value. Both callers then judged the move with `indeterminate(fail_closed=False)`:

- `secret_file_matching._DirectoryWalk.change`;
- `recursive_search._SearchCwds.moved`.

So when the link scan had stopped, nothing denied. That happens with:

- a cold index past 512 directories;
- an overflowed index (more than 200,000 directories, as `/workspace` is);
- a verify deadline;
- an unclassifiable link.

The placement is not sound, so this is a real escape. Each of these read the dummy in real bash and was ALLOWED with the scan stopped:

- `v=HO; getopts i ${v}ME -i; cd ~; cat late`
- `v=HO; let ${v}ME=7; cd ~; cat late` (also `((…))`, `$((…))`, and an array subscript `x[${v}ME=7]=1`)
- `v=TMP; let ${v}DIR=7; cd $TMPDIR; cat late`
- `trap 'T''MPDIR=$PWD/inner' DEBUG; cd $TMPDIR; cat rel`
- `ln -s "$PWD/inner" ~/new && cd ~/new && cat rel` (the link is made by the same command, so `realpath` at decision time sees nothing)
- `cd -P "$TMPDIR/up/.." && cat proj/inner/rel` (the physical place is checked but not returned as a base)

`getopts`, `let`, `trap` and arithmetic are not in `_INDIRECT_SETTER`. A deny-list cannot be completed: arithmetic assigns from subscripts, offsets and `[[ -eq ]]`.

**Fix.** Both sites now call `indeterminate()`, which fails closed. The placed directories are still ADDED as bases, so a word under `$HOME` is resolved there, but a stopped scan denies.

**Cost.** A move to `~` or `$TMPDIR` followed by a reader is denied while the index is cold or overflowed. Once it is built, it is allowed again.

Tests:

- `TestAStoppedScanIsNotOverriddenByPlacement`: 8 commands × cold, overflowed and built × 2 fixtures. 32 tests were RED before the fix.
- The builder's `test_a_move_outside_the_project_is_allowed_with_a_cold_index` is now `..._once_the_index_is_built`. A new cold test asserts that a placed move followed by a read denies.

### F2 (fixed): a directory that could not be listed ended the walk as "complete"

The walk counted such a directory as holding a link, but did not descend into it, and still reported the walk complete. Bash can `cd` through a directory it cannot list (mode `0311`), so a link below it was never seen. `cd $(printf a/b); cat late` was allowed with `a/` unlistable.

Measured: the cold `unreadable-all` scenario opened 108 probes on `fx` and 110 on `fz`.

It applies to a daemon that is not root, or to a filesystem that refuses root (NFS `root_squash`, FUSE).

**Fix.** An unlistable directory now stops the result, with its own reason, in both places:

- `_walk_project_links`;
- `LinkIndex.verify`.

Tests:

- `test_an_unlistable_directory_stops_the_per_call_scan`;
- `test_a_directory_that_cannot_be_listed_stops_the_verification`.

### Other stops

- **Never open a denied probe:** the re-list cap, an overflowed index, the scan, directory and search caps, unreadable `inner`, depth 0 and the scan deadline.
- **Truncation that marks the walk lost:** `recursive_search` `SEARCH_DIRECTORY_CAP` cuts the list but sets `lost`, so every later read is judged over every indexed file.
- **The `[:LINK_DIRECTORY_CAP]` slices** set `overflowed` or `unscanned`.

## Task 3: cache forgery

The link index:

- reads no project file and no environment variable, and writes nothing;
- is keyed by `resolve_project_root()`;
- checks every stored directory against `(st_dev, st_ino, st_ctime_ns)` on each use, and classifies links again on each use;
- lists again any directory whose ctime is within 3 seconds of its listing.

What an earlier command can do to it, and what follows:

| Action                                                  | Effect                                                      |
| ------------------------------------------------------- | ----------------------------------------------------------- |
| Create more than 200,000 directories                    | Overflowed index: deny, not allow                           |
| Change more than 4,096 directories                      | Stale index: deny                                           |
| Exceed the 2 s verify deadline                          | Deny                                                        |
| Evict it from the 4-entry cache, or make the build fail | Back to the capped per-call walk, which denies past its cap |
| Add a link in the same clock tick as the listing        | Caught by the 3-second re-list window                       |
| Replace a directory with a link                         | Changes the parent's ctime, so the parent is listed again   |
| Bind-mount over a directory (needs root)                | Changes the lstat identity, so it is listed again           |

`test_a_link_made_after_the_build_is_seen` passes.

**Limit.** The agent runs as uid 0. Root can reset ctime only by moving the system clock, and would have to hit the stored nanosecond. Root also does not need a link to read the file. This is outside the threat model.

`.git` is not entered. The per-call walk on main skips it the same way, so this is no change.

## Task 4: usability

**Synthetic projects.** With the index built:

- `big/` has 600 directories and no link. It allows 129 of the 132 Plan 00614 usability commands. The 3 denied hold lone surrogate code points.
- `fz/` has 600 directories and has links. It allows `cd "$(mktemp -d)" && ls`, `cd "$TMPDIR" && python3 x.py`, `cd ~/x && cat README.md`, `cd ~ && ls`, `cd "$D" && make test`, `cd "$(dirname "$0")" && ./run.sh` and `for d in */; do (cd "$d" && make); done`.

`TestMovesOutsideTheProjectArePlaced` (built) and the builder's 12-command `USABILITY` list pass.

**This repository.** `build_link_index('/workspace')` overflows at 200,000 directories after 5 s. The tree includes `.claude/worktrees/*` (about 69,000 directories each) and `untracked/scratch` fixtures. So in this repository every computed move followed by a reader is denied, and after F1 that includes `~` and `$TMPDIR` moves.

A single worktree builds in 0.8 s. It has 69,252 directories, 111 holding a link and 150 directory links, so it is under 512, and each verify takes about 0.3 s.

Projects with more than 512 link-holding directories also stop in `_scan_from_index` and deny. `node_modules/.bin` is the likely cause.

## Task 5: TestSweepVerdictIsHostIndependent

**This is not pre-existing on main.** The class passes on main and fails on the branch. The branch's review-614c P2 rule denies a scan that gave up when the command holds a glob or a recursive search. With an expired deadline on the branch:

- `cat a*` and `grep -r x .` are denied;
- `cat README.md` and `cd $(printf x); cat y` are still allowed, with an advisory naming the deadline.

**The branch is right on fail-closed grounds.** The literal fallback cannot see what a glob expands to, so what the scan never reached is unknown. Host independence still holds, because `SCAN_DEADLINE_SECONDS` stays far above any host's scan time; the class's first test checks this.

**The test is updated** to the branch's verdict:

- a wildcard command denies, at both sizes;
- the deny reason names the deadline;
- a command without a glob still allows, with an advisory that names the deadline.

## After the fixes

RERUN_PLACEHOLDER

## Left

- **This repository's index overflows its cap** (more than 200,000 directories, worktrees included). With F1 fixed, a move to `~` or `$TMPDIR` followed by a reader is denied here. Options for the coordinator:
  - exclude `.claude/worktrees/` and `untracked/` from the index, since they are other checkouts and scratch;
  - or raise the build cap.
- **More than 512 link-holding directories** (`node_modules`) still stop `_scan_from_index`.
- **Flaggable guard:** `TooManyToEnumerateError` escapes the handler on commands nested 5 or more `bash -c` deep, on main and on the branch. It is pre-existing.
- **Placement residuals** that are already ledgered (N669):
  - the shell's `HOME` or `TMPDIR` can differ from the daemon's. Since F1 this matters only when the scan is complete, and then every link directory is judged anyway;
  - an alias or a function named `cd`.
- **The verify cost** is one lstat for every directory on every computed move (about 0.3 s per 69,000 directories).
