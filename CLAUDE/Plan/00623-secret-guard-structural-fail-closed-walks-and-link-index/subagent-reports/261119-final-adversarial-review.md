# Plan 00623: final adversarial review (tip 761a450e1)

**Verdict: FAIL as reviewed, conditional PASS after the two fixes on this branch.** Against `main`, the branch loosens nothing: 0 DENY-to-ALLOW. But that number carries little weight here. Main allows almost every probe in this corpus: it denied 3 of 145 with the daemon cwd at `/`, and 18 of 145 at the project root. So the verdict rests on the real-bash oracle. The oracle found real escapes on the branch.

- **Fixed here, with tests written first:** two link escapes. The second one sits on the branch's own under-cap path, which is the shipped default.
- **Still open:** several escape classes that main shares. They are listed below for the owner to decide.

Tools are in `review2-tools/`. The working copies, fixtures and outputs are in the worktree's `untracked/scratch/rv2/`.

## Method

- **Fixture.** `fx/proj` holds 20 holding directories (`wNN/.bin/tool`, each a link inside the project). It also holds `w19/zz/late`, a link to a dummy protected file outside the project, `w19/zz/dl`, a directory link to outside, and an in-project dummy at `inner/<protected>`.
- **Guard run.** `secret_file_guard` was run in-process with `PYTHONPATH` set to each tree.
- **Trees and modes:**
  - the branch, with `LINK_SCAN_DIRECTORY_CAP` patched to 8 (the name-rule path) or left at 512 ("lifted", the shipped under-cap path), index built or cold;
  - the parent tip `71ca5278a^`, cap 8 and lifted, built;
  - `main` (a fresh worktree), daemon cwd at `/` and at the project root.
- **Corpora.** 145 + 36 commands (`commands.txt`, `commands2.txt`), covering:
  - braces, quoting, ANSI-C strings and escapes;
  - `${…}` defaults;
  - globs, bracket classes and extglob (including `shopt -s extglob` on an earlier line);
  - `./`, `//` and trailing slashes, and `..` chains;
  - redirects and option-attached words;
  - `find`, `xargs`, `grep -r`, `rg`, `tar`, `git` and `dd` readers;
  - `cd`/`pushd`/`CDPATH` chains after a computed move;
  - links and copies created earlier in the same command;
  - names that spell a link's tail through another directory.
- **Oracle.** Every command the branch allowed, in any mode, was run in real bash on a fresh copy of the fixture. `D` was set to each of 6 project directories, with and without extglob. Output holding the dummy content counts as an escape.

## Real-bash escapes on the reviewed tip (761a450e1)

| #   | Command (shape)                                                                              | Branch modes allowing                     | Main   | Status                  |
| --- | -------------------------------------------------------------------------------------------- | ----------------------------------------- | ------ | ----------------------- |
| E1  | `cat w19/zz/[l]ate`, `w1[9]/zz/late`, `cd w19/zz && cat [l]ate` (no computed move)           | all                                       | allows | **FIXED** `ae0724c5c`   |
| E2  | `cd "$D" && cat zz/[l]ate`, `zz/la[t]e`, `zz/l[a-z]te`, `z[z]/late`                          | under the cap                             | allows | **FIXED** `ae0724c5c`   |
| E3  | `cd "$D" && cat .bin/../zz/late`, `.bin/./../zz/late`                                        | under the cap                             | allows | **FIXED** (this commit) |
| E4  | `cat w19/zz/${X:-late}`, `${X-late}`, `cat inner/${X:-<protected>}` (static)                 | all                                       | allows | OPEN                    |
| E5  | `cd "$D" && cat zz/${X:-late}`, `${X:=late}`, `${D:+zz/late}`                                | under the cap (the cap path denies)       | allows | OPEN (same class as E4) |
| E6  | `shopt -s extglob` + newline + `cat w19/zz/+(l)ate`, `!(dl)`, `@(late)`                      | all                                       | allows | OPEN                    |
| E7  | `shopt -s extglob` + newline + `cd "$D" && cat zz/+(l)ate`                                   | cap path built (**parent tip denied it**) | allows | OPEN                    |
| E8  | `ln -s w19/zz n && cat n/late`, `ln -s ../outside n && cat n/i*`, `cp -rs … q && cat q/late` | all                                       | allows | OPEN                    |

Causes:

- **E1/E2.** `_token_mention` skipped the link check for any glob-shaped token, on the reasoning that "a link is never literally named `[x]`". But a finite bracket glob expands to a literal path that bash then reads through the link. `?` and `*` were caught because `index.glob_matches` expands those, while a finite bracket's expansions are no longer glob-shaped and reached nothing.
  - **Fix:** with globbing on, each finite expansion goes through `_link_mention`.
- **E3.** `CwdSet.bases_above_scanned` returned `[]` for any word holding `..`, and `could_be_link` (the over-cap path) only runs when overflowed.
  - **Fix:** the names before the first `..` are real directories, so they are matched against the scanned directories. A new `collapsed_above_scanned` judges the collapsed spelling, with leading `..` removed, from every base that spells it. `_link_targets` resolves those candidates physically.
