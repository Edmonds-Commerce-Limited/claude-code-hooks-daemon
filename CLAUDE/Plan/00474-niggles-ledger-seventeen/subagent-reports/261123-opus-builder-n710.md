# Builder report: N710 (secret guard expands a glob in any path part)

**Branch**: `fix-n710-secret-guard-glob-later-parts`, off `origin/main` `a3486b47b`.

## The defect, as reproduced

Red run on main, with a fixture `proj/kit/bin/late` linking to a dummy protected file outside the project:

- **Write/script route.** Every later-part glob was ALLOWED: `kit/*/late`, `kit/bin/l*`, `kit/**/late`, `k*/*/late`, an absolute `/…/kit/*/late`, from `kit` `b?n/late`, and after a computed or a literal `cd`. This route passes no index.
- **Bash route.** This route denied only through the protected-file index. With `_index` returning None, it ALLOWED all 11 globbed shapes. It also ALLOWED every shape on a link made after the index was built.
- **Past `LINK_DIRECTORY_CAP`.** `could_be_link` returned False for `kit/*/late`, `kit/b?n/late` and `kit/bin/l*`.
- **Already covered on main.** Finite bracket globs (`kit/[b]in/late`) were caught by bracket expansion.

## Fix (`src/claude_code_hooks_daemon/utils/secret_file_matching.py`)

- **New `expand_word_glob(base, pattern, *, default_semantics)`.** It expands a glob in any component and returns the matches that pass through a link. Plain matches resolve to their own spelling, so they are neither returned nor counted.
  - It is bounded by `GLOB_WORD_LISTING_CAP` (512 listings or probes) and `GLOB_WORD_MATCH_CAP` (4096 linked matches).
  - It returns a stopped `Bounded` when it passes a cap, when a directory cannot be listed, or when an entry cannot be classified.
  - When bash's defaults are not certain (`default_globs()`), dot names match and `**` recurses without following links. Otherwise `**` is read as `*`.
  - `[^` is read as `[!`, and a backslash is dropped, which only widens the match.
- **New `_glob_link_mention`.** It feeds each match to the unchanged `_link_mention`. A stopped expansion raises `IncompleteScanError` through `.required()`, and the guard denies it on both routes.
- **Wired into four sites:**
  - the tail of `_token_mention_judged`, bash context only, never for a quoted literal;
  - `find_protected_mention_strict`, gated on its `globbed`;
  - `CwdSet.could_be_link`, where a later-part glob is expanded, and an incomplete expansion counts as a link;
  - `CwdSet._bases_spelling`, where a globbed leading component matches scanned directory names by fnmatch. That covers a glob read above the link's directory after a computed `cd`.

## Tests

The new file `tests/unit/handlers/pre_tool_use/test_secret_file_guard_glob_later_parts.py` covers:

- Bash and Write, from the root, from `kit`, and from an absolute path;
- `**` at depth 0 and depth 2, under both semantics;
- dot names and `shopt -s dotglob`;
- brace plus glob;
- a glob in the directory part with a protected basename;
- a computed `cd` and a literal `cd`;
- the Bash route with no index, and a link made after indexing;
- the over-cap fixture through `could_be_link`;
- fail-closed cases: too many linked matches, too many listings, and an unlistable directory;
- unchanged allows: literal paths, plain matches, no-match globs, and a quoted glob.

The new tests and the link-loop tests pass.

**Existing tests that encoded the hole, now re-pinned.** Two fixtures asserted ALLOW for `cat */*`:

- `test_secret_file_guard_link_resolution.py::TestGlobWildcardOnTheLinkComponent`, from both checkouts;
- `test_secret_file_guard_cwd_fail_closed.py::TestGlobFromADirectoryThatIsALinkOut`, which also covered `cd clean && cat */*`.

In both fixtures `*/*` matches `inner/ilink`, a link to the protected dummy, so the command really reads it. Both are now DENY. In the cwd fixture, the literal `cat inner/ilink` and `cd clean && cat inner/ilink` sit beside them as proof that the glob is judged like its literal, which was already denied.

**One regression, fixed.** N117 expects a name past NAME_MAX (ENAMETOOLONG) to be "absent", and it now is again.

## Second round, after an advisor review

**Shapes fnmatch reads more narrowly than bash.** These were red first, then fixed:

- **POSIX classes** (`[[:alpha:]]`) are now widened to any name. Before this fix the Write route allowed them.
- **Extglob.** `?( *( +( @( !(` is translated to a regex, with `!(…)` read as any name. Before this fix both routes allowed it.
  - The ordinary token stream splits `@(bin|zz)` at `(` and `|`. A command-level pass (`_extglob_words`) now re-reads each whole unquoted extglob word.
  - A group that does not close in its component stops the walk, so it fails closed.
- **`could_be_link`'s first part and `_bases_spelling`** now use the same matcher (`_component_spells`). That covers `[^z]`.
- **Dead code removed:** the unreachable dot-name `continue` in `_globstar`.

**Discriminating fail-closed tests:**

- An unlistable directory is now asserted on the Write route and with `_index` set to None.
- An entry whose `is_symlink()` raises is tested.
- Mutant check: making a stopped walk return `finished([])` turns 4 tests red. The mutant was reverted.

**Real-tree over-block probe** (repository root, handler with no index):

- Under certain bash defaults (this host), these are all allowed: `ls src/**/*.py`, `ls **/*.md`, `ls tests/*/*/*.py`, `cat src/claude_code_hooks_daemon/*/*.py` and `ls CLAUDE/Plan/*/PLAN.md`.
- With semantics uncertain, `ls **/*.md` at the repository root is DENIED, because the globstar walk passes the 512-listing cap through `.git` and `untracked/`. The other commands stay allowed. That deny is the fail-closed outcome the brief asked for. It only happens where shell snapshots cannot confirm defaults, or in a command that runs `shopt`.

**Words the expansion cannot place:**

- `$D/*/late` and `"$PWD"/kit/*/late` are judged exactly like their literal twins; tests assert that the two decisions are equal.
- A `~` form is skipped, just as `_link_targets` skips it for a literal, so the two stay consistent.
- `LinkNames.reaches` is not extended for later-part globs (past the scan cap). Nothing tests it, so it is left as a follow-up.

**Deny reason.** `cat kit/*/late` gets the same `R-SECRET-BASH-MENTION` reason as the literal path. No "could not build the explanation" error appeared in that probe.

Final targeted run: `test_secret_file_guard*.py` gives 3137 passed, 11 skipped. ruff, black and mypy are clean.

## Notes

- **Release note.** The note is `CLAUDE/UPGRADES/UNRELEASED/release-notes/089-…`. 088 is the highest number on main, and no origin branch adds 089.
- **No config change.** No config-changes entry was needed.
- **Over-block risk.** A glob needing more than 512 directory listings, or one with more than 4096 matches through links, is now denied. Run-time cost is not measured beyond the test suite. A command made of very many distinct unquoted globs now lists directories per word, because listings are not cached across words.
