# N265: secret_file_guard scan cost

## Hot spot

cProfile on the realistic program (300 events, 11.5 KB): `_globs_can_intersect`
(`utils/secret_file_matching.py`) was 6.8 s of 17.1 s profiled, 48,600 calls. Cause:
`_token_mention` expands a token's brackets into literal spellings
(`s-{event_0["tool_name"]}` gives 9 spellings), and `_glob_intersection_mention` runs
each spelling against all 54 protected patterns through a pure-Python DP grid. Tokens
are unique per event, so memoising on the token does not help. Cost was linear in input
size (0.83 s, 1.59 s, 2.86 s at 75, 150, 300 events) but with a large constant.

## Changes

- `_globs_can_intersect`: after the existing normalisation and the existing
  `_DP_MAX_CELLS` fail-closed cap, a first argument with no `*`/`?` is answered by
  `_wildcard_regex(b).fullmatch(a)` (an `lru_cache`d compile keyed on the pattern
  text only, so no per-request state). Exact, not a heuristic. Only the token side is
  fast-pathed so `test_a_lone_long_star_run_collapses_to_near_zero_cost` (which needs DP
  work for a wildcarded first argument against a literal pattern) passes unchanged.
- `shell_expansion._code_brace_words`: `_outside_every_span` rebuilt the span-start list
  on every call (1,200 calls, 0.46 s profiled); built once now.
- `shell_segmentation.split_unquoted_spans`: the per-character scan of every separator
  is skipped unless the character is a separator's first character (full scan kept if a
  separator is empty).

## Cost, before and after (this host, load average about 20, so noisy)

| Measure (300-event program)            | Before    | After           |
| -------------------------------------- | --------- | --------------- |
| CPU seconds (process_time, unprofiled) | 2.86      | 1.24 to 1.72    |
| `_globs_can_intersect` calls with grid | 48,600    | 0 on this input |
| DP grid cells (30-event program)       | 807,300   | 0               |
| DP cells (60-event test program)       | 1,632,150 | 0               |

The remaining cost is spread thin: `first_matching_glob` (66,786 `_glob_fullmatch` calls,
about 17% of the profile), AST walking for the Python-heredoc exemption, and
`split_unquoted_spans`. None is a single dominant step; I did not chase them.

## Tests

- New `TestScanCostIsBoundedByInputSize` (test_secret_file_guard.py): DP cells per
  command character under 2 (was about 140), and DP cells for a 4x program at most 5x.
  Both are counts from the existing `dp_cell_counter` seam; the class also injects the
  CPU clock and the generous deadline so the verdict cannot depend on host speed. Both
  were red before the fix (1,632,150 cells against a bound of 23,026; the 4x test
  denied on the 5 s deadline).
- New `TestGlobIntersectionAgreesWithReference` (test_secret_file_matching.py): every
  pair of globs over `a b * ?` up to length 4 (116,281 pairs) agrees with an
  independent recursive reference; regex metacharacters in a literal token stay literal.
- Ran unchanged and green: test_secret_file_guard.py, test_secret_file_matching.py,
  test_shell_expansion.py, test_shell_expansion_brace_view.py,
  test_shell_segmentation.py, test_shell_segmentation_inert_heads.py,
  test_shell_segmentation_inert_spans.py, test_shell_segmentation_performance.py,
  test_secret_exemptions_reserved_words.py: 2,304 passed.
- ruff and black clean; `audit_error_hiding.py` and `check_input_contract.py` pass.

## Not verified

- mypy reports one error in test_secret_file_matching.py line 2373
  (`secret_file_matching` does not export `shell_expansion`); it is on a line this
  change did not touch. pyright cannot resolve `pytest` in this worktree's venv (no
  `lsp-venv`), so pyright ran only in a degraded form.
- No test for the `split_unquoted_spans` and `_outside_every_span` changes beyond the
  existing suites, which pass; their speedup is measured only through the whole scan.
- The deployed 5 s deadline was not exercised on a slow host; "half the CPU" is this
  host's number, under load.
- The wider suite and `llm_qa.py` were not run, by instruction.