- **E4/E5.** `_may_be_relative_path` and the other placement checks treat any `$` word as not a path. A parameter default (`${X:-word}`) is a literal path when `X` is unset. **E4 also reads an in-project protected file directly, with no link involved**, so this is a general secret-guard gap and not only a Plan 00623 one.
- **E6/E7.** The tokeniser splits `(`/`)`, so the word `zz/+(l)ate` is never judged whole. `LinkNames` treats `(` as "any name", but it never sees the word. E7 is the one parent-to-branch loosening found: the parent denied every computed move past the cap.
- **E8.** A link or symlink-copy made earlier in the same command is not modelled. The plan's "a link created earlier in the same command" probe only covers the shapes `ln -s <protected-target>` (denied) and `ln -s <dir>` followed by a read of a name the guard cannot connect.

Each open item is shared with main, so none is a loosening against main. E4 and E8 work in any project with no computed move, and are the most serious.

## Name rule past 512 holding directories (task 1 focus)

These attacks on `LinkNames.reaches` were all denied on the cap path:

- brace expansion with a slash inside (`w19/{q,zz/late}`, `w19/z{z/la,}te`, `{,w19/}zz/late`);
- quoting splits (`z"z/la"te`, `zz/la''te`, `$'\x6cate'`);
- `\` escapes;
- `?`, `*`, `[…]`, `[!x]`, `[[:alpha:]]`;
- `./`, `//` and trailing `/.`;
- `..` anywhere;
- `cd zz`, `pushd`, `CDPATH`, `cd z*` and `cd ..` after the move;
- `grep -r`, `rg -L`, `find -L … -exec cat`, `find | xargs cat` and `$(find …)` readers.

The only cap-path allows that leaked were E6, E7 and E8, which come from the tokeniser and from same-command link creation, not from the name rule. The rule's soundness argument holds for words it actually receives.

## Fail-closed (task 2)

`untracked/scratch/00623-review/tools/failclosed.py` was re-run on the fixed tree, cold and built. It forces 11 stops (caps, deadlines, unreadable directories, link targets that cannot be told, depth 0), over 364 probes on 2 fixtures, cold and built: 44 runs, **0 deny-to-not-deny**. The flaggable and quarantine guards were not re-probed beyond their targeted unit tests, which pass.

## Cache forgery (task 3)

The index is in memory only (`link_index`); no project file or env var is read to build or trust it. `LinkNames` is built from `LinkIndex.verify`'s own listing on each call, so nothing persisted feeds it. A link made after the build is seen (the unit tests `test_a_link_made_after_the_build_is_seen`, 14 cases, pass). The reuse window is one tool call (`link_scan_scope`). A link made by an EARLIER command in the same Bash call is the E8 class above, not a cache issue.

## Usability in this repository (task 4)

This was measured in-process with the branch code against `/workspace`. The live daemon runs main's code, so real Bash calls would show main's behaviour.

- **`/workspace` holds 160,146 directories, not about 61,000.** The count includes this review's own fixtures and main worktree.
- **The index builds in 1.9 s and is complete, under its 200,000-directory cap.** It holds 426 link-holding directories, 2,461 directory links and 3,072 links.
- **Every computed move followed by a reader still denies.** That covers `cd ~/x && cat f`, `cd "$(git rev-parse --show-toplevel)" && cat f`, `cd "$(mktemp -d)" && ls` and `cd "$D" && cat CLAUDE.md`. Each takes about 0.85 s, almost all of it index verification.
  - **Why:** 2,461 directory links is past `INDEXED_DIRECTORY_LINK_CAP` (512), so the scan stops.
  - **Where they are:** 2,235 of them are previous reviews' fixtures (`untracked/scratch/00623-review` 1,126 and `00614-review2` 1,109) and 152 are in this worktree's scratch.
  - **Those links are real.** Several of them lead to dummy protected directories, so the deny is correct, not a false positive. Removing those review fixtures would leave about 170 directory links, and the commands would then be judged by name.
- Static commands (`cat README.md`, `cd src && ls`) are allowed in 0.00 s.

## Release note (task 5)

`004-…` matches the final behaviour, with one imprecision: the 512 trigger counts link-holding directories plus directory links, not holding directories alone. That sentence is corrected, and bullets for the two security fixes are added. The note does not mention the per-command verification cost (about 0.85 s at 160,000 directories).

## Tests

`tests/unit/handlers/pre_tool_use/test_secret_file_guard_bracket_link.py` (new):

- **RED before each fix:** 6 failed (bracket) and 3 failed (`..`).
- **GREEN:** 18 passed.

Targeted regression on the fixed tree: every `test_secret_file_guard*`, flaggable and quarantine guard file, `test_secret_file_matching*`, `test_link_index`, `test_recursive_search*` and `test_bounded_walk` (28 files, two chunks): 2,313 passed, 11 skipped, and 1,625 passed; 0 failed. ruff, black and mypy are clean on the changed files. The oracle re-run on the fixed tree leaves exactly E4 to E8.

## Left

- **E4/E5:** parameter defaults (`${X:-path}`), which also expose in-project protected files directly.
- **E6/E7:** extglob words split by the tokeniser.
- **E8:** a link or `cp -s` made earlier in the same command.
- **Usability:** this repository still denies every computed move until the review fixtures are pruned (an owner decision), and costs about 0.85 s per such command.
- The baseline and parent-tip worktrees used here have been removed. The probe fixtures remain in this worktree's `untracked/scratch/rv2/`; they hold links to a dummy and add to the directory-link count, so delete them before measuring usability again.
