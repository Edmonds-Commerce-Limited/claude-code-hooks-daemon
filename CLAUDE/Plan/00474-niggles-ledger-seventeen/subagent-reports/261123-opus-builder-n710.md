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

The new tests and the link-loop tests pass. The full `test_secret_file_guard*.py` set was run; the results are in the PR.

## Notes

- **Release note.** The note is `CLAUDE/UPGRADES/UNRELEASED/release-notes/089-…`. 088 is the highest number on main, and no origin branch adds 089.
- **No config change.** No config-changes entry was needed.
- **Over-block risk.** A glob needing more than 512 directory listings, or one with more than 4096 matches through links, is now denied. Run-time cost is not measured beyond the test suite. A command made of very many distinct unquoted globs now lists directories per word, because listings are not cached across words.
