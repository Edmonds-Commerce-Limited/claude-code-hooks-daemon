# Builder report: PR #230 round 2 (N710 review findings 4, 5, 6)

Branch `fix-n710-secret-guard-glob-later-parts`. Inputs: the independent review
`261123-opus-independent-review-pr230.md`, findings 4-6; the failed CI job
"Performance sweeps" (run 45246717371, job 137945660997).

## The CI failure is not this PR's code

The failing perf test was `test_subagent_full_qa_blocker.py::TestResidualRoutesReviewRound2::test_a_big_alias_chain_is_judged_quickly`:
1.518 s against `scaled_cpu_seconds(1.5)`. It was the first test to run in
that file, in a collection of 65k items.

- It exercises `find_full_qa_invocation` only. A cProfile of the same call
  spends 0.000 s in `secret_file_matching`.
- Locally the call takes 0.08-0.10 s on the branch and 0.12 s on main.
- Main's perf sweep passed on the previous run (job 137929069171).

Recorded as ledger N717. The bound was NOT loosened. The secret-guard work
below adds a `perf_sweep` test of its own.

## Changes (`src/claude_code_hooks_daemon/utils/secret_file_matching.py`)

1. **Finding 6: reads are shared per command.**
   - A `_GlobListings` set rides on the existing `link_scan_scope` contextvar,
     and `reset_link_scans` clears it. It holds:
     - each directory's listing;
     - each spelled-path probe;
     - each link-only sublist;
     - each finished non-last step;
     - each base's realpath answer.
   - Each directory is listed, and each path probed, once per command.
   - A failed read is cached as its failure (a `_WordGlobStopped`) and is
     re-raised for every later word. It is never cached as an empty listing.
   - `find_protected_mention_strict` (the fallback after a scan gives up) now
     runs inside a scope too. Before, it re-listed every directory for every
     word, with no deadline. It cost 17 s in the 2000-word profile.
   - A last pattern step under a path reached through no link matches only
     that directory's links. A plain match there resolves to its own spelling
     and was never returned, so this narrows nothing.
   - `_component_regex` is `lru_cache`d.
2. **Finding 5: the budget counts distinct reads, shared by every word.**
   - `GLOB_WORD_LISTING_CAP` (512 per word) is replaced by two caps:
     - `GLOB_LISTING_CAP = 4096`: distinct listings and probes per command.
     - `GLOB_WORD_FRONTIER_CAP = 4096`: paths one step of one word keeps, now
       de-duplicated by path; a path reached through a link on any route
       keeps that mark.
   - **Measured:** 40 us per listing and 14 us per lstat+stat probe (warm,
     526 plan folders). 4096 reads is therefore about 0.2 s, and 8x the 527
     folders `CLAUDE/Plan/Completed/*/PLAN.md` walks.
   - **Fail closed:** a spent budget stays spent, so every later word in the
     command is stopped too, even one whose reads were already cached.
     Unreadable still means stopped, and stopped still means deny.
3. **Finding 4: `[^...]` is read as negation everywhere this module uses fnmatch for a shell word.**
   - `LinkNames._component_matches` now uses `_component_spells` (`[^`
     negation, POSIX classes widened). The unreadable-characters rule
     (anything) is kept.
   - `expand_directory_glob` (a globbed `cd`) uses `_component_spells`.
   - The prose-overlap heuristic in `_token_mention_judged` goes through the
     new `_bash_bracket_negation`, which `_component_regex` uses as well.

## Tests (`tests/unit/handlers/pre_tool_use/test_secret_file_guard_glob_later_parts.py`)

All of these were written first and seen failing (15 failed), before the fix.

- **Finding 5:** 600 plain `done/dNNNN/PLAN.md` folders give ALLOW on both
  routes. The same tree with one `PLAN.md` swapped for a link to the dummy
  gives DENY on both routes, and on the Bash route with no index.
- **Finding 6, read counts:**
  - With the index off, one `os.scandir` per directory per command. The
    index's own per-word listing in `protected_file_index._wildcard_links` is
    main's code and is out of scope.
  - A repeated word charges nothing more.
  - The budget is shared across words, and once spent it stays spent.
- **Finding 6, timing:** a `perf_sweep` test runs 2000 words over 300
  directories within `scaled_cpu_seconds(5.0)`.
- **Over the cap:** the over-the-listing-cap test is re-pinned to
  `GLOB_LISTING_CAP` (still DENY). A frontier-cap test is new.
- **Unreadable directory:** it stops every word that meets it within one
  scope.
- **Finding 4:** `LinkNames.reaches` with `[^z]in/late`, `bin/[^z]ate`,
  `[^z]ate`, `[[:alpha:]]in/late` and `kit/[^z]in/late` (reaches), and with
  `[^b]in/late` and `bin/[^l]ate` (does not reach). `expand_directory_glob`
  with `[^z]in`. `cd kit/[^z]in && cat late` gives DENY.

## Timings

Measured in-process with the guard (`untracked/scratch` bench, no index, this
host):

| Case                                               | before (PR head)            | after         | main          |
| -------------------------------------------------- | --------------------------- | ------------- | ------------- |
| `grep -l Complete CLAUDE/Plan/Completed/*/PLAN.md` | 0.007 s DENY                | 0.017 s ALLOW | 0.002 s ALLOW |
| 100 words `wide/*/x<n>*`, 300 dirs                 | 0.383 s                     | 0.036 s       | 0.015 s       |
| 2000 words                                         | 10.1 s DENY (22 s profiled) | 0.77 s ALLOW  | 0.36 s ALLOW  |

## Targeted QA

- **Secret-guard suite:** 4466 passed, 11 skipped in 133 s. This covers:
  - `tests/unit/handlers/pre_tool_use/test_secret_file_guard*.py`;
  - `test_quarantine_artefact_read_guard*.py`;
  - `tests/unit/utils/test_secret_file_matching*.py`;
  - `test_protected_file_index.py`;
  - `test_recursive_search*.py`.
- **Performance sweeps, narrowed:** `pytest -m perf_sweep` over this test
  file and `test_subagent_full_qa_blocker.py` (the file whose test failed on
  CI): 12 passed in 4.3 s.
  - The new 2000-word test took 1.11 s against a bound of
    `scaled_cpu_seconds(5.0)`.
  - The alias-chain test passed.
- **Lint and types:** `ruff check`, `black` and `mypy` on the module are clean.

## Not fixed here (pre-existing on main): ledger N716

Review findings 1-3 are recorded as N716 (security, HIGH), with the review's
reproducers:

- `nocaseglob`;
- extglob words the capture regex truncates;
- implicit `dotglob` via `GLOBIGNORE` or `BASHOPTS`.
